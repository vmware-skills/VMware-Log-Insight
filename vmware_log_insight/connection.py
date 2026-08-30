"""Log Insight (Aria Operations for Logs) REST client with session auth.

Authenticates via ``POST /api/v2/sessions`` with username/password/provider and
carries the returned ``sessionId`` as ``Authorization: Bearer <sessionId>`` on
subsequent calls. The session has a TTL (seconds); it is re-acquired
automatically near expiry.

Per CLAUDE.md 踩坑 #37, HTTP error codes are translated to a teaching
``LogInsightApiError`` in ONE place (``_request``), so callers never surface a
raw httpx traceback: transient gateway errors (502/503/504) and transport
failures get one light retry, a 401 triggers a single re-auth, and 4xx client
errors (e.g. 404 for a bad alert id) are not retried.

Base URL pattern: https://<host>:<port>/api/v2  (default port 9543)
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from vmware_log_insight.config import AppConfig, TargetConfig, load_config

_log = logging.getLogger("vmware-log-insight.connection")

# Refresh the session this many seconds before its TTL actually expires.
_EXPIRY_BUFFER_SEC = 60

# Transient gateway statuses worth one automatic retry. 4xx are NOT retried.
_TRANSIENT_STATUS = frozenset({502, 503, 504})
_RETRY_DELAY_SEC = 2.0

# Trust a successful liveness probe for this long so a burst of connect() calls
# doesn't re-probe GET /sessions/current every time.
_LIVENESS_TTL_SEC = 30.0

# Fallback session lifetime if the server omits ttl (Log Insight default ~30 min).
_DEFAULT_TTL_SEC = 1800


class LogInsightApiError(Exception):
    """A Log Insight API call returned an error or failed to connect.

    Carries a teaching message (status + path + how to fix). ``status_code`` is
    None for transport/timeout failures (no HTTP response was received).
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        method: str | None = None,
        path: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.method = method
        self.path = path


def _hint_for_status(status_code: int) -> str:
    """Return a short, actionable remediation hint for an HTTP error status.

    Deliberately free of the request path. The callers already name the failing
    call, and naming it here too put it in the message twice — 216 of the 539
    characters a 404 on a search path rendered, which pushed the closing remedy
    past ``sanitize()``'s 300-char cap so the agent never received it.
    """
    if status_code == 404:
        return (
            "Check the id — list the parent collection first (e.g. "
            "`vmware-log-insight alert list`) and copy an exact id."
        )
    if status_code == 400:
        return (
            "Bad request — check the query constraints and parameters. Time/field "
            "constraints are path-encoded as field/OPERATOR/value segments."
        )
    if status_code in (401, 403):
        return "Authentication/authorization failed — check the account, password, and provider."
    if status_code == 503:
        return "The appliance is starting up or a service is not ready. Wait and retry."
    if status_code in (502, 504):
        return "The node is busy or a gateway timed out — retry shortly."
    if status_code >= 500:
        return "Server-side error — retry shortly; check Log Insight health."
    return "Check the request and try again."


def _is_tls_verify_error(exc: Exception) -> bool:
    """True if a transport error looks like a TLS certificate verification failure."""
    text = str(exc).lower()
    return "certificate" in text or "ssl" in text or "verify" in text


def _transport_hint(exc: Exception) -> str:
    """Return the remedy for a connection/timeout failure, authored not quoted.

    The exception is read to choose the branch but never interpolated. Its text
    is whatever ssl/socket produced — for a TLS failure that is the certificate
    subject and the hostname it was checked against, for a DNS failure the name
    that failed to resolve. ``_safe_error`` passes ``LogInsightApiError`` through
    verbatim, so quoting the exception would hand all of that to the agent while
    telling the operator nothing they can act on. The full text still reaches
    the server log through ``exc_info``.

    A Log Insight appliance ships with a self-signed certificate, so the TLS
    branch is the likely one on a first connection — and its remedy was the part
    the old message lost to truncation.
    """
    if _is_tls_verify_error(exc):
        return (
            "The certificate could not be verified — for a self-signed appliance "
            "cert set `verify_ssl: false` for this target in "
            "~/.vmware-log-insight/config.yaml."
        )
    return (
        "Check 'host' and 'port' for this target in "
        "~/.vmware-log-insight/config.yaml and that the appliance is reachable "
        "from this machine."
    )


