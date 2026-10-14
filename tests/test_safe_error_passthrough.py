"""The skill's most common first-run failure reached the agent as a class name.

``_safe_error`` reduces unrecognised exceptions to ``"<Class>: operation
failed."`` so raw Log Insight response bodies and host:port pairs cannot leak.
Its allowlist was assembled from the exception types the *tool* layer raises —
``LogInsightApiError`` and the validation errors — and stopped there.

``config.get_password`` raises a bare ``OSError`` naming the environment
variable to set, and every tool in this skill reaches it: ``_get_connection`` →
``ConnectionManager.connect`` → ``get_password``. So the first thing a new
operator hits, before a single query runs, was::

    OSError: operation failed.

instead of ``Set environment variable: VMWARE_LOG_INSIGHT_PROD_PASSWORD``.

That is the case where the message *is* the remedy — there is nothing else to
work from, no hint that names the variable, and the variable is per-target so it
cannot be guessed. Nothing caught it because the CLI path prints the exception
in full and the connection tests assert on the raise site, never on what the MCP
wrapper leaves of it.

``RuntimeError`` is not on the list and must not be added. It is the generic
catch-all: allowing it would pass any library's raw text through as though this
package had authored it, which is the leak the wrapper exists to stop.

The first repair of that defect overshot: it admitted bare ``OSError``, and
``sanitize()`` only strips control characters and truncates — it redacts
nothing, so every other OS-level failure came through with it. The passthrough
is now the narrow ``ConfigError`` that ``config.py`` actually raises, and TLS
errors are reduced *before* the allowlist is consulted, because
``ssl.SSLCertVerificationError`` also inherits from ``ValueError`` and an
allowlist cannot express "not this one".
"""

from __future__ import annotations

import socket
import ssl

import pytest

from vmware_log_insight.config import ConfigError, TargetConfig
from vmware_log_insight.connection import LogInsightApiError
from vmware_log_insight.mcp_server._shared import _safe_error

TEACHING = (
    "Target 'prod' not found. Available: lab, staging. Copy an exact name from "
    "that list, or add the target to ~/.vmware-log-insight/config.yaml."
)

ENV_KEY = "VMWARE_LOG_INSIGHT_PROD_PASSWORD"
HOSTNAME = "loginsight-prod.corp.example.com"


def test_missing_password_names_the_variable_to_set(monkeypatch):
    """The defect this test exists for, raised the way the package raises it.

    Driven through ``get_password`` rather than fabricated: the previous version
    constructed a bare ``OSError`` by hand and would have kept passing no matter
    what type ``config.py`` actually raised.
    """
    monkeypatch.delenv(ENV_KEY, raising=False)
    with pytest.raises(ConfigError) as exc_info:
        TargetConfig(host="h", username="u").get_password("prod")

    assert ENV_KEY in _safe_error(exc_info.value, "search_logs")


def test_config_error_is_still_an_oserror():
    """The CLI paths that predate the narrow type catch ``OSError``."""
    assert issubclass(ConfigError, OSError)


def test_api_error_keeps_its_message():
    """The connection layer authors these to carry a corrected next step."""
    assert _safe_error(LogInsightApiError(TEACHING), "search_logs") == TEACHING


@pytest.mark.parametrize(
    "exc_type",
    [ValueError, KeyError, FileNotFoundError, PermissionError, ConnectionError, ConfigError],
)
def test_deliberate_errors_pass_through(exc_type):
    assert "prod" in _safe_error(exc_type(TEACHING), "search_logs")


def test_os_level_failures_no_longer_carry_the_hostname():
    """Why the passthrough is ``ConfigError`` and not the base class it extends.

    A DNS failure names the host it could not resolve. That text is the
    resolver's, not this package's. Put ``OSError`` back and this is the
    assertion that goes red.
    """
    out = _safe_error(socket.gaierror(8, f"nodename nor servname provided: {HOSTNAME}"), "t")
    assert out == "gaierror: operation failed."
    assert HOSTNAME not in out


def test_tls_errors_are_reduced_despite_inheriting_valueerror():
    """The reduction has to run *before* the allowlist, not inside it.

    ``ssl.SSLCertVerificationError`` inherits from ``ValueError`` as well as
    ``OSError``, and ``ValueError`` has been on the allowlist throughout — so
    removing ``OSError`` on its own changes nothing here. Its message quotes the
    certificate subject and the hostname it was checked against.
    """
    exc = ssl.SSLCertVerificationError(
        1,
        "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed "
        f"certificate in certificate chain, subject 'CN={HOSTNAME},O=Corp' (_ssl.c:1006)",
    )
    assert isinstance(exc, ValueError), "the co-inheritance this guard exists for is gone"

    out = _safe_error(exc, "search_logs")
    assert out == "SSLCertVerificationError: operation failed."
    assert HOSTNAME not in out


def test_unplanned_exceptions_are_still_reduced():
    """The redaction this allowlist exists for has to keep working."""
    out = _safe_error(RuntimeError("https://admin:hunter2@li.internal/api/x"), "search_logs")
    assert out == "RuntimeError: operation failed."
    assert "hunter2" not in out


def test_runtime_error_is_not_a_teaching_error():
    """RuntimeError is the generic catch-all — allowlisting it reopens the leak."""
    assert _safe_error(RuntimeError(TEACHING), "search_logs") == "RuntimeError: operation failed."


def test_message_is_still_truncated():
    """Length capping is the other half of the guard."""
    assert len(_safe_error(LogInsightApiError("x" * 900), "search_logs")) <= 300
