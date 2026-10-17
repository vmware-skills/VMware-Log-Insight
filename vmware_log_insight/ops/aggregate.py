"""Aggregated-events queries: GET /api/v2/aggregated-events/{constraints}.

Produces a numeric time series (counts by default) over a window, then runs a
simple z-score spike detection so the agent gets "where did logs burst?" without
scanning raw events. Pure aggregation math is unit-testable offline.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from vmware_log_insight.constraints import build_constraints, parse_duration_ms
from vmware_log_insight.ops._shape import expect_object
from vmware_log_insight.ops.search import summarize_event, whole_word_note

if TYPE_CHECKING:
    from vmware_log_insight.connection import LogInsightClient

_log = logging.getLogger("vmware-log-insight.ops.aggregate")

# Mirrors tests/eval/spec/api_index.py AGGREGATION_FUNCTIONS.
VALID_AGGREGATIONS = frozenset(
    {"COUNT", "UCOUNT", "AVG", "MIN", "MAX", "SUM", "STDDEV", "VARIANCE", "SAMPLE"}
)

# Verified on 8.18.7 (2026-10-17): these two answer HTTP 400 when given an
# aggregation-field; the other seven answer HTTP 400 without one.
_NO_FIELD = frozenset({"COUNT", "SAMPLE"})
FIELD_AGGREGATIONS = VALID_AGGREGATIONS - _NO_FIELD


def _normalize_bins(data: dict) -> list[dict]:
    """Pull bins out of the aggregated-events response, oldest first.

    8.18.7 sends ``bins: [{minTimestamp, minTimestampString, maxTimestamp,
    maxTimestampString, value}]``, newest first. ``value`` is a number, except for
    SAMPLE where it is one whole event — summarized and sanitized like a
    search_logs event, because it is raw log text.
    """
    out: list[dict] = []
    for b in data.get("bins") or []:
        if not isinstance(b, dict):
            continue
        value = b.get("value")
        if isinstance(value, dict):
            value = summarize_event(value)
        elif not isinstance(value, (int, float)) or isinstance(value, bool):
            value = None
        out.append(
            {"timestamp_ms": b.get("minTimestamp"), "end_ms": b.get("maxTimestamp"), "value": value}
        )
    out.sort(key=lambda b: b["timestamp_ms"] if isinstance(b["timestamp_ms"], int) else 0)
    return out


def detect_spikes(bins: list[dict], z_threshold: float = 2.0) -> list[dict]:
    """Flag bins whose value exceeds mean + z_threshold * stddev.

    Needs >=3 bins for a meaningful baseline; returns nothing below that or when
    the series is flat (stddev 0), rather than calling everything a spike.
    """
    values = [b["value"] for b in bins if isinstance(b.get("value"), (int, float))]
    if len(values) < 3:
        return []
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    stddev = variance**0.5
    if stddev == 0:
        return []
    spikes = []
    for b in bins:
        v = b.get("value")
        if isinstance(v, (int, float)):
            z = (v - mean) / stddev
            if z >= z_threshold:
                spikes.append({**b, "zscore": round(z, 2)})
    return spikes


def aggregate_events(
    client: LogInsightClient,
    *,
    text: str | None = None,
    last: str | int | None = None,
    begin_ms: int | None = None,
    end_ms: int | None = None,
    filters: list[tuple[str, str, str]] | None = None,
    aggregation: str = "COUNT",
    field: str | None = None,
    bin_width_ms: int = 60000,
) -> dict:
    """Aggregate matching events into a time series and detect spikes.

    Args:
        client: Authenticated Log Insight client.
        text / last / begin_ms / end_ms / filters: Same query semantics as
            search_events (default last hour if no window is given).
        aggregation: One of COUNT, UCOUNT, AVG, MIN, MAX, SUM, STDDEV, VARIANCE,
            SAMPLE. Default COUNT. COUNT and SAMPLE take no field; the other
            seven need one.
        field: The field the function is applied to (a name from list_fields),
            e.g. UCOUNT of ``hostname``. Required for every function except
            COUNT and SAMPLE, refused for those two.
        bin_width_ms: Width of each time bin in milliseconds. Default 60000 (1m).

    Returns:
        {"aggregation", "field", "bin_width_ms", "constraints", "bins":
        [{timestamp_ms, end_ms, value}] oldest first, "spikes":[{timestamp_ms,
        end_ms, value, zscore}]}, plus "note" when the series is empty for a
        reason worth saying.
    """
    aggregation = aggregation.upper()
    if aggregation not in VALID_AGGREGATIONS:
        raise ValueError(
            f"unknown aggregation {aggregation!r}; valid: "
            f"{sorted(VALID_AGGREGATIONS)}. Re-run aggregate_logs with one of "
            "those exact strings; COUNT is the default and answers "
            "'how many events per bin'."
        )
    if aggregation in _NO_FIELD and field:
        raise ValueError(
            f"{aggregation} takes no field (the appliance answers HTTP 400). "
            f"Re-run aggregate_logs without field, or use UCOUNT with "
            f"field={field!r} to count distinct values of it."
        )
    if aggregation in FIELD_AGGREGATIONS and not field:
        raise ValueError(
            f"{aggregation} needs a field to apply to (the appliance answers HTTP "
            "400 without one). Pass field=<name> — e.g. UCOUNT with "
            "field='hostname' — and pick names from list_log_fields."
        )
    if bin_width_ms <= 0:
        raise ValueError(
            f"bin_width_ms must be positive (got {bin_width_ms}). Re-run "
            "aggregate_logs with bin_width_ms=60000 for 1-minute bins, or a "
            "larger value for coarser bins over a long window."
        )

    constraints = build_constraints(
        text=text, last=last, begin_ms=begin_ms, end_ms=end_ms, filters=filters
    )
    params: dict = {"aggregation-function": aggregation, "bin-width": bin_width_ms}
    if field:
        params["aggregation-field"] = field
    data = expect_object(
        client.get(f"/aggregated-events/{constraints}", params=params),
        "GET /aggregated-events",
    )
    bins = _normalize_bins(data)
    filled = False
    if aggregation in _ZERO_WHEN_EMPTY and bins:
        window = _window_ms(last, begin_ms, end_ms)
        bins, filled = _fill_empty_bins(bins, window, bin_width_ms)
    result = {
        "aggregation": aggregation,
        "field": field,
        "bin_width_ms": bin_width_ms,
        "constraints": constraints,
        "bins": bins,
        "spikes": detect_spikes(bins),
    }
    if filled:
        result["filled_empty_bins"] = True
    notes = []
    if not bins and (note := whole_word_note(text)):
        notes.append(note)
    if not bins and field:
        # 8.18.7 answers an unknown field with an empty series, not an error,
        # so "no bins" cannot be read as "no events".
        notes.append(
            f"No bins. Either nothing matched in the window, or {field!r} is not "
            "a field this appliance has — check the name with list_log_fields."
        )
    if notes:
        result["note"] = " ".join(notes)
    return result


# A bin with no events is 0 for these; for AVG/MIN/MAX/... it has no value.
_ZERO_WHEN_EMPTY = frozenset({"COUNT", "UCOUNT"})
# Past this many bins the series is too fine to pad; it is returned as sent.
_MAX_FILLED_BINS = 5000


def _window_ms(
    last: str | int | None, begin_ms: int | None, end_ms: int | None
) -> tuple[int, int]:
    """The query window as (start, end) epoch ms, as build_constraints reads it."""
    now = int(time.time() * 1000)
    if begin_ms is not None or end_ms is not None:
        return (begin_ms if begin_ms is not None else 0, end_ms if end_ms is not None else now)
    return (now - parse_duration_ms(last if last is not None else "1h"), now)


def _fill_empty_bins(
    bins: list[dict], window: tuple[int, int], width: int
) -> tuple[list[dict], bool]:
    """Add the zero bins 8.18.7 leaves out, so spikes are measured against quiet.

    The appliance omits bins with no events (verified 2026-10-17: "warning" over
    an hour of 1-minute bins came back as 4 bins). A burst after a quiet stretch
    then arrives as one or two bins, the baseline is the burst itself, and no
    spike is reported. Bins are aligned to multiples of the width (as the
    appliance aligns them). A window with no start (end_ms only), or one that
    would need more than _MAX_FILLED_BINS, is only filled between the bins sent.
    """
    starts = [b["timestamp_ms"] for b in bins if isinstance(b["timestamp_ms"], int)]
    if not starts:
        return bins, False
    lo = window[0] if window[0] > 0 else min(starts)
    first = (min(lo, min(starts)) // width) * width
    last = max(max(starts), ((window[1] - 1) // width) * width)
    if (last - first) // width + 1 > _MAX_FILLED_BINS:
        first, last = min(starts), max(starts)
        if (last - first) // width + 1 > _MAX_FILLED_BINS:
            return bins, False
    present = {b["timestamp_ms"] for b in bins}
    extra = [
        {"timestamp_ms": t, "end_ms": t + width - 1, "value": 0}
        for t in range(first, last + 1, width)
        if t not in present
    ]
    if not extra:
        return bins, False
    merged = sorted(bins + extra, key=lambda b: b["timestamp_ms"] if isinstance(b["timestamp_ms"], int) else 0)
    return merged, True
