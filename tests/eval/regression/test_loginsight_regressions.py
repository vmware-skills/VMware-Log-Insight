"""Regression evals for vmware-log-insight. Failures block release.

Covers 踩坑 #34 (every advertised tool is actually exposed over MCP + schemas
build, #33), the read-only invariant, and the presence of the .env obfuscation
helpers (the whole reason this skill ships the b64 pattern from day one).
"""
from __future__ import annotations

import asyncio

from vmware_log_insight.mcp_server.server import mcp
from vmware_log_insight import config

_EXPECTED_TOOLS = {
    "search_logs", "aggregate_logs", "list_log_fields", "get_log_insight_version",
    "list_log_alerts", "get_log_alert", "get_log_alert_history",
}


def test_mcp_exposes_exactly_the_expected_tools():
    """踩坑 #34: CLI/advertised tool count must equal the MCP-exposed set, and
    #33: FastMCP must build every schema without raising."""
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert names == _EXPECTED_TOOLS


def test_all_tools_are_read_only():
    """This skill is non-destructive by construction — no tool may be a write."""
    for t in asyncio.run(mcp.list_tools()):
        ann = t.annotations
        # annotations may be a pydantic model or None; coerce to dict.
        data = ann.model_dump() if hasattr(ann, "model_dump") else (ann or {})
        assert data.get("readOnlyHint") is True, f"{t.name} is not marked read-only"
        assert data.get("destructiveHint") is False, f"{t.name} marked destructive"


def test_config_has_env_obfuscation_helpers():
    """The .env b64 obfuscation must be built in (per the family decision)."""
    assert hasattr(config, "_autoencode_env_file")
    assert hasattr(config, "_decode_secret")
    assert hasattr(config, "_is_b64_token")


def test_a_returned_error_is_audited_as_a_failure(monkeypatch):
    """A tool that catches and returns must still be recorded as having failed.

    ``@vmware_tool`` marks a call failed when an exception reaches it, or when
    the payload it returns is the family's error envelope — a dict carrying a
    truthy ``error``. All seven tools in this skill catch and return exactly
    that envelope, so no explicit ``report_tool_failure`` call is needed here.

    That is a property of this surface, not a guarantee, which is why it is
    pinned: a tool rewritten to hand back an error *string* would look identical
    to a success, and the audit row would say ``ok`` for an operation that
    failed, with the circuit breaker told the same thing.
    """
    import vmware_log_insight.mcp_server.server as server
    from vmware_log_insight.connection import LogInsightApiError

    assert getattr(server.list_log_fields, "_is_vmware_tool", False), (
        "list_log_fields is not wrapped by @vmware_tool — this test would pass "
        "without exercising the audit path it exists to check"
    )

    rows: list[dict] = []

    class _Recorder:
        def log(self, **kw):
            rows.append(kw)

    monkeypatch.setattr("vmware_policy.guard.get_engine", lambda: _Recorder())

    def boom(target=None):
        raise LogInsightApiError("Log Insight returned HTTP 404.", status_code=404)

    monkeypatch.setattr(server, "_get_connection", boom)
    result = server.list_log_fields()

    assert result.get("error"), "the tool did not return the error envelope"
    assert rows, "the wrapper recorded no audit row at all"
    assert rows[0]["status"] == "error", (
        f"a failed call was audited as {rows[0]['status']!r} — the audit log "
        "and the circuit breaker both read this field"
    )
