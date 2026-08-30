"""A 404 on login must not be diagnosed as a bad object id.

Real-hardware finding, 2026-08-30. Authentication failed with HTTP 404, and the
remedy offered was:

    Check the id — list the parent collection first (e.g.
    `vmware-log-insight alert list`) and copy an exact id.

There is no id in a login. And `alert list` performs the very authentication
that just failed, so following the advice reproduces the error. The user is sent
in a circle, one API call per lap.

The cause is a fall-through: the auth path special-cases 400/401/403 and hands
everything else to `_hint_for_status`, which is written for *resource* calls
where 404 really does mean "wrong id". On `POST /sessions` the same status means
something entirely different — nothing answers at that path — which is a host,
port or appliance-identity problem, and the message has to say so.

This is one of six instances the same round found of a remedy that cannot work:
error messages are only as good as the worst branch that reaches them.
"""

from __future__ import annotations

import httpx
import pytest

from vmware_log_insight import connection as conn


def _client_returning(status: int):
    """An httpx client whose POST /sessions answers with ``status``."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={})

    return httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="https://logs.example:9543/api/v2",
    )


def _connection(monkeypatch, status: int):
    target = type(
        "T", (), {"host": "logs.example", "port": 9543, "provider": "Local"}
    )()
    c = object.__new__(conn.LogInsightClient)
    c._target = target
    c._username = "admin"
    c._password = "secret"
    c._base_url = "https://logs.example:9543/api/v2"
    c._client = _client_returning(status)
    return c


@pytest.mark.unit
def test_a_404_on_login_is_not_blamed_on_an_object_id(monkeypatch):
    c = _connection(monkeypatch, 404)

    with pytest.raises(conn.LogInsightApiError) as exc:
        c._acquire_session()

    message = str(exc.value)
    assert "copy an exact id" not in message, (
        "a login has no id to copy; this is the generic resource-404 hint "
        "reaching a path it was never written for"
    )
    assert "alert list" not in message, (
        "that command performs the authentication that just failed — following "
        "the advice reproduces the error"
    )
    # And it must say something true instead.
    assert "logs.example" in message
    assert "9543" in message


@pytest.mark.unit
@pytest.mark.parametrize("status", [400, 401, 403, 404, 405, 503])
def test_the_remedy_survives_the_mcp_layers_truncation(status, monkeypatch):
    """The reason the message is terse, pinned so it stays terse.

    `_safe_error` renders exceptions through `sanitize(str(exc), 300)`. Twice
    already in this file a message grew past that and lost its own closing
    remedy — the agent received a diagnosis and no next step, which is how a
    long, careful error message becomes worse than a short one. Asserting on
    the truncated text is the only way to test what the agent actually reads.
    """
    from vmware_policy import sanitize

    c = _connection(monkeypatch, status)
    with pytest.raises(conn.LogInsightApiError) as exc:
        c._acquire_session()

    raw = str(exc.value)
    assert len(raw) <= 300, (
        f"the message is {len(raw)} chars; the last {len(raw) - 300} are cut "
        f"before the agent sees them: {raw[300:]!r}"
    )
    # Not merely short — intact. Comparing against the sanitized form is what
    # ties this test to what the agent actually receives rather than to a
    # number that could drift away from `_safe_error`.
    assert sanitize(raw, 300) == raw


@pytest.mark.unit
def test_the_404_message_names_what_is_actually_wrong(monkeypatch):
    c = _connection(monkeypatch, 404)

    with pytest.raises(conn.LogInsightApiError) as exc:
        c._acquire_session()

    lowered = str(exc.value).lower()
    # Host/port/appliance identity — the three things a 404 on the login
    # endpoint can actually mean.
    assert "host" in lowered or "port" in lowered
    assert "/api/v2" in str(exc.value)


@pytest.mark.unit
@pytest.mark.parametrize("status", [400, 401, 403])
def test_credential_failures_keep_their_own_message(status, monkeypatch):
    """The control. These already said the right thing and must not be swept
    into a generic 'wrong host' answer, which would send the user to check
    networking that is fine."""
    c = _connection(monkeypatch, status)

    with pytest.raises(conn.LogInsightApiError) as exc:
        c._acquire_session()

    message = str(exc.value)
    assert "password" in message.lower()
    assert ".env" in message


@pytest.mark.unit
def test_a_resource_404_still_gets_the_id_hint():
    """The other control: the generic hint is correct where it was written to
    be used, and removing it would cost a real diagnosis on real calls."""
    assert "copy an exact id" in conn._hint_for_status(404)


@pytest.mark.unit
def test_a_405_on_login_is_treated_like_a_404(monkeypatch):
    """Same diagnosis, and reachable: a proxy that forwards the path but not
    the method answers 405, and the id hint is no better there."""
    c = _connection(monkeypatch, 405)

    with pytest.raises(conn.LogInsightApiError) as exc:
        c._acquire_session()

    message = str(exc.value)
    assert "copy an exact id" not in message
    # Asserting only the absence let 405 fall through to the generic "Check the
    # request and try again", which also lacks that phrase — the test passed for
    # the wrong reason (形态 #4). It has to assert the diagnosis is present.
    assert "9543" in message and "/api/v2" in message
