"""Aggregated-events queries: GET /api/v2/aggregated-events/{constraints}.

Produces a numeric time series (counts by default) over a window, then runs a
simple z-score spike detection so the agent gets "where did logs burst?" without
scanning raw events. Pure aggregation math is unit-testable offline.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from vmware_log_insight.constraints import build_constraints

if TYPE_CHECKING:
    from vmware_log_insight.connection import LogInsightClient

_log = logging.getLogger("vmware-log-insight.ops.aggregate")

# Mirrors tests/eval/spec/api_index.py AGGREGATION_FUNCTIONS.
VALID_AGGREGATIONS = frozenset(
    {"COUNT", "UCOUNT", "AVG", "MIN", "MAX", "SUM", "STDDEV", "VARIANCE", "SAMPLE"}
)


def _normalize_bins(data: dict) -> list[dict]:
    """Pull (timestamp_ms, value) bins out of the aggregated-events response.

    Defensive across wire variants: bins may live under ``bins`` and carry the
    count as ``value`` or ``count``; the timestamp as ``timestamp`` or ``time``.
    """
    out: list[dict] = []
    for b in data.get("bins", data.get("aggregatedEvents", [])) or []:
        ts = b.get("timestamp", b.get("time"))
        value = b.get("value", b.get("count", 0))
        out.append({"timestamp_ms": ts, "value": value})
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
    bin_width_ms: int = 60000,
) -> dict:
    """Aggregate matching events into a time series and detect spikes.

    Args:
        client: Authenticated Log Insight client.
        text / last / begin_ms / end_ms / filters: Same query semantics as
            search_events (default last hour if no window is given).
        aggregation: One of COUNT, UCOUNT, AVG, MIN, MAX, SUM, STDDEV, VARIANCE,
            SAMPLE. Default COUNT.
        bin_width_ms: Width of each time bin in milliseconds. Default 60000 (1m).

    Returns:
        {"aggregation", "bin_width_ms", "constraints", "bins":[{timestamp_ms,
        value}], "spikes":[{timestamp_ms, value, zscore}]}.
    """
    aggregation = aggregation.upper()
    if aggregation not in VALID_AGGREGATIONS:
        raise ValueError(
            f"unknown aggregation {aggregation!r}; valid: "
            f"{sorted(VALID_AGGREGATIONS)}. Re-run aggregate_logs with one of "
            "those exact strings; COUNT is the default and answers "
            "'how many events per bin'."
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
    data = client.get(
        f"/aggregated-events/{constraints}",
        params={"aggregation-function": aggregation, "bin-width": bin_width_ms},
    )
    bins = _normalize_bins(data)
    return {
        "aggregation": aggregation,
        "bin_width_ms": bin_width_ms,
        "constraints": constraints,
        "bins": bins,
        "spikes": detect_spikes(bins),
    }
