"""Shared MCP plumbing for the vmware-log-insight tool modules.

Tool functions live in ``vmware_log_insight/mcp_server/tools/*.py`` and register onto the
single
``mcp`` instance defined here. This module imports nothing from the tool
packages (tools import *from* ``_shared``, never the reverse) to avoid a circular
import. ``vmware_log_insight/mcp_server/server.py`` re-exports these so the historical
import paths
keep resolving.
"""

import logging
import os
import ssl
from pathlib import Path
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP
from vmware_policy import sanitize

from vmware_log_insight.config import ConfigError, load_config
from vmware_log_insight.connection import ConnectionManager, LogInsightApiError
from vmware_log_insight import __version__

logger = logging.getLogger("mcp_server")


def _safe_error(exc: Exception, tool: str) -> str:
    """Return an agent-safe error string; log full detail server-side only.

    LogInsightApiError (the connection layer's teaching errors) and intentional
    validation errors pass through; anything else is masked so raw response
    bodies / host:port pairs never reach the agent.

    ``ConfigError`` is on the list because ``config.get_password`` raises it to
    report a missing ``VMWARE_LOG_INSIGHT_<TARGET>_PASSWORD``, naming the
    variable to set. Every tool reaches that path through ``_get_connection``,
    so leaving it off turned the most common first-run failure in this skill
    into ``operation failed.`` — the one message where the remedy *is* the text.

    It is deliberately narrower than the ``OSError`` it subclasses. Allowing the
    base class through admitted every other OS-level failure with it, and
    ``sanitize()`` strips control characters and truncates — it redacts nothing.
    ``socket.gaierror`` quotes the name that failed to resolve; this package
    authored none of that text. The FileNotFoundError / PermissionError /
    ConnectionError entries stay: they are narrower still and record the
    specific subclasses this package raises on purpose.

    Swapping the entry is necessary but not sufficient, which is why the
    ``ssl.SSLError`` reduction sits *ahead* of the allowlist rather than in it:
    ``ssl.SSLCertVerificationError`` inherits from ``ValueError`` as well as
    ``OSError``, and ``ValueError`` predates all of this. An allowlist cannot
    express "not this one", so the exclusion has to be checked first. Only
    ``ssl.SSLError`` — ``socket.gaierror`` and ``ConnectionRefusedError`` have
    ``OSError`` as their only base and are already reduced, so naming them here
    would make this guard sound broader than it is.

    Measured reach, so nobody has to guess: on this skill's own transport it
    never fires. httpx maps a certificate failure to ``httpx.ConnectError``,
    which is not an ``ssl.SSLError`` and not on the allowlist either, and
    ``connection.py`` translates it into an authored ``LogInsightApiError``
    before it gets here. The guard covers a raw TLS error arriving by some other
    route; the leak that actually happened was ``connection.py`` interpolating
    that exception's text into a message the allowlist passes through.

    ``RuntimeError`` is deliberately absent. It is Python's generic catch-all,
    so allowing it through would pass any library's raw text as if this package
    had authored it.
    """
    logger.error("Tool %s failed", tool, exc_info=True)
    if isinstance(exc, ssl.SSLError):
        return f"{type(exc).__name__}: operation failed."
    if isinstance(
        exc,
        (
            LogInsightApiError,
            ValueError,
            KeyError,
            ConfigError,
            FileNotFoundError,
            PermissionError,
            ConnectionError,
        ),
    ):
        return sanitize(str(exc), 300)
    return f"{type(exc).__name__}: operation failed."


mcp = FastMCP(
    "vmware-log-insight",
    instructions=(
        "VMware Aria Operations for Logs (vRealize Log Insight): read-only log "
        "search, aggregation/spike detection, field discovery, and alert queries. "
        "Feed results to vmware-debug's incident_timeline to correlate with events "
        "from other sources. For vCenter events/alarms use vmware-monitor; for "
        "metrics/anomalies use vmware-aria."
    ),
)

# FastMCP takes no version argument and leaves the lowlevel server's at
# None, which makes `initialize` answer with the MCP SDK's version rather
# than ours. Set it so a client can tell which release it is talking to.
mcp._mcp_server.version = __version__

_conn_mgr: Optional[ConnectionManager] = None


def _get_connection(target: Optional[str] = None) -> Any:
    """Return a LogInsightClient, lazily initialising the connection manager."""
    global _conn_mgr  # noqa: PLW0603
    if _conn_mgr is None:
        config_path_str = os.environ.get("VMWARE_LOG_INSIGHT_CONFIG")
        config_path = Path(config_path_str) if config_path_str else None
        _conn_mgr = ConnectionManager(load_config(config_path))
    return _conn_mgr.connect(target)