class LogInsightClient:
    """REST client for a single Log Insight instance."""

    def __init__(
        self, target: TargetConfig, password: str, username: str | None = None
    ) -> None:
        self._target = target
        self._base_url = f"https://{target.host}:{target.port}/api/v2"
        self._password = password
        # Resolved by the caller (ConnectionManager) alongside the password so
        # both halves of the credential come from the same read; falls back to
        # the configured username for direct construction.
        self._username = username or target.username
        self._session_id: str | None = None
        self._session_expires_at: float = 0.0
        self._liveness_checked_at: float = 0.0

        if not target.verify_ssl:
            import urllib3

            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        self._client = httpx.Client(
            base_url=self._base_url,
            verify=target.verify_ssl,
            timeout=30.0,
        )
        self._acquire_session()

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def _acquire_session(self) -> None:
        """Acquire a new sessionId from Log Insight.

        Auth errors are translated to ``LogInsightApiError`` here (this runs at
        connect time and on mid-request refresh), so a wrong password (401),
        bad provider (400), or a booting appliance (503) surfaces a teaching
        message instead of a raw httpx traceback.
        """
        payload = {
            "username": self._username,
            "password": self._password,
            "provider": self._target.provider,
        }
        try:
            resp = self._client.post(
                "/sessions", json=payload, headers={"Accept": "application/json"}
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in (400, 401, 403):
                hint = (
                    "Check username/password/provider in "
                    "~/.vmware-log-insight/config.yaml and the password env var in "
                    "~/.vmware-log-insight/.env."
                )
            elif status in (404, 405):
                # _hint_for_status is written for resource calls, where 404
                # genuinely means "wrong id". Reached from here it told the user
                # to run `alert list` and copy an id — a login has no id, and
                # that command performs the authentication that just failed, so
                # following the advice reproduced the error (2026-08-30). On the
                # login endpoint the same status means nothing answers at this
                # path, which is a host/port/appliance question. Kept terse for
                # the same reason as _hint_for_status: the MCP layer renders
                # exceptions through sanitize(str(exc), 300), and a longer
                # version loses its own closing remedy.
                hint = (
                    "Nothing answers at that path — not a credential problem. "
                    "Check host and port in config.yaml (the API is on 9543, "
                    "not 443), and whether a proxy forwards /api/v2."
                )
            else:
                hint = _hint_for_status(status)
            raise LogInsightApiError(
                f"Log Insight authentication failed: POST /sessions returned "
                f"HTTP {status}. {hint} Then run `vmware-log-insight doctor`. "
                f"Configured host: {self._target.host}",
                status_code=status,
                method="POST",
                path="/sessions",
            ) from exc
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise LogInsightApiError(
                f"Log Insight authentication could not connect. "
                f"{_transport_hint(exc)} Then run `vmware-log-insight doctor`. "
                f"Configured host: {self._target.host}",
                method="POST",
                path="/sessions",
            ) from exc

        data = resp.json()
        session_id = data.get("sessionId")
        if not session_id:
            raise ConnectionError(
                # Kept under the 300-char sanitize() cap: at 316 the closing
                # remedy was cut mid-word and no agent ever received it.
                "Log Insight accepted the credentials but returned no "
                "sessionId. Verify host/port in "
                "~/.vmware-log-insight/config.yaml points at a Log Insight "
                "appliance, not a vCenter or a load-balancer front end, then "
                "run `vmware-log-insight doctor`."
            )
        # ttl is a duration in SECONDS (not an epoch). Default ~30 min if absent.
        ttl = data.get("ttl") or _DEFAULT_TTL_SEC
        self._session_id = session_id
        self._session_expires_at = time.time() + float(ttl)
        _log.info(
            "Log Insight session acquired for %s (ttl %.0fs)",
            self._target.host,
            float(ttl),
        )

    def _ensure_session(self) -> None:
        """Re-acquire the session if expired or near expiry."""
        if time.time() >= (self._session_expires_at - _EXPIRY_BUFFER_SEC):
            _log.info("Session expired or near expiry, re-acquiring...")
            self._acquire_session()

    def _headers(self) -> dict[str, str]:
        self._ensure_session()
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._session_id}",
        }

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
        retries: int = 1,
    ) -> httpx.Response:
        """Send one request, recovering from auth and transient failures.

        Layered per the error-recovery contract: (1) transport/timeout and
        transient gateway statuses (502/503/504) are retried once after a short
        delay; (2) a 401/403 triggers a single session re-acquisition (the
        re-issue goes back through the top of the loop so it is covered by the
        same transport-error handling); (3) any remaining error status is
        translated to a teaching ``LogInsightApiError``. 4xx client errors
        (e.g. 404 for a bad id) are NOT retried.
        """
        attempt = 0
        reauthed = False
        while True:
            try:
                resp = self._client.request(
                    method, path, headers=self._headers(), params=params, json=json_data
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt < retries:
                    attempt += 1
                    time.sleep(_RETRY_DELAY_SEC)
                    continue
                raise LogInsightApiError(
                    f"Log Insight request could not connect. "
                    f"{_transport_hint(exc)} Then run `vmware-log-insight "
                    f"doctor`. Configured host: {self._target.host}. "
                    f"Failing call: {method} {path}",
                    method=method,
                    path=path,
                ) from exc

            if resp.status_code in (401, 403) and not reauthed:
                _log.info("Auth error on %s %s, re-acquiring session...", method, path)
                self._acquire_session()
                reauthed = True
                continue

            if resp.status_code in _TRANSIENT_STATUS and attempt < retries:
                attempt += 1
                time.sleep(_RETRY_DELAY_SEC)
                continue

            if resp.status_code >= 400:
                raise LogInsightApiError(
                    f"Log Insight returned HTTP {resp.status_code}. "
                    f"{_hint_for_status(resp.status_code)} "
                    f"Run `vmware-log-insight doctor` if every call to this "
                    f"target fails. Failing call: {method} {path}",
                    status_code=resp.status_code,
                    method=method,
                    path=path,
                )
            return resp

    def get(self, path: str, params: dict[str, Any] | None = None, *, retries: int = 1) -> dict:
        """Single GET request. Returns parsed JSON (or {} for an empty body).

        Pass retries=0 for probes where an error status is itself the answer
        (e.g. a liveness check) to skip the transient back-off.
        """
        resp = self._request("GET", path, params=params, retries=retries)
        return resp.json() if resp.content else {}

    def is_alive(self) -> bool:
        """Check whether the cached client + session are still usable.

        A reachable appliance that returns 5xx (e.g. 503 while a service boots)
        is still "alive": the client and session work, the platform just isn't
        ready, so there's no point rebuilding the connection. Only auth failures
        (401/403) or transport errors mean the cached client is stale.
        """
        try:
            self._request("GET", "/sessions/current", retries=0)
            self._liveness_checked_at = time.time()
            return True
        except LogInsightApiError as exc:
            return exc.status_code is not None and exc.status_code not in (401, 403)
        except Exception:
            return False

    def is_alive_cached(self, ttl: float = _LIVENESS_TTL_SEC) -> bool:
        """Liveness check that skips the HTTP probe within ``ttl`` of the last success."""
        if self._liveness_checked_at and (time.time() - self._liveness_checked_at) < ttl:
            return True
        return self.is_alive()

    def close(self) -> None:
        """Close the HTTP client.

        Log Insight sessions expire on their own TTL, and the public v2 API has
        no verified session-delete endpoint, so we simply drop the local session
        and close the connection pool rather than calling an unconfirmed logout
        path (踩坑 #36 — no hallucinated endpoints).
        """
        self._session_id = None
        self._client.close()


class ConnectionManager:
    """Manages connections to multiple Log Insight targets."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._clients: dict[str, LogInsightClient] = {}

    @classmethod
    def from_config(cls, config: AppConfig | None = None) -> ConnectionManager:
        return cls(config or load_config())

    def connect(self, target_name: str | None = None) -> LogInsightClient:
        """Get or create a LogInsightClient for the specified target."""
        name = target_name or self._config.default_target
        if not name:
            configured = ", ".join(self._config.targets.keys()) or "(none)"
            # Remedy before the target list: the list grows with the deployment
            # and is the expendable half, so a long one must truncate itself
            # rather than the instruction.
            raise ValueError(
                "No target specified and no default target configured. Pass "
                "target=<name>, or set default_target in "
                "~/.vmware-log-insight/config.yaml, then verify with "
                f"`vmware-log-insight doctor`. Available: {configured}"
            )

        if name in self._clients:
            if self._clients[name].is_alive_cached():
                return self._clients[name]
            self._clients[name].close()
            del self._clients[name]

        target_cfg = self._config.get_target(name)
        if target_cfg is None:
            available = ", ".join(self._config.targets.keys())
            raise ValueError(
                f"Target '{name}' not found. Copy an exact name from the list "
                "below, or add the target to ~/.vmware-log-insight/config.yaml "
                "and verify it with `vmware-log-insight doctor`. "
                f"Available: {available}"
            )

        # Resolve both halves of the credential together — a username left
        # behind by a rotation would pair with the new password and fail.
        client = LogInsightClient(
            target_cfg, target_cfg.get_password(name), target_cfg.get_username(name)
        )
        self._clients[name] = client
        return client

    def disconnect(self, target_name: str) -> None:
        if target_name in self._clients:
            self._clients[target_name].close()
            del self._clients[target_name]

    def disconnect_all(self) -> None:
        for name in list(self._clients):
            self.disconnect(name)

    def list_targets(self) -> list[str]:
        return list(self._config.targets.keys())
