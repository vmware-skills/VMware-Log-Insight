"""Regression: the response shapes a real Aria Operations for Logs 8.18.7 returns.

Every payload here comes from ``tests/fixtures/li_8_18_7.json``, captured
read-only from a live 8.18.7 appliance on 2026-10-17. Up to 2.4.0 the unit tests
mocked wrapped objects (``{"fields": [...]}``, ``{"alerts": [...]}``, bins with a
``timestamp`` key) that the appliance never sends, so three of seven tools failed
on every call against real hardware while the suite was green (AIops#45).

Do not replace a fixture payload with a hand-written one: recapture instead.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from vmware_log_insight.connection import LogInsightApiError
from vmware_log_insight.constraints import build_constraints
from vmware_log_insight.ops.aggregate import aggregate_events
from vmware_log_insight.ops.alerts import get_alert, get_alert_history, list_alerts
from vmware_log_insight.ops.fields import get_version, list_fields
from vmware_log_insight.ops.search import search_events

FIXTURE = json.loads(
    (Path(__file__).parents[2] / "fixtures" / "li_8_18_7.json").read_text(encoding="utf-8")
)


class RealShapeClient:
    """Answers every GET with one captured 8.18.7 payload (or raises ``error``)."""

    def __init__(self, payload, error: LogInsightApiError | None = None):
        self.payload = payload
        self.error = error
        self.paths: list[str] = []
        self.params: list[dict | None] = []

    def get(self, path, params=None, **kwargs):
        self.paths.append(path)
        self.params.append(params)
        if self.error is not None:
            raise self.error
        return copy.deepcopy(self.payload)


# --- fields: a bare JSON array of {displayName, internalName, fieldType, ...} ---


class PathClient:
    """Answers each path with its captured payload; an unrouted path is a 404."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.paths: list[str] = []

    def get(self, path, params=None, **kwargs):
        self.paths.append(path)
        if path not in self.routes:
            raise LogInsightApiError(f"HTTP 404 for GET {path}", status_code=404, path=path)
        return copy.deepcopy(self.routes[path])


def _fields_client(packs=True) -> PathClient:
    routes = {"/fields": FIXTURE["fields"]}
    if packs:
        routes["/content/contentpack"] = FIXTURE["content_packs"]
    return PathClient(routes)


def test_fields_bare_array_is_listed_by_display_name():
    out = list_fields(_fields_client())
    names = [f["name"] for f in out["items"]]
    assert out["total"] == len(FIXTURE["fields"]) == len(names)
    assert "hostname" in names and "appname" in names
    # displayName is what a person types; internalName is what the API stores.
    source = next(f for f in out["items"] if f["name"] == "source")
    assert source["internal_name"] == "__li_source_path"
    assert source["type"] == "STRING"


def test_fields_name_filter_on_bare_array():
    out = list_fields(_fields_client(), name_filter="HOST")
    assert [f["name"] for f in out["items"]] == ["hostname"]


def test_content_pack_fields_get_the_name_a_query_accepts():
    # Verified live: only "<pack namespace>:<displayName>" aggregates; the bare
    # display name and the encoded internalName match nothing.
    out = list_fields(_fields_client(), name_filter="vmw_config_type")
    (f,) = out["items"]
    assert f["name"] == "com.vmware.vsphere:vmw_config_type"
    assert f["display_name"] == "vmw_config_type"
    assert f["content_pack"] == "VMware - vSphere"
    assert f["internal_name"].startswith("ibadcoc7")
    assert "note" not in out


def test_unreadable_pack_list_is_said_not_hidden():
    out = list_fields(_fields_client(packs=False), name_filter="vmw_config_type")
    (f,) = out["items"]
    assert f["name"] == "vmw_config_type"
    assert "pack namespace" in out["note"]


def test_no_pack_lookup_when_no_field_needs_one():
    static = [f for f in FIXTURE["fields"] if not f.get("displayNamespace")]
    client = PathClient({"/fields": static})
    list_fields(client)
    assert client.paths == ["/fields"]


def test_fields_unexpected_shape_is_a_teaching_error_not_attributeerror():
    with pytest.raises(LogInsightApiError, match="GET /fields"):
        list_fields(RealShapeClient("not a list"))


