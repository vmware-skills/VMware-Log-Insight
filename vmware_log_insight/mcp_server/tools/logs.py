"""LOG tools (4, read-only): log_search, log_aggregate, log_fields, log_version.

Each resolves the connection/error helpers through ``vmware_log_insight.mcp_server.server``
at call
time, so patching ``server._get_connection`` governs every tool.
"""

from typing import Optional

from vmware_policy import vmware_tool

from vmware_log_insight.mcp_server._shared import mcp

_READ = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}


@mcp.tool(annotations=_READ)
@vmware_tool(risk_level="low")
def log_search(
    text: Optional[str] = None,
    last: Optional[str] = None,
    begin_ms: Optional[int] = None,
    end_ms: Optional[int] = None,
    limit: int = 50,
    target: Optional[str] = None,
) -> dict:
    """[READ] Search Log Insight events within a time window.

    WHEN: to find the actual log lines behind an incident (e.g. what vmkernel
    logged during a storage event). For "where did logs burst?" use
    log_aggregate instead; for vCenter alarms use vmware-monitor.

    RETURNS: {count, complete (False if truncated), constraints,
    events: [{timestamp_ms, text, fields}]}. Feed events to vmware-debug
    incident_timeline to correlate across sources. Read-only.

    Args:
        text: Free-text substring matched against the event message with the
            CONTAINS operator — not a regex and not a full query expression.
            Omit to match every event in the window. To filter on an extracted
            field instead, discover names with log_fields; this tool exposes no
            field-filter parameter.
        last: Relative window ending now, as a quantity plus a unit suffix —
            s, m, h or d ("30m", "2h", "7d") — or a bare number of seconds.
            Anything else raises a ValueError naming the accepted forms. Cannot
            be combined with begin_ms/end_ms; passing both is refused. Omit all
            three and the query defaults to the last hour, so it is never
            unbounded.
        begin_ms: Absolute window start as epoch milliseconds (not seconds).
            May be given without end_ms, which then means "from this instant
            onwards". Cannot be combined with last.
        end_ms: Absolute window end as epoch milliseconds (not seconds). May be
            given without begin_ms, which then means "everything up to this
            instant". Cannot be combined with last.
        limit: Maximum events returned, 1..20000, default 50. Out-of-range
            values are silently clamped into that range rather than refused.
            Narrow the window or the text rather than raising this — raw events
            are the largest thing this skill can put in context.
        target: Log Insight target name as spelled in
            ~/.vmware-log-insight/config.yaml. Omit to use that file's
            default_target — with no default configured, omitting it is an error
            that lists the configured names.
    """
    from vmware_log_insight.mcp_server import server

    try:
        from vmware_log_insight.ops.search import search_events

        return search_events(
            server._get_connection(target),
            text=text, last=last, begin_ms=begin_ms, end_ms=end_ms, limit=limit,
        )
    except Exception as e:
        return {"error": server._safe_error(e, "log_search"), "hint": "Run 'vmware-log-insight doctor'."}


