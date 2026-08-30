"""Pre-flight diagnostics for vmware-log-insight."""

from __future__ import annotations

import logging
import socket
import stat
from pathlib import Path

from rich.console import Console
from rich.table import Table

_log = logging.getLogger("vmware-log-insight.doctor")
console = Console()


def run_doctor(config_path: Path | None = None, skip_auth: bool = False) -> bool:
    """Run all pre-flight checks. Returns True if all pass."""
    from vmware_log_insight.config import (
        CONFIG_FILE,
        ENV_FILE,
        load_config,
        resolve_config_path,
    )

    checks: list[tuple[str, bool, str]] = []

    # 1. Config file exists — resolved exactly as the tools resolve it,
    # including $VMWARE_LOG_INSIGHT_CONFIG, which this function used to skip.
    # With the variable set it inspected ~/.vmware-log-insight/config.yaml,
    # found it fine, and reported PASS while every tool call opened a different
    # file (2026-08-30).
    path = resolve_config_path(config_path)
    if path.exists():
        checks.append(("Config file", True, str(path)))
    else:
        checks.append(
            ("Config file", False, f"Not found: {path}. Copy config.example.yaml to {CONFIG_FILE}")
        )

    # 2. .env permissions
    if ENV_FILE.exists():
        try:
            perms = stat.S_IMODE(ENV_FILE.stat().st_mode)
            if perms & (stat.S_IRWXG | stat.S_IRWXO):
                checks.append((".env permissions", False, f"{oct(perms)} too open. Run: chmod 600 {ENV_FILE}"))
            else:
                checks.append((".env permissions", True, f"{oct(perms)} (owner-only)"))
        except OSError as e:
            checks.append((".env permissions", False, str(e)))
    else:
        checks.append((".env permissions", True, "No .env file (using shell env vars)"))

    # 3. Parse config
    config = None
    try:
        config = load_config(path)
        checks.append(("Config parse", True, f"{len(config.targets)} target(s) configured"))
    except Exception as e:
        checks.append(("Config parse", False, str(e)))

    if config is None:
        _print_table(checks)
        return False

    # 4. Password env vars set
    for name, target_cfg in config.targets.items():
        try:
            target_cfg.get_password(name)
            checks.append((f"Password ({name})", True, "Set"))
        except OSError as e:
            checks.append((f"Password ({name})", False, str(e)))

    # 5. Network connectivity (TCP to the API port)
    for name, target_cfg in config.targets.items():
        try:
            socket.create_connection((target_cfg.host, target_cfg.port), timeout=5).close()
            checks.append((f"Network ({name})", True, f"{target_cfg.host}:{target_cfg.port} reachable"))
        except OSError as e:
            checks.append((f"Network ({name})", False, f"Cannot reach {target_cfg.host}:{target_cfg.port} - {e}"))

    # 6 & 7. Authentication + appliance version
    if not skip_auth:
        for name, target_cfg in config.targets.items():
            try:
                from vmware_log_insight.connection import ConnectionManager

                mgr = ConnectionManager(config)
                client = mgr.connect(name)
                checks.append((f"Auth ({name})", True, "Session acquired"))
                try:
                    from vmware_log_insight.ops.fields import get_version

                    ver = get_version(client)
                    checks.append((f"Version ({name})", True, ver.get("version") or "unknown"))
                except Exception as e:
                    checks.append((f"Version ({name})", False, str(e)))
                mgr.disconnect(name)
            except Exception as e:
                checks.append((f"Auth ({name})", False, str(e)))

    # 8. MCP server import
    try:
        import vmware_log_insight.mcp_server.server  # noqa: F401

        checks.append(("MCP server import", True, "vmware_log_insight.mcp_server.server importable"))
    except Exception as e:
        checks.append(("MCP server import", False, str(e)))

    _print_table(checks)
    return all(passed for _, passed, _ in checks)


def _print_table(checks: list[tuple[str, bool, str]]) -> None:
    table = Table(title="vmware-log-insight Doctor", show_header=True)
    table.add_column("Check", style="bold")
    table.add_column("Status")
    table.add_column("Detail")
    for name, passed, detail in checks:
        status = "[green]PASS[/green]" if passed else "[red]FAIL[/red]"
        table.add_row(name, status, detail)
    console.print(table)
