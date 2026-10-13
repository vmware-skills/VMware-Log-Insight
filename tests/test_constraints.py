"""Unit tests for the query-constraint builder (pure, no live appliance)."""

from __future__ import annotations

import pytest

from vmware_log_insight.constraints import build_constraints, parse_duration_ms


# ── parse_duration_ms ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value,expected_ms",
    [(60, 60000), ("60", 60000), ("30m", 1800000), ("2h", 7200000), ("1d", 86400000)],
)
def test_parse_duration_ms_valid(value, expected_ms):
    assert parse_duration_ms(value) == expected_ms


@pytest.mark.parametrize("bad", ["", "abc", "1x", 0, -5, "-3h", True])
def test_parse_duration_ms_rejects_bad(bad):
    with pytest.raises(ValueError):
        parse_duration_ms(bad)


# ── build_constraints ──────────────────────────────────────────────────


def test_defaults_to_last_hour_when_no_window():
    assert build_constraints() == "timestamp/LAST%203600000"


def test_text_becomes_contains_segment():
    c = build_constraints(text="error", last="1h")
    assert c == "timestamp/LAST%203600000/text/CONTAINS%20error"


def test_absolute_window():
    c = build_constraints(begin_ms=1000, end_ms=2000)
    assert c == "timestamp/%3E%201000/timestamp/%3C%202000"


def test_last_and_absolute_are_mutually_exclusive():
    with pytest.raises(ValueError):
        build_constraints(last="1h", begin_ms=1000)


def test_filters_and_value_escaping():
    c = build_constraints(last="1h", filters=[("hostname", "=", "esxi 01/x")])
    # value's space and slash are percent-encoded so they don't break the grammar
    assert "hostname/%3D%20esxi%2001%2Fx" in c


def test_unknown_operator_rejected():
    with pytest.raises(ValueError):
        build_constraints(filters=[("f", "LIKE", "v")])
