"""Issue #3: every search returned HTTP 400 on a real appliance while doctor passed.

The constraint builder wrote ``timestamp/LAST/360000`` — operator and value as
two path segments. Log Insight expects them as ONE segment separated by a
space: the reporter's working curl was ``.../timestamp/LAST%20360000``.

These tests pin the bytes that actually leave the client (via MockTransport),
not just the string the builder returns, so a later change to how httpx
normalises the path cannot quietly reintroduce the bug.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import httpx

from vmware_log_insight.connection import LogInsightClient
from vmware_log_insight.constraints import build_constraints
from vmware_log_insight.ops.search import search_events


def _capturing_client(seen: list[str]) -> LogInsightClient:
    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.url.raw_path.decode("ascii"))
        return httpx.Response(200, json={"events": [], "complete": True})

    c = LogInsightClient.__new__(LogInsightClient)
    c._target = SimpleNamespace(username="u", provider="Local", host="li.test")
    c._base_url = "https://li.test:9543/api/v2"
    c._password = "pw"
    c._username = "u"
    c._session_id = "sess"
    c._session_expires_at = time.time() + 9999
    c._liveness_checked_at = time.time()
    c._client = httpx.Client(base_url=c._base_url, transport=httpx.MockTransport(handler))
    return c


def test_issue_3_time_window_is_one_segment_on_the_wire():
    seen: list[str] = []
    search_events(_capturing_client(seen), text="Test", last=360)
    assert len(seen) == 1
    path = seen[0].split("?")[0]
    assert path == "/api/v2/events/timestamp/LAST%20360000/text/CONTAINS%20Test"
    # the exact shape that 400'd in the issue must never be sent again
    assert "LAST/" not in path and "CONTAINS/" not in path


def test_absolute_window_and_filters_keep_field_value_pairs():
    seen: list[str] = []
    search_events(
        _capturing_client(seen),
        begin_ms=1000,
        end_ms=2000,
        filters=[("hostname", "=", "esx/01"), ("vmw_cluster", "EXISTS", "")],
    )
    path = seen[0].split("?")[0]
    assert path == (
        "/api/v2/events/timestamp/%3E%201000/timestamp/%3C%202000"
        "/hostname/%3D%20esx%2F01/vmw_cluster/EXISTS"
    )


def test_every_constraint_is_exactly_field_plus_one_segment():
    """Structural invariant: segment count is 2 per constraint (EXISTS included),
    whatever characters the values carry."""
    c = build_constraints(
        text="a/b c",
        last="1h",
        filters=[("f", "!=", "x/y/z"), ("g", "EXISTS", ""), ("h", "<", "5")],
    )
    assert len(c.split("/")) == 2 * 5
