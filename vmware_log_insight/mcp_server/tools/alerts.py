"""ALERT tools (3, read-only): alert_list, alert_get, alert_history."""

from typing import Optional

from vmware_policy import vmware_tool

from vmware_log_insight.mcp_server._shared import mcp

_READ = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}


@mcp.tool(annotations=_READ)
@vmware_tool(risk_level="low")
def alert_list(
    name_filter: Optional[str] = None, limit: int = 50, target: Optional[str] = None
) -> dict:
    """[READ] List defined Log Insight alerts.

    Returns the family list envelope {items, returned, limit, total, truncated,
    hint}; each item is {id, name, enabled, info}. Start here, then pass an id to
    alert_get or alert_history. total is the real count matching name_filter, so
    truncated answers whether more exist; raise limit or narrow name_filter when
    true. Read-only — this skill never creates/edits/deletes alerts.

    Args:
        name_filter: Case-insensitive substring matched against the alert's
            name only (not its id or description). Omit to list every defined
            alert. The appliance returns the whole collection either way and the
            filter runs locally, so filtering costs nothing extra.
        limit: Maximum items in the page (default 50). It slices the matches
            after filtering; 'total' still reports every match, so a small limit
            never hides how many alerts exist.
        target: Log Insight target name as spelled in
            ~/.vmware-log-insight/config.yaml. Omit to use that file's
            default_target — with no default configured, omitting it is an error
            that lists the configured names.
    """
    from vmware_log_insight.mcp_server import server

    try:
        from vmware_log_insight.ops.alerts import list_alerts

        return list_alerts(server._get_connection(target), name_filter=name_filter, limit=limit)
    except Exception as e:
        return {"error": server._safe_error(e, "alert_list"), "hint": "Run 'vmware-log-insight doctor'."}


@mcp.tool(annotations=_READ)
@vmware_tool(risk_level="low")
def alert_get(alert_id: str, target: Optional[str] = None) -> dict:
    """[READ] Get the stored definition of one alert. Use this after alert_list.

    Returns the same sanitized {id, name, enabled, info} projection as an
    alert_list row plus 'raw_keys' — the sorted key names the appliance actually
    sent — so you can see what else the definition carries without this skill
    guessing at its shape. For when the alert fired, use alert_history.
    Read-only.

    Args:
        alert_id: The alert id exactly as returned in an alert_list row's 'id'
            field (not the alert's name). An empty string is refused with a
            message telling you to run alert_list; a well-formed but unknown id
            comes back as a 404 from the appliance.
        target: Log Insight target name as spelled in
            ~/.vmware-log-insight/config.yaml. Omit to use that file's
            default_target — with no default configured, omitting it is an error
            that lists the configured names.
    """
    from vmware_log_insight.mcp_server import server

    try:
        from vmware_log_insight.ops.alerts import get_alert

        return get_alert(server._get_connection(target), alert_id)
    except Exception as e:
        return {"error": server._safe_error(e, "alert_get"), "hint": "Run 'vmware-log-insight doctor'."}


@mcp.tool(annotations=_READ)
@vmware_tool(risk_level="low")
def alert_history(alert_id: str, limit: int = 50, target: Optional[str] = None) -> dict:
    """[READ] List recent trigger-history records for an alert.

    Use this for when an alert fired, not how it's defined.
    Returns the family list envelope {items, returned, limit, total, truncated,
    hint}; each item is {timestamp_ms, info}. total is the real history-record
    count, so truncated answers whether older records were left behind — raise
    limit when true. Read-only.

    Args:
        alert_id: The alert id exactly as returned in an alert_list row's 'id'
            field (not the alert's name). An empty string is refused with a
            message telling you to run alert_list first.
        limit: Maximum history records returned, most recent first as the
            appliance orders them (default 50). There is no offset — the
            appliance hands back the whole history in one call and this slices
            it, so when truncated is true the only way to reach older records is
            a larger limit.
        target: Log Insight target name as spelled in
            ~/.vmware-log-insight/config.yaml. Omit to use that file's
            default_target — with no default configured, omitting it is an error
            that lists the configured names.
    """
    from vmware_log_insight.mcp_server import server

    try:
        from vmware_log_insight.ops.alerts import get_alert_history

        return get_alert_history(server._get_connection(target), alert_id, limit=limit)
    except Exception as e:
        return {"error": server._safe_error(e, "alert_history"), "hint": "Run 'vmware-log-insight doctor'."}
