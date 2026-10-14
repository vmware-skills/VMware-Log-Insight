"""Alert queries: GET /api/v2/alerts, /alerts/{id}, /alerts/{id}/history.

Read-only — this skill never creates, edits, or deletes alerts. All text is
sanitized.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from vmware_policy import paginated, sanitize

if TYPE_CHECKING:
    from vmware_log_insight.connection import LogInsightClient

_DEFAULT_LIMIT = 50


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
    data = client.get("/alerts")
    items = data.get("alerts", []) or []
    filt = name_filter.lower() if name_filter else None
    matched: list[dict] = []
    for a in items:
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
    if not alert_id:
        raise ValueError(
            "alert_id must not be empty: expected an alert id. Run list_log_alerts "
            "(or `vmware-log-insight alert list`) and copy an exact value from "
            "a row's 'id' field."
        )
    data = client.get(f"/alerts/{alert_id}")
    summary = _summarize_alert(data)
    summary["raw_keys"] = sorted(k for k in data if isinstance(k, str))
    return summary


def get_alert_history(
    client: LogInsightClient, alert_id: str, limit: int = _DEFAULT_LIMIT
) -> dict:
    """List recent trigger-history records for an alert.

    Args:
        client: Authenticated Log Insight client.
        alert_id: The alert id (from list_alerts).
        limit: Max history records to return. Default 50.

    Returns:
        The family list envelope; `items` is a list of {timestamp_ms, info}
        records, most recent first as returned. The API hands back the whole
        history in one GET and `limit` slices it here, so `total` is the real
        record count at no extra cost — a page that exactly fills `limit` is
        still reported complete when it genuinely is.
    """
    if not alert_id:
        raise ValueError(
            "alert_id must not be empty: expected an alert id. Run list_log_alerts "
            "(or `vmware-log-insight alert list`) and copy an exact value from "
            "a row's 'id' field, then pass it to get_log_alert_history."
        )
    data = client.get(f"/alerts/{alert_id}/history")
    records = data.get("history", data.get("records", [])) or []
    out: list[dict] = []
    for r in records[:limit]:
        out.append(
            {
                "timestamp_ms": r.get("timestamp", r.get("time")),
                "info": sanitize(str(r.get("info", r.get("message", ""))), 500),
            }
        )
    return paginated(out, limit=limit, total=len(records))
