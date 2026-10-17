"""Alert queries: GET /api/v2/alerts, /alerts/{id}, /alerts/{id}/history.

Read-only — this skill never creates, edits, or deletes alerts. All text is
sanitized.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from urllib.parse import quote

from vmware_policy import paginated, sanitize

from vmware_log_insight.connection import LogInsightApiError
from vmware_log_insight.ops._shape import expect_list, expect_object

if TYPE_CHECKING:
    from vmware_log_insight.connection import LogInsightClient

_DEFAULT_LIMIT = 50

# 8.18.7 alert ids are UUIDs. Allow a little more than that (content packs and
# older releases may differ) but nothing that can leave /alerts/<id>: no '/',
# no '?', no whitespace, and not '.' or '..' (which a URL normaliser resolves).
_ALERT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")


def _alert_segment(alert_id: str) -> str:
    """The URL path segment for a well-formed alert id; refuse anything else.

    Up to 2.4.0 the id was interpolated raw, so ``alert_id="../version"`` reached
    ``GET /api/v2/version``. Read-only, but a tool must only call what it names.
    The caller keeps the f-string path at the call site so the spec-conformance
    scan still sees which endpoint it is.
    """
    if not alert_id:
        raise ValueError(
            "alert_id must not be empty: expected an alert id. Run list_log_alerts "
            "(or `vmware-log-insight alert list`) and copy an exact value from "
            "a row's 'id' field."
        )
    if not _ALERT_ID.fullmatch(alert_id):
        raise ValueError(
            f"alert_id {sanitize(alert_id, 80)!r} is not an alert id (ids are "
            "UUIDs such as 1205ef1d-2b11-37ea-9acc-b0a745e61112). Run "
            "list_log_alerts and copy an exact value from a row's 'id' field."
        )
    return quote(alert_id, safe="")


def _raise_if_unknown_id(exc: LogInsightApiError, path: str) -> None:
    """Re-raise an unknown-id answer with advice that can work.

    8.18.7 answers HTTP 404 for an unknown UUID and HTTP 500 for an id that is
    not a UUID (both verified 2026-10-17); the connection layer's generic 5xx
    hint says "retry shortly" — advice that can never work for a wrong id.
    """
    if exc.status_code in (404, 500):
        raise LogInsightApiError(
            f"Log Insight returned HTTP {exc.status_code} for GET {path}. "
            "On 8.18.7 that is what an alert id the appliance does not know "
            "returns. Run list_log_alerts and copy an exact id; if that id "
            "also fails, check the appliance's health.",
            status_code=exc.status_code,
            method="GET",
            path=path,
        ) from exc


def _summarize_alert(a: dict) -> dict:
    """Project one alert onto high-signal summary fields."""
    return {
        "id": sanitize(str(a.get("id", a.get("alertId", ""))), 100),
        "name": sanitize(str(a.get("name", "")), 200),
        "enabled": a.get("enabled"),
        "info": sanitize(str(a.get("info", a.get("description", ""))), 500),
    }


def list_alerts(
    client: LogInsightClient,
    name_filter: str | None = None,
    limit: int = _DEFAULT_LIMIT,
) -> dict:
    """List defined alerts.

    Args:
        client: Authenticated Log Insight client.
        name_filter: Optional case-insensitive substring filter on alert name.
        limit: Max alerts to return. Default 50.

    Returns:
        The family list envelope; `items` is a list of {id, name, enabled, info}
        — pass an id to get_alert for details. `total` is the real count of
        alerts matching `name_filter`: the API returns the whole collection in
        one GET and the filter runs here, so counting the matches costs nothing
        beyond the request already made.
    """
    items = expect_list(client.get("/alerts"), "GET /alerts")
    filt = name_filter.lower() if name_filter else None
    matched: list[dict] = []
    for a in items:
        if not isinstance(a, dict):
            continue
        summary = _summarize_alert(a)
        if filt and filt not in summary["name"].lower():
            continue
        matched.append(summary)
    return paginated(matched[:limit], limit=limit, total=len(matched))


def get_alert(client: LogInsightClient, alert_id: str) -> dict:
    """Get full details for one alert by id.

    Args:
        client: Authenticated Log Insight client.
        alert_id: The alert id (from list_alerts).

    Returns:
        The alert's full (sanitized) detail dict.
    """
    seg = _alert_segment(alert_id)
    try:
        data = client.get(f"/alerts/{seg}")
    except LogInsightApiError as exc:
        _raise_if_unknown_id(exc, f"/alerts/{seg}")
        raise
    data = expect_object(data, "GET /alerts/{id}")
    summary = _summarize_alert(data)
    summary["raw_keys"] = sorted(k for k in data if isinstance(k, str))
    return summary


# The appliance pages history itself (limit default 20, max 50 per its API docs);
# one page is all this tool reads.
_HISTORY_PAGE_MAX = 50
# Each trigger record carries up to 10 matching events; a few say what fired.
_MESSAGES_PER_RECORD = 3


def _summarize_trigger(r: dict) -> dict:
    """One trigger record: when it fired, whether acknowledged, a few events.

    Verified on 8.18.7 (2026-10-17, a temporary alert that fired twice):
    ``{alertId, triggerTimestamp, acknowledged, resultUrl, messages: [{text,
    timestamp, staticFields, extractedFields}]}`` with up to 10 messages. Up to
    2.4.0 this read ``timestamp``/``info``, which a record does not have, so
    every row came back as ``{timestamp_ms: null, info: ""}``.
    """
    messages = [m for m in r.get("messages") or [] if isinstance(m, dict)]
    return {
        "timestamp_ms": r.get("triggerTimestamp"),
        "acknowledged": r.get("acknowledged"),
        "message_count": len(messages),
        "messages": [
            {"timestamp_ms": m.get("timestamp"), "text": sanitize(str(m.get("text", "")), 500)}
            for m in messages[:_MESSAGES_PER_RECORD]
        ],
    }


def get_alert_history(
    client: LogInsightClient, alert_id: str, limit: int = _DEFAULT_LIMIT
) -> dict:
    """List recent trigger-history records for an alert, most recent first.

    Args:
        client: Authenticated Log Insight client.
        alert_id: The alert id (from list_alerts).
        limit: Max records to return, 1..50 (the appliance's own page cap).
            Default 50. A larger value is lowered to 50 and "note" says so.

    Returns:
        The family list envelope; `items` is a list of {timestamp_ms,
        acknowledged, message_count, messages: [{timestamp_ms, text}]} (at most
        3 of the record's events). The appliance pages history, so `total` is
        known only when the page came back short; a full page is reported as
        possibly truncated.
    """
    seg = _alert_segment(alert_id)
    page = max(1, min(limit, _HISTORY_PAGE_MAX))
    try:
        records = client.get(f"/alerts/{seg}/history", params={"limit": page})
    except LogInsightApiError as exc:
        _raise_if_unknown_id(exc, f"/alerts/{seg}/history")
        raise
    records = expect_list(records, "GET /alerts/{id}/history")
    records = [r for r in records if isinstance(r, dict)][:page]
    out = [_summarize_trigger(r) for r in records]
    total = len(out) if len(out) < page else None
    result = paginated(out, limit=page, total=total)
    if limit > _HISTORY_PAGE_MAX:
        result["note"] = (
            f"limit {limit} was lowered to {_HISTORY_PAGE_MAX}, the most the "
            "appliance returns in one history page."
        )
    return result
