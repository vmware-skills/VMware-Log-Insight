"""CLI for VMware Log Insight (Aria Operations for Logs) — read-only.

Commands mirror the MCP tools: search/aggregate events, list fields, query
alerts, plus doctor and the stdio MCP server entry point. The ``mcp`` subcommand
starts the server via the installed entry point and does not touch the network
(proxy-safe — 踩坑 #25).
"""

from __future__ import annotations

import functools
import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from vmware_log_insight import __version__
import sys
from vmware_policy import audited, cli_local


def _harden_console_encoding() -> None:
    """Never let one unrepresentable glyph kill a command.

    On a console whose encoding cannot carry the characters we print -- cp936 on
    the Chinese Windows boxes this family is tested on, or any ASCII locale --
    ``print`` raises ``UnicodeEncodeError`` and the whole command dies with a
    traceback. ``--help`` died that way in four repos. A mangled dash is a
    cosmetic loss; a dead ``--help`` is an outage, so the error handler is
    relaxed rather than the vocabulary narrowed.

    Best effort: ``reconfigure`` is absent when stdout has been replaced by a
    plain object (pytest capture, some MCP hosts), and losing the hardening
    there is not worth an exception at import.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError, OSError):
            pass


_harden_console_encoding()

app = typer.Typer(
    name="vmware-log-insight",
    help="VMware Aria Operations for Logs (vRealize Log Insight) — read-only log search.",
    no_args_is_help=True,
)
console = Console()

alert_app = typer.Typer(help="Alert queries: list, get, history.")
app.add_typer(alert_app, name="alert")

TargetOption = Annotated[str | None, typer.Option("--target", "-t", help="Target name from config")]
ConfigOption = Annotated[Path | None, typer.Option("--config", "-c", help="Config file path")]


def _friendly_errors(fn):
    """Print expected operational errors as one red line instead of a traceback."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        from vmware_log_insight.connection import LogInsightApiError

        try:
            return fn(*args, **kwargs)
        except (LogInsightApiError, FileNotFoundError, KeyError, OSError, ValueError) as exc:
            console.print(f"[red]Error: {exc}[/red]")
            raise typer.Exit(1) from exc
        finally:
            _close_open_connections()

    return wrapper


_OPEN_MANAGERS: list = []


def _close_open_connections() -> None:
    while _OPEN_MANAGERS:
        mgr = _OPEN_MANAGERS.pop()
        try:
            mgr.disconnect_all()
        except Exception:
            pass


def _get_connection(target: str | None, config_path: Path | None = None):
    from vmware_log_insight.config import load_config
    from vmware_log_insight.connection import ConnectionManager

    cfg = load_config(config_path)
    mgr = ConnectionManager(cfg)
    _OPEN_MANAGERS.append(mgr)
    return mgr.connect(target or cfg.default_target), cfg


def _json(data: object) -> None:
    console.print_json(json.dumps(data, indent=2, default=str))


@app.command()
@cli_local("prints the installed version")
def version() -> None:
    """Print the installed vmware-log-insight version."""
    console.print(f"vmware-log-insight {__version__}")


@app.command()
@_friendly_errors
@audited("doctor")
def doctor(
    skip_auth: Annotated[bool, typer.Option("--skip-auth", help="Skip authentication check")] = False,
    config: ConfigOption = None,
) -> None:
    """Run pre-flight diagnostics for Log Insight connectivity."""
    from vmware_log_insight.doctor import run_doctor

    raise typer.Exit(0 if run_doctor(config_path=config, skip_auth=skip_auth) else 1)


@app.command()
@_friendly_errors
@audited("log_search")
def search(
    text: Annotated[str | None, typer.Option("--text", "-q", help="Free-text search (CONTAINS)")] = None,
    last: Annotated[str, typer.Option("--last", "-l", help="Relative window: 1h, 30m, 7d")] = "1h",
    limit: Annotated[int, typer.Option("--limit", "-n", help="Max events (default 50)")] = 50,
    as_json: Annotated[bool, typer.Option("--json", help="Raw JSON output")] = False,
    target: TargetOption = None,
    config: ConfigOption = None,
) -> None:
    """Search log events within a time window."""
    from vmware_log_insight.ops.search import search_events

    client, _ = _get_connection(target, config)
    result = search_events(client, text=text, last=last, limit=limit)
    if as_json:
        _json(result)
        return
    table = Table(title=f"Events ({result['count']}{'+' if not result['complete'] else ''})")
    table.add_column("Timestamp (ms)")
    table.add_column("Text", style="bold", overflow="fold")
    for e in result["events"]:
        table.add_row(str(e["timestamp_ms"]), e["text"][:160])
    console.print(table)


