"""MCP server for VMware Log Insight (Aria Operations for Logs) — read-only.

Thin entrypoint: importing the tool modules runs their ``@mcp.tool`` decorators
(registering the 7 read tools on the shared ``mcp`` instance), re-exports the
shared plumbing and every tool function so ``from vmware_log_insight.mcp_server.server
import mcp,
<fn>`` keeps resolving (踩坑 #17), and exposes ``main()``.

Tool categories
---------------
* **Logs** (4, read-only): search_logs, aggregate_logs, list_log_fields, get_log_insight_version
  — ``vmware_log_insight/mcp_server/tools/logs.py``
* **Alerts** (3, read-only): list_log_alerts, get_log_alert, get_log_alert_history
  — ``vmware_log_insight/mcp_server/tools/alerts.py``

Security: stdio transport (local only, no listener); credentials come from
env/.env, never MCP messages; all API text passes through sanitize().
For vCenter events/alarms use vmware-monitor; for metrics use vmware-aria.
"""

import logging
import sys
from typing import Optional

from vmware_policy import describe_tool_parameters, mtime_cached_loader, set_environment_resolver
from vmware_policy import skill_name

from vmware_log_insight.config import CONFIG_FILE, load_config

# Shared plumbing — re-exported so `from vmware_log_insight.mcp_server.server import
# _safe_error,
# mcp, _get_connection` (and monkeypatch targets) keep resolving.
from vmware_log_insight.mcp_server._shared import (  # noqa: F401
    _ERROR_HINT,
    _error_result,
    _get_connection,
    _safe_error,
    logger,
    mcp,
)

# Importing the tool modules runs their @mcp.tool decorators (registration).
from vmware_log_insight.mcp_server.tools import (  # noqa: F401
    alerts,
    logs,
)

# Re-export every tool function so `vmware_log_insight.mcp_server.server.<tool>` resolves (tests
# call e.g. `server.search_logs(...)` and patch `server._get_connection`).
from vmware_log_insight.mcp_server.tools.alerts import (  # noqa: F401
    get_log_alert,
    get_log_alert_history,
    list_log_alerts,
)
from vmware_log_insight.mcp_server.tools.logs import (  # noqa: F401
    aggregate_logs,
    get_log_insight_version,
    list_log_fields,
    search_logs,
)


# ---------------------------------------------------------------------------
# Environment declaration
# ---------------------------------------------------------------------------


_cached_config = mtime_cached_loader("VMWARE_LOG_INSIGHT_CONFIG", CONFIG_FILE, load_config)


def _environment_for(target: Optional[str]) -> str:
    """Report the environment a target declares, for policy scoping.

    Policy rules scope by environment ("irreversible work in production needs a
    second person"), and vmware-policy cannot read this skill's config itself.
    Registering this lookup is what lets those rules fire at all. Reloaded on
    config.yaml mtime change so an edit takes effect without restarting the
    server. The config is cached via :func:`vmware_policy.mtime_cached_loader`,
    so repeated tool calls pay one ``os.stat`` instead of a full YAML parse.

    Every tool this skill ships is read-only, and reads are never gated by the
    declaration rule — so nothing here is gated *today*. It is registered so
    that the first write tool added is scoped correctly on the day it lands,
    rather than shipping unprotected because the wiring was never done.
    """
    try:
        return _cached_config().environment_for(target)
    except Exception:  # noqa: BLE001 — an unreadable config means "undeclared"
        return ""


# Keyed by skill: the registry used to be one process-global slot, and a
# bare `import` of any sibling's server module replaced whichever resolver
# was there -- measured turning a freeze-production-writes rule from DENY
# to ALLOW. Keyed, a resolver only ever answers for its own skill, so
# registering at import time is safe again.
set_environment_resolver(_environment_for, skill=skill_name(__name__))

__all__ = [
    "mcp",
    "main",
    "_environment_for",
    "_safe_error",
    "_error_result",
    "_get_connection",
    "search_logs",
    "aggregate_logs",
    "list_log_fields",
    "get_log_insight_version",
    "list_log_alerts",
    "get_log_alert",
    "get_log_alert_history",
]


def main(
    expose: Optional[str] = None,
    allow_write: Optional[str] = None,
    transport: Optional[str] = None,
    host: Optional[str] = None,
    port: Optional[int] = None,
    cert: Optional[str] = None,
    key: Optional[str] = None,
    public_name: Optional[str] = None,
    token_file: Optional[str] = None,
) -> None:
    """Start the MCP server using stdio transport.

    Guards Python < 3.10, the floor declared in `requires-python`.
    """
    # Floor is 3.10, matching `requires-python` and the other eleven skills.
    # This guard used to demand 3.11 on the grounds that FastMCP schema
    # reflection was unreliable on 3.10 (踩坑 #33). That was the symptom; the
    # cause was PEP 604 `X | None` in the server's own signatures, fixed by
    # converting them to `Optional[X]`. 3.10 was then verified end to end on
    # 2026-07-19 — every tool's schema built, zero failures, pydantic 2.13.4.
    if sys.version_info < (3, 10):
        sys.exit(
            "vmware-log-insight MCP server requires Python >= 3.10. Reinstall: "
            "uv tool install --python 3.12 --force vmware-log-insight"
        )
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    from vmware_policy.serve import run_server
    run_server(
        mcp,
        skill="log_insight",
        expose=expose, allow_write=allow_write, transport=transport, host=host, port=port,
        cert=cert, key=key, public_name=public_name, token_file=token_file,
        pooled=True,
    )


# Role metadata for network callers (HLD §18).
import vmware_log_insight.policy_roles  # noqa: F401

if __name__ == "__main__":
    main()

# The docstrings above are the schema. `describe_tool_parameters` copies each
# `Args:` entry into the JSON schema an agent actually reads, and closes the
# object. Without it every parameter reaches the model as a bare name and a
# type, which is how a wrong guess becomes an unfiltered result or a silent
# zero-row answer instead of an error (real-hardware round, 2026-08-30).
_DESCRIBED_PARAMS = describe_tool_parameters(mcp._tool_manager._tools)