# --- alerts: GET /alerts and /alerts/{id}/history are bare arrays ---


def test_alerts_bare_array():
    out = list_alerts(RealShapeClient(FIXTURE["alerts"]))
    assert out["total"] == len(FIXTURE["alerts"])
    first = out["items"][0]
    assert first["id"] == FIXTURE["alerts"][0]["id"]
    assert first["enabled"] is False
    assert first["name"].startswith("vRops")


def test_alert_history_empty_bare_array():
    assert FIXTURE["alert_history"] == []
    out = get_alert_history(RealShapeClient(FIXTURE["alert_history"]), FIXTURE["alert"]["id"])
    assert out["items"] == [] and out["total"] == 0


def test_get_alert_real_object():
    out = get_alert(RealShapeClient(FIXTURE["alert"]), FIXTURE["alert"]["id"])
    assert out["id"] == FIXTURE["alert"]["id"]
    assert "query" in out["raw_keys"]


@pytest.mark.parametrize("bad", ["../version", "..", "a/b", "x y", "id?x=1"])
def test_alert_id_cannot_leave_the_alerts_path(bad):
    client = RealShapeClient(FIXTURE["alert"])
    with pytest.raises(ValueError, match="list_log_alerts"):
        get_alert(client, bad)
    with pytest.raises(ValueError, match="list_log_alerts"):
        get_alert_history(client, bad)
    assert client.paths == []


def test_unknown_alert_id_500_is_not_hinted_as_retry():
    # 8.18.7 answers HTTP 500 for a non-UUID id it does not know (404 for an
    # unknown UUID); the generic 5xx hint says "retry", which never helps.
    err = LogInsightApiError(
        "Log Insight returned HTTP 500. Server-side error — retry shortly.",
        status_code=500, method="GET", path="/alerts/x",
    )
    for call in (get_alert, get_alert_history):
        with pytest.raises(LogInsightApiError) as exc:
            call(RealShapeClient(None, error=err), "00000000-0000-4000-8000-000000000000")
        assert "list_log_alerts" in str(exc.value)
        assert "retry" not in str(exc.value).lower()


# --- aggregation: bins carry minTimestamp/maxTimestamp, not timestamp ---


def test_aggregate_bins_have_timestamps():
    out = aggregate_events(RealShapeClient(FIXTURE["aggregate_count"]), last="10m")
    assert out["bins"], "fixture has bins"
    assert all(isinstance(b["timestamp_ms"], int) for b in out["bins"])
    assert all(b["end_ms"] > b["timestamp_ms"] for b in out["bins"])
    # oldest first, so a reader sees a timeline
    starts = [b["timestamp_ms"] for b in out["bins"]]
    assert starts == sorted(starts)
    assert sum(b["value"] for b in out["bins"]) == sum(
        b["value"] for b in FIXTURE["aggregate_count"]["bins"]
    )


def test_aggregate_spikes_carry_a_timestamp():
    payload = copy.deepcopy(FIXTURE["aggregate_count"])
    payload["bins"][3]["value"] = 100000
    out = aggregate_events(RealShapeClient(payload), last="10m")
    assert len(out["spikes"]) == 1
    assert out["spikes"][0]["timestamp_ms"] == payload["bins"][3]["minTimestamp"]


def test_aggregate_sample_value_is_a_sanitized_event():
    payload = copy.deepcopy(FIXTURE["aggregate_sample"])
    payload["bins"][0]["value"]["text"] = "evil\x1b[31m\x00text"
    out = aggregate_events(RealShapeClient(payload), last="10m", aggregation="SAMPLE")
    sample = out["bins"][0]["value"]
    assert isinstance(sample, dict)
    assert "\x1b" not in sample["text"] and "\x00" not in sample["text"]
    assert out["spikes"] == []


@pytest.mark.parametrize("fn", ["UCOUNT", "AVG", "MIN", "MAX", "SUM", "STDDEV", "VARIANCE"])
def test_field_functions_require_a_field(fn):
    client = RealShapeClient(FIXTURE["aggregate_ucount_hostname"])
    with pytest.raises(ValueError, match="field"):
        aggregate_events(client, last="10m", aggregation=fn)
    assert client.paths == []
    aggregate_events(client, last="10m", aggregation=fn, field="hostname")
    assert client.params[-1]["aggregation-field"] == "hostname"