@app.command()
@_friendly_errors
@audited("log_aggregate")
def aggregate(
    text: Annotated[str | None, typer.Option("--text", "-q", help="Free-text search")] = None,
    last: Annotated[str, typer.Option("--last", "-l", help="Relative window: 1h, 30m, 7d")] = "1h",
    aggregation: Annotated[str, typer.Option("--agg", help="COUNT|UCOUNT|AVG|MIN|MAX|SUM|...")] = "COUNT",
    bin_width_ms: Annotated[int, typer.Option("--bin-ms", help="Bin width in ms")] = 60000,
    target: TargetOption = None,
    config: ConfigOption = None,
) -> None:
    """Aggregate events into a time series and detect spikes."""
    from vmware_log_insight.ops.aggregate import aggregate_events

    client, _ = _get_connection(target, config)
    result = aggregate_events(
        client, text=text, last=last, aggregation=aggregation, bin_width_ms=bin_width_ms
    )
    _json(result)


@app.command()
@_friendly_errors
@audited("log_fields")
def fields(
    name: Annotated[str | None, typer.Option("--name", help="Filter by name substring")] = None,
    target: TargetOption = None,
    config: ConfigOption = None,
) -> None:
    """List extracted fields usable in query filters."""
    from vmware_log_insight.ops.fields import list_fields

    client, _ = _get_connection(target, config)
    items = list_fields(client, name_filter=name)["items"]
    table = Table(title=f"Fields ({len(items)})")
    table.add_column("Name", style="bold")
    for f in items:
        table.add_row(f["name"])
    console.print(table)


@alert_app.command("list")
@_friendly_errors
@audited("alert_list")
def alert_list_cmd(
    name: Annotated[str | None, typer.Option("--name", help="Filter by name substring")] = None,
    limit: Annotated[int, typer.Option("--limit", "-n")] = 50,
    target: TargetOption = None,
    config: ConfigOption = None,
) -> None:
    """List defined alerts."""
    from vmware_log_insight.ops.alerts import list_alerts

    client, _ = _get_connection(target, config)
    result = list_alerts(client, name_filter=name, limit=limit)
    items = result["items"]
    # The envelope knows the real total, so say when rows were left behind
    # rather than showing a count that reads like the whole set.
    shown = f"{len(items)} of {result['total']}" if result["truncated"] else str(len(items))
    table = Table(title=f"Alerts ({shown})")
    table.add_column("ID")
    table.add_column("Name", style="bold")
    table.add_column("Enabled")
    for a in items:
        table.add_row(a["id"][:36], a["name"][:60], str(a["enabled"]))
    console.print(table)


@alert_app.command("get")
@_friendly_errors
@audited("alert_get")
def alert_get_cmd(alert_id: str, target: TargetOption = None, config: ConfigOption = None) -> None:
    """Get full details for one alert by id."""
    from vmware_log_insight.ops.alerts import get_alert

    client, _ = _get_connection(target, config)
    _json(get_alert(client, alert_id))


@alert_app.command("history")
@_friendly_errors
@audited("alert_history")
def alert_history_cmd(
    alert_id: str,
    limit: Annotated[int, typer.Option("--limit", "-n")] = 50,
    target: TargetOption = None,
    config: ConfigOption = None,
) -> None:
    """List recent trigger-history records for an alert."""
    from vmware_log_insight.ops.alerts import get_alert_history

    client, _ = _get_connection(target, config)
    _json(get_alert_history(client, alert_id, limit=limit))


@app.command("mcp")
@cli_local("starts the MCP server; its tools audit themselves")
def mcp_cmd() -> None:
    """Start the MCP server (stdio transport). Proxy-safe — no network access."""
    import sys

    # Floor is 3.10, matching `requires-python` and the other eleven skills.
    # This guard used to demand 3.11 on the grounds that FastMCP schema
    # reflection was unreliable on 3.10 (踩坑 #33). That was the symptom; the
    # cause was PEP 604 `X | None` in the server's own signatures, fixed by
    # converting them to `Optional[X]`. 3.10 was then verified end to end on
    # 2026-07-19 — every tool's schema built, zero failures, pydantic 2.13.4.
    if sys.version_info < (3, 10):
        typer.echo(
            "ERROR: vmware-log-insight MCP server requires Python >= 3.10.\n"
            "Fix: uv tool install --python 3.12 --force vmware-log-insight",
            err=True,
        )
        raise typer.Exit(2)
    from vmware_log_insight.mcp_server.server import main as _mcp_main

    _mcp_main()


if __name__ == "__main__":
    app()
