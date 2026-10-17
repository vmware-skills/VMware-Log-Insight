"""Regression: list tools state their completeness instead of implying it.

Source: VMware-AIops issue #31 (juanpf-ha). Running the family against a local
Llama 3.3 70B, the operator reported that "with long tool responses, it may
omit existing information or incorrectly state that no data was returned."

A bare ``list[dict]`` gives a model nothing to distinguish a complete answer
from page one, so it guesses — and a guess that reads "no data" looks like a
finding. ``list_log_alerts``, ``get_log_alert_history`` and ``list_log_fields`` now return the
family envelope from ``vmware_policy.paginated``, so ``returned``/``total``/
``truncated`` are stated.

Every total here is real and free: the Log Insight API hands back the whole
collection in one GET and this package applies ``limit`` client-side, so the
full match count is already in hand. That is what lets a page which exactly
fills ``limit`` be reported complete rather than conservatively flagged.
"""

from __future__ import annotations

from vmware_log_insight.ops.alerts import get_alert_history, list_alerts
from vmware_log_insight.ops.fields import list_fields

ENVELOPE_KEYS = {"items", "returned", "limit", "total", "truncated", "hint"}


class FakeClient:
    """Returns a canned payload for any GET."""

    def __init__(self, payload):
        self.payload = payload

    def get(self, path, params=None, **kwargs):
        return self.payload


def _alerts(count: int) -> FakeClient:
    return FakeClient(
        [
            {"id": f"a{i}", "name": f"alert-{i:03d}", "enabled": True, "info": ""}
            for i in range(count)
        ]
    )


def _history(count: int) -> FakeClient:
    return FakeClient([{"timestamp": i, "info": f"fired-{i}"} for i in range(count)])


def _fields(count: int) -> FakeClient:
    return FakeClient([{"displayName": f"field_{i:03d}"} for i in range(count)])


# ---------------------------------------------------------------------------
# Shape — every converted tool carries the whole contract
# ---------------------------------------------------------------------------


def test_alert_list_returns_the_envelope():
    assert ENVELOPE_KEYS <= set(list_alerts(_alerts(3)))


def test_alert_history_returns_the_envelope():
    assert ENVELOPE_KEYS <= set(get_alert_history(_history(3), "a1"))


def test_log_fields_returns_the_envelope():
    assert ENVELOPE_KEYS <= set(list_fields(_fields(3)))


# ---------------------------------------------------------------------------
# Truncation — the question the model can no longer get wrong
# ---------------------------------------------------------------------------


def test_full_page_is_flagged_truncated():
    """213 alerts behind a limit of 50: say so rather than imply 50 is all."""
    out = list_alerts(_alerts(213), limit=50)
    assert out["returned"] == 50
    assert out["total"] == 213
    assert out["truncated"] is True
    assert "213" in out["hint"]


def test_short_result_is_not_truncated():
    out = list_alerts(_alerts(3), limit=50)
    assert out["returned"] == 3
    assert out["total"] == 3
    assert out["truncated"] is False
    assert out["hint"] is None


def test_exactly_full_page_with_known_total_is_complete():
    """The payoff of a real total: a page filled to the limit is not ambiguous.

    Without ``total`` the envelope would conservatively flag this truncated,
    costing the agent a redundant follow-up query.
    """
    out = list_alerts(_alerts(50), limit=50)
    assert out["returned"] == 50
    assert out["truncated"] is False
    assert out["hint"] is None


def test_alert_history_truncation_counts_all_records_not_the_page():
    out = get_alert_history(_history(120), "a1", limit=50)
    assert out["returned"] == 50
    assert out["total"] == 120
    assert out["truncated"] is True


def test_empty_result_is_complete_not_truncated():
    """Zero rows is a complete answer, not a maybe — the #31 failure mode."""
    out = list_alerts(FakeClient([]))
    assert out["items"] == []
    assert out["total"] == 0
    assert out["truncated"] is False
    assert out["hint"] is None


# ---------------------------------------------------------------------------
# The total must reflect the filter, never the unfiltered collection
# ---------------------------------------------------------------------------


def test_total_counts_matches_not_the_whole_collection():
    client = FakeClient(
        [
            {"id": "a1", "name": "disk full", "enabled": True},
            {"id": "a2", "name": "cpu hot", "enabled": True},
            {"id": "a3", "name": "disk slow", "enabled": True},
        ]
    )
    out = list_alerts(client, name_filter="disk")
    assert out["returned"] == 2
    assert out["total"] == 2  # not 3 — the filter is part of the question
    assert out["truncated"] is False


# ---------------------------------------------------------------------------
# Unlimited tools — "truncated: false" is itself the information
# ---------------------------------------------------------------------------


def test_log_fields_has_no_limit_and_reports_a_real_total():
    out = list_fields(_fields(400))
    assert out["returned"] == 400
    assert out["total"] == 400
    assert out["limit"] is None
    assert out["truncated"] is False
    assert out["hint"] is None
