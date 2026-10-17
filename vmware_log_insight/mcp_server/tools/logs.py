"""LOG tools (4, read-only): search_logs, aggregate_logs, list_log_fields, get_log_insight_version.

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
def search_logs(
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
    aggregate_logs instead; for vCenter alarms use vmware-monitor.

    RETURNS: {count, complete (False if truncated), constraints,
    events: [{timestamp_ms, text, fields}]}, plus 'note' when limit was lowered.
    'fields' is a flat {name: value} dict — hostname, appname, procid, source,
    facility and any extracted fields the appliance attached. Feed events to
    vmware-debug build_incident_timeline to correlate across sources. Read-only.

    Args:
        text: Word(s) matched against the event message with the CONTAINS
            operator. Log Insight matches whole tokens, not substrings:
            "localhost" finds "localhost.localdomain", "localdom" finds nothing
            (verified on 8.18.7). Not a regex and not a query expression. Omit to
            match every event in the window. This tool has no field-filter
            parameter; filter on a field's value by reading 'fields' in the result.
        last: Relative window ending now, as a quantity plus a unit suffix —
            s, m, h or d ("30m", "2h", "7d") — or a bare number of seconds.
            Anything else raises a ValueError naming the accepted forms. Cannot
            be combined with begin_ms/end_ms; passing both is refused. Omit all
            three and the query defaults to the last hour, so it is never
            unbounded. Windows longer than ~24.8 days are sent as an absolute
            start time, because the appliance's LAST operator overflows there.
        begin_ms: Absolute window start as epoch milliseconds (not seconds —
            a value that looks like seconds is refused). May be given without
            end_ms, which then means "from this instant onwards". Must be before
            end_ms. Cannot be combined with last.
        end_ms: Absolute window end as epoch milliseconds (not seconds). May be
            given without begin_ms, which then means "everything up to this
            instant". Cannot be combined with last.
        limit: Maximum events returned, 1..200, default 50. A larger value is
            lowered to 200 and the result's 'note' says so. Each event is ~650
            characters, so 50 is already ~8k tokens: narrow the window or the
            text rather than raising this.
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
        return server._error_result(e, "search_logs")


@mcp.tool(annotations=_READ)
@vmware_tool(risk_level="low")
def aggregate_logs(
    text: Optional[str] = None,
    last: Optional[str] = None,
    begin_ms: Optional[int] = None,
    end_ms: Optional[int] = None,
    aggregation: str = "COUNT",
    field: Optional[str] = None,
    bin_width_ms: int = 60000,
    target: Optional[str] = None,
) -> dict:
    """[READ] Aggregate matching events into a time series and detect spikes.

    WHEN: to find when/whether log volume burst without pulling raw events. Follow up with search_logs on the spike window.

    RETURNS: {aggregation, field, bin_width_ms, constraints, bins:[{timestamp_ms,
    end_ms, value}] oldest first, spikes:[{timestamp_ms, end_ms, value,
    zscore}]}, plus 'note' when an empty series has a likely cause. For SAMPLE
    each bin's value is one example event {timestamp_ms, text, fields}, and no
    spikes are computed. The appliance omits bins with no events, so a quiet
    minute is a missing bin, not a zero. A bin is flagged as a
    spike when it sits at least 2 standard deviations above the mean; a series
    of fewer than 3 bins, or a flat one, reports no spikes rather than calling
    everything a spike — so an empty 'spikes' list is not evidence of calm when
    the window is short. Read-only.

    Args:
        text: Word(s) matched with CONTAINS (whole tokens, not substrings),
            exactly as in search_logs. Omit to aggregate every event in the window.
        last: Relative window ending now — "30m", "2h", "7d" (units s/m/h/d) or
            a bare number of seconds. Cannot be combined with begin_ms/end_ms.
            Omit all three and the window defaults to the last hour.
        begin_ms: Absolute window start as epoch milliseconds (seconds are
            refused). Usable on its own; must be before end_ms; cannot be
            combined with last.
        end_ms: Absolute window end as epoch milliseconds. Usable on its own;
            cannot be combined with last.
        aggregation: The function applied within each bin — exactly one of
            COUNT, UCOUNT, AVG, MIN, MAX, SUM, STDDEV, VARIANCE, SAMPLE
            (lower case is accepted and upper-cased). Anything else raises a
            ValueError listing the nine. Default COUNT, which answers "how many
            events per bin" and is what spike detection is normally run on.
            COUNT and SAMPLE take no field; the other seven require one.
        field: The field the function applies to, as listed by list_log_fields
            ('name') — e.g. aggregation="UCOUNT", field="hostname" counts distinct
            hosts per bin. Required for UCOUNT/AVG/MIN/MAX/SUM/STDDEV/VARIANCE,
            refused for COUNT/SAMPLE. AVG/MIN/MAX/SUM/STDDEV/VARIANCE need a
            NUMBER field (list_log_fields 'type'). An unknown name returns an
            empty series with a 'note', not an error. For a content-pack field
            (one with a 'namespace'), whether the appliance takes 'name' or
            'internal_name' is unverified — try 'internal_name' if 'name'
            returns nothing.
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
            aggregation=aggregation, field=field, bin_width_ms=bin_width_ms,
        )
    except Exception as e:
        return server._error_result(e, "aggregate_logs")


@mcp.tool(annotations=_READ)
@vmware_tool(risk_level="low")
def list_log_fields(name_filter: Optional[str] = None, target: Optional[str] = None) -> dict:
    """[READ] List the fields this appliance knows (static and extracted).

    Use this to pick a 'field' for aggregate_logs, or to learn what a key in a
    search_logs event's 'fields' means. Returns the family list envelope {items,
    returned, limit, total, truncated, hint}; each item is {name, internal_name,
    type} plus 'namespace' for content-pack fields. 'name' is what aggregate_logs
    takes; 'type' (STRING, NUMBER, ...) says which functions apply. No limit —
    every matching field is returned. An 8.18.7 appliance with the default
    content packs has ~340 fields (~15k tokens unfiltered), so pass name_filter.
    Read-only.

    Args:
        name_filter: Case-insensitive substring matched against the field's
            display name ('name').
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
        return server._error_result(e, "list_log_fields")


@mcp.tool(annotations=_READ)
@vmware_tool(risk_level="low")
def get_log_insight_version(target: Optional[str] = None) -> dict:
    """[READ] Return the Log Insight appliance version/build (diagnostics and
    query-syntax compatibility). Returns {version, release_name, build}. Use
    this first when a query behaves unexpectedly, to confirm the appliance
    version before trusting search_logs. Read-only.

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
        return server._error_result(e, "get_log_insight_version")