@pytest.mark.parametrize("fn", ["COUNT", "SAMPLE"])
def test_count_and_sample_refuse_a_field(fn):
    # 8.18.7 answers HTTP 400 for COUNT or SAMPLE with aggregation-field.
    client = RealShapeClient(FIXTURE["aggregate_count"])
    with pytest.raises(ValueError, match="field"):
        aggregate_events(client, last="10m", aggregation=fn, field="hostname")
    assert client.paths == []


def test_unknown_field_empty_series_says_why():
    out = aggregate_events(
        RealShapeClient(FIXTURE["aggregate_avg_unknown_field"]),
        last="10m", aggregation="AVG", field="no_such_field",
    )
    assert out["bins"] == []
    assert "list_log_fields" in out["note"]


# --- search: hostname/appname/procid are positional slices of text ---


def test_search_positional_fields_are_sliced_from_text():
    out = search_events(RealShapeClient(FIXTURE["events"]), last="10m")
    fields = out["events"][0]["fields"]
    assert fields["hostname"] == "localhost.localdomain"
    assert fields["appname"] == "envoy"
    assert fields["procid"] == "1049382"
    assert fields["facility"] == "local4"


def test_search_limit_cap_is_stated_not_silent():
    client = RealShapeClient(FIXTURE["events"])
    out = search_events(client, last="10m", limit=20000)
    assert client.params[-1]["limit"] < 20000
    assert "limit" in out.get("note", "")


# --- time windows ---


def test_long_last_window_does_not_overflow_int32():
    # LAST takes an int32 of ms on 8.18.7: past ~24.85 days it answers HTTP 400.
    c = build_constraints(last="30d", now_ms=1_800_000_000_000)
    assert "LAST" not in c
    assert c == "timestamp/%3E%20" + str(1_800_000_000_000 - 30 * 86400 * 1000)


def test_short_last_window_still_uses_last():
    assert build_constraints(last="24d").startswith("timestamp/LAST%20")


def test_begin_after_end_is_refused():
    with pytest.raises(ValueError, match="begin_ms"):
        build_constraints(begin_ms=2_000_000_000_000, end_ms=1_000_000_000_000)


@pytest.mark.parametrize("kw", [{"begin_ms": 1_790_000_000}, {"end_ms": 1_790_000_000}])
def test_seconds_instead_of_ms_is_refused(kw):
    with pytest.raises(ValueError, match="milliseconds"):
        build_constraints(**kw)


def test_version_real_shape():
    out = get_version(RealShapeClient(FIXTURE["version"]))
    assert out["version"] == "8.18.7-25423541"
    assert out["release_name"] == "GA"


# --- doctor reads the query API, not just login + /version ---


class RoutedClient:
    """Answers each path with its captured payload (``/fields`` overridable)."""

    def __init__(self, fields_payload):
        self.fields_payload = fields_payload

    def get(self, path, params=None, **kwargs):
        if path == "/version":
            return copy.deepcopy(FIXTURE["version"])
        if path == "/fields":
            return copy.deepcopy(self.fields_payload)
        if path == "/content/contentpack":
            return copy.deepcopy(FIXTURE["content_packs"])
        raise AssertionError(f"doctor called an unexpected path: {path}")


def _doctor_with(fields_payload, tmp_path, monkeypatch, capsys):
    import socket

    from vmware_log_insight import config as cfg
    from vmware_log_insight import doctor as doc
    from vmware_log_insight.connection import ConnectionManager

    conf = tmp_path / "config.yaml"
    conf.write_text(
        "targets:\n  lab:\n    host: li.example\n    username: admin\n"
        "default_target: lab\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cfg, "ENV_FILE", tmp_path / "no-such.env")
    monkeypatch.setenv("VMWARE_LOG_INSIGHT_LAB_PASSWORD", "x")
    monkeypatch.setenv("COLUMNS", "300")

    class _Sock:
        def close(self):
            pass

    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: _Sock())
    monkeypatch.setattr(ConnectionManager, "connect", lambda self, name=None: RoutedClient(fields_payload))
    monkeypatch.setattr(ConnectionManager, "disconnect", lambda self, name: None)
    ok = doc.run_doctor(config_path=conf)
    return ok, capsys.readouterr().out