@mcp.tool(annotations=_READ)
@vmware_tool(risk_level="low")
def log_aggregate(
    text: Optional[str] = None,
    last: Optional[str] = None,
    begin_ms: Optional[int] = None,
    end_ms: Optional[int] = None,
    aggregation: str = "COUNT",
    bin_width_ms: int = 60000,
    target: Optional[str] = None,
) -> dict:
    """[READ] Aggregate matching events into a time series and detect spikes.

    WHEN: to find when/whether log volume burst without pulling raw events. Follow up with log_search on the spike window.

    RETURNS: {aggregation, bin_width_ms, constraints, bins:[{timestamp_ms,
    value}], spikes:[{timestamp_ms, value, zscore}]}. A bin is flagged as a
    spike when it sits at least 2 standard deviations above the mean; a series
    of fewer than 3 bins, or a flat one, reports no spikes rather than calling
    everything a spike — so an empty 'spikes' list is not evidence of calm when
    the window is short. Read-only.

    Args:
        text: Free-text substring matched with CONTAINS, exactly as in
            log_search. Omit to aggregate every event in the window.
        last: Relative window ending now — "30m", "2h", "7d" (units s/m/h/d) or
            a bare number of seconds. Cannot be combined with begin_ms/end_ms.
            Omit all three and the window defaults to the last hour.
        begin_ms: Absolute window start as epoch milliseconds. Usable on its
            own; cannot be combined with last.
        end_ms: Absolute window end as epoch milliseconds. Usable on its own;
            cannot be combined with last.
        aggregation: The function applied within each bin — exactly one of
            COUNT, UCOUNT, AVG, MIN, MAX, SUM, STDDEV, VARIANCE, SAMPLE
            (lower case is accepted and upper-cased). Anything else raises a
            ValueError listing the nine. Default COUNT, which answers "how many
            events per bin" and is what spike detection is normally run on.
        bin_width_ms: Width of each time bin in milliseconds, must be positive
            (default 60000 = one minute). It sets the resolution of both the
            series and the spike test: bins much wider than the burst average
            it away, bins much narrower make every quiet minute look like noise.
        target: Log Insight target name as spelled in
            ~/.vmware-log-insight/config.yaml. Omit to use that file's
            default_target — with no default configured, omitting it is an error
            that lists the configured names.
    """
    from vmware_log_insight.mcp_server import server

    try:
        from vmware_log_insight.ops.aggregate import aggregate_events

        return aggregate_events(
            server._get_connection(target),
            text=text, last=last, begin_ms=begin_ms, end_ms=end_ms,
            aggregation=aggregation, bin_width_ms=bin_width_ms,
        )
    except Exception as e:
        return {"error": server._safe_error(e, "log_aggregate"), "hint": "Run 'vmware-log-insight doctor'."}


@mcp.tool(annotations=_READ)
@vmware_tool(risk_level="low")
def log_fields(name_filter: Optional[str] = None, target: Optional[str] = None) -> dict:
    """[READ] List the extracted fields available to use in query filters.

    Use this to discover valid field names before filtering log_search /
    log_aggregate. Returns the family list envelope {items, returned, limit,
    total, truncated, hint}; each item is {name}. No limit — every matching
    field is returned, so truncated is always false: this is the complete field
    list, not a page. Read-only.

    Args:
        name_filter: Case-insensitive substring matched against the field name.
            Omit to return every field this appliance extracts. Field extraction
            is deployment-specific, so a name absent here does not exist for
            this target no matter what it is called elsewhere.
        target: Log Insight target name as spelled in
            ~/.vmware-log-insight/config.yaml. Omit to use that file's
            default_target — with no default configured, omitting it is an error
            that lists the configured names.
    """
    from vmware_log_insight.mcp_server import server

    try:
        from vmware_log_insight.ops.fields import list_fields

        return list_fields(server._get_connection(target), name_filter=name_filter)
    except Exception as e:
        return {"error": server._safe_error(e, "log_fields"), "hint": "Run 'vmware-log-insight doctor'."}


@mcp.tool(annotations=_READ)
@vmware_tool(risk_level="low")
def log_version(target: Optional[str] = None) -> dict:
    """[READ] Return the Log Insight appliance version/build (diagnostics and
    query-syntax compatibility). Returns {version, release_name, build}. Use
    this first when a query behaves unexpectedly, to confirm the appliance
    version before trusting log_search. Read-only.

    Args:
        target: Log Insight target name as spelled in
            ~/.vmware-log-insight/config.yaml. Omit to use that file's
            default_target — with no default configured, omitting it is an error
            that lists the configured names. This is also the cheapest way to
            prove a given target's credentials work at all.
    """
    from vmware_log_insight.mcp_server import server

    try:
        from vmware_log_insight.ops.fields import get_version

        return get_version(server._get_connection(target))
    except Exception as e:
        return {"error": server._safe_error(e, "log_version"), "hint": "Run 'vmware-log-insight doctor'."}
