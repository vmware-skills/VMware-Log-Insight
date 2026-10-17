"""Event search: GET /api/v2/events/{constraints}.

Returns high-signal event summaries (timestamp + text + a flattened fields dict),
default-paginated, with the query text passed back so the caller can refine.
All API text passes through sanitize() (prompt-injection defence).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from vmware_policy import sanitize

from vmware_log_insight.constraints import build_constraints
from vmware_log_insight.ops._shape import expect_object

if TYPE_CHECKING:
    from vmware_log_insight.connection import LogInsightClient

_log = logging.getLogger("vmware-log-insight.ops.search")

# Family rule: search over list. Default page size kept small and high-signal.
# The appliance accepts up to 20000, but on 8.18.7 that was a 16 MB result that
# took 31 s and was stored whole in the audit database (2026-10-17). Measured on
# the same appliance, one summarized event is ~650 chars (the fields dict is most
# of it): 50 events ~32 KB, 200 ~130 KB — already more than an agent should read.
# A larger request is lowered to this and the result says so.
_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200


def _field_value(f: dict, text: str) -> str:
    """The value of one event field, sanitized.

    Most fields carry ``content``. The syslog header fields (hostname, appname,
    procid on 8.18.7) instead carry ``startPosition`` + ``length`` into the
    event's own text, so the value is a slice of that text — sliced from the raw
    text, before sanitizing changes its length. Up to 2.4.0 these read as "".
    """
    if "content" in f:
        return sanitize(str(f.get("content", "")), 500)
    start, length = f.get("startPosition"), f.get("length")
    if (
        isinstance(start, int)
        and isinstance(length, int)
        and not isinstance(start, bool)
        and 0 <= start
        and 0 < length
        and start + length <= len(text)
    ):
        return sanitize(text[start : start + length], 500)
    return ""


def _flatten_fields(event: dict) -> dict[str, str]:
    """Flatten Log Insight's ``fields: [{name, content | startPosition+length}]``.

    A plain dict rendering is handled too. Values are sanitized.
    """
    raw = event.get("fields")
    text = str(event.get("text", ""))
    out: dict[str, str] = {}
    if isinstance(raw, list):
        for f in raw:
            if not isinstance(f, dict):
                continue
            name = f.get("name")
            if name:
                out[sanitize(str(name), 200)] = _field_value(f, text)
    elif isinstance(raw, dict):
        for name, content in raw.items():
            out[sanitize(str(name), 200)] = sanitize(str(content), 500)
    return out


def summarize_event(event: dict) -> dict:
    """Project one raw event onto the high-signal summary we return.

    Also used for the event a SAMPLE aggregation returns per bin.
    """
    return {
        "timestamp_ms": event.get("timestamp"),
        "text": sanitize(str(event.get("text", "")), 1000),
        "fields": _flatten_fields(event),
    }


def search_events(
    client: LogInsightClient,
    *,
    text: str | None = None,
    last: str | int | None = None,
    begin_ms: int | None = None,
    end_ms: int | None = None,
    filters: list[tuple[str, str, str]] | None = None,
    limit: int = _DEFAULT_LIMIT,
) -> dict:
    """Search log events within a time window.

    Args:
        client: Authenticated Log Insight client.
        text: Free-text search, sent with CONTAINS. On 8.18.7 that matches whole
            tokens, not substrings: "localhost" matches, "localdom" does not.
        last: Relative window ("1h", "30m", int seconds). Default last hour if no
            window is given. Mutually exclusive with begin_ms/end_ms.
        begin_ms / end_ms: Absolute epoch-ms window.
        filters: Extra (field, operator, value) constraints.
        limit: Max events to return (1..200). Default 50 — narrow with text /
            the window rather than raising this. A larger value is lowered to
            200 and the result's "note" says so.

    Returns:
        {"count", "complete" (bool, False if the server truncated), "constraints"
        (the query string used), "events": [{timestamp_ms, text, fields}]}, plus
        "note" when the limit was lowered.
    """
    requested = limit
    limit = max(1, min(limit, _MAX_LIMIT))
    constraints = build_constraints(
        text=text, last=last, begin_ms=begin_ms, end_ms=end_ms, filters=filters
    )
    data = expect_object(
        client.get(f"/events/{constraints}", params={"limit": limit}), "GET /events"
    )

    events = [summarize_event(e) for e in data.get("events") or [] if isinstance(e, dict)]
    result = {
        "count": len(events),
        # `complete=False` means the server returned a partial result set.
        "complete": data.get("complete", True),
        "constraints": constraints,
        "events": events,
    }
    if requested > _MAX_LIMIT:
        result["note"] = (
            f"limit {requested} was lowered to {_MAX_LIMIT}, the most this tool "
            "returns. Narrow the window or the text, or use aggregate_logs to "
            "see where events cluster."
        )
    return result