def test_doctor_passes_on_the_real_fields_shape(tmp_path, monkeypatch, capsys):
    ok, out = _doctor_with(FIXTURE["fields"], tmp_path, monkeypatch, capsys)
    assert ok, out
    assert "Query API" in out and f"{len(FIXTURE['fields'])} fields" in out


def test_doctor_fails_when_the_query_api_shape_is_wrong(tmp_path, monkeypatch, capsys):
    # The 2.4.0 failure: login and /version fine, every query tool broken.
    ok, out = _doctor_with({"fields": FIXTURE["fields"]}, tmp_path, monkeypatch, capsys)
    assert not ok
    assert "Query API" in out and "FAIL" in out


# --- error payloads: the hint says where each kind of failure goes ---


def test_error_hint_routes_each_kind_of_failure():
    # Up to 2.4.0 every error, including a bad argument, said only
    # "Run 'vmware-log-insight doctor'." — which fixes none of the input cases.
    from vmware_log_insight.mcp_server import server

    out = server._error_result(ValueError("UCOUNT needs a field"), "aggregate_logs")
    assert out["error"] == "UCOUNT needs a field"
    hint = out["hint"]
    assert "list_log_fields" in hint and "list_log_alerts" in hint
    assert "doctor" in hint and "server log" in hint
    assert hint != "Run 'vmware-log-insight doctor'."


def test_unexpected_errors_stay_masked():
    from vmware_log_insight.mcp_server import server

    out = server._error_result(AttributeError("'list' object has no attribute 'get'"), "list_log_fields")
    assert out["error"] == "AttributeError: operation failed."


# --- server log: a refused argument is one line, a failure keeps its traceback ---


def test_input_error_logs_one_line_without_traceback(caplog):
    import logging

    from vmware_log_insight.mcp_server import server

    with caplog.at_level(logging.DEBUG, logger="mcp_server"):
        server._error_result(ValueError("UCOUNT needs a field"), "aggregate_logs")
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1 and warnings[0].exc_info is None
    assert "UCOUNT needs a field" in warnings[0].getMessage()
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_real_failure_keeps_its_traceback(caplog):
    import logging

    from vmware_log_insight.mcp_server import server

    with caplog.at_level(logging.DEBUG, logger="mcp_server"):
        server._error_result(AttributeError("boom"), "list_log_fields")
        server._error_result(
            LogInsightApiError("could not connect", status_code=None), "search_logs"
        )
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 2
    # the real exception, not an empty sys.exc_info() tuple
    assert all(r.exc_info and r.exc_info[1] is not None for r in errors)


# --- a partial word reads as "no such logs": say why when nothing matched ---

EMPTY_EVENTS = {"complete": True, "duration": 6, "numResults": 0, "events": []}


def test_zero_hits_on_a_partial_token_says_text_matches_whole_words():
    # Live 8.18.7: "agt-w2" -> 0 with complete=true, "agt-w2*" -> 50+.
    out = search_events(RealShapeClient(EMPTY_EVENTS), text="agt-w2", last="10m")
    assert out["count"] == 0
    assert "whole words" in out["note"] and "'agt-w2*'" in out["note"]


def test_zero_hits_with_a_wildcard_or_no_text_adds_no_token_note():
    for kw in ({"text": "agt-w2*"}, {}):
        out = search_events(RealShapeClient(EMPTY_EVENTS), last="10m", **kw)
        assert "whole words" not in out.get("note", "")


def test_hits_add_no_token_note():
    out = search_events(RealShapeClient(FIXTURE["events"]), text="envoy", last="10m")
    assert out["count"] and "note" not in out


def test_empty_series_on_a_partial_token_says_so_too():
    empty = {"complete": True, "duration": 3, "numResults": 0, "bins": []}
    out = aggregate_events(RealShapeClient(empty), text="agt-w2", last="10m")
    assert "'agt-w2*'" in out["note"]


def test_whole_word_note_wins_over_the_limit_note():
    out = search_events(RealShapeClient(EMPTY_EVENTS), text="agt-w2", last="10m", limit=5000)
    assert "whole words" in out["note"]
