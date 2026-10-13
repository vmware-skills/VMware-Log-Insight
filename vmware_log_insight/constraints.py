"""Build Log Insight query constraints (the path-encoded part of
``GET /api/v2/events/{constraints}`` and ``/aggregated-events/{constraints}``).

Log Insight encodes each filter as ONE ``field/<OPERATOR value>`` pair: the
field is a path segment, and the operator and its value share the next segment,
separated by a space (``%20`` on the wire) — e.g. ``text/CONTAINS%20error``,
``timestamp/LAST%203600000``, ``timestamp/%3E%201700000000000``. ``EXISTS``
takes no value (``field/EXISTS``). Constraints are ``/``-joined.

Time windows use the ``LAST`` operator (milliseconds) or numeric comparisons on
``timestamp`` (epoch ms). These are pure functions so they unit-test without a
live appliance.

History: up to 1.9.0 this module wrote ``field/OPERATOR/value`` (three
segments). Every search then failed with HTTP 400 on a real appliance while
``doctor`` passed — issue vmware-skills/VMware-Log-Insight#3, where the
reporter's working curl used ``timestamp/LAST%20360000``.
"""

from __future__ import annotations

from urllib.parse import quote

# Operators accepted in field constraints (mirrors tests/eval/spec/api_index.py).
VALID_OPERATORS = frozenset({"CONTAINS", "=", "!=", "<", ">", "EXISTS", "LAST"})

# Duration suffix -> seconds, for human windows like "30m", "24h", "7d".
_DURATION_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_duration_ms(value: str | int) -> int:
    """Parse a duration into milliseconds.

    Accepts an int (seconds), a bare numeric string (seconds), or a shorthand
    string with a unit suffix: ``s`` ``m`` ``h`` ``d`` (e.g. "30m", "24h", "7d").
    Raises ValueError on anything else (踩坑 #23: accept human shorthand at the
    boundary, fail loudly otherwise).
    """
    if isinstance(value, bool):
        raise ValueError(
            f"invalid duration: {value!r}. Pass a shorthand window like '30m', "
            "'2h', '7d', or an integer number of seconds — e.g. "
            "log_search(last='1h')."
        )
    if isinstance(value, int):
        if value <= 0:
            raise ValueError(
                f"duration must be positive: {value!r}. Pass a shorthand window "
                "like '30m', '2h', '7d', or a positive integer number of "
                "seconds to log_search / log_aggregate."
            )
        return value * 1000
    text = str(value).strip().lower()
    if not text:
        raise ValueError(
            "empty duration: expected a shorthand window like '30m', '2h', "
            "'7d', or an integer number of seconds. Pass e.g. "
            "log_search(last='1h'), or omit the window entirely to default to "
            "the last hour."
        )
    if text[-1] in _DURATION_UNITS:
        try:
            qty = float(text[:-1])
        except ValueError as exc:
            raise ValueError(
                f"invalid duration: {value!r}. The unit suffix is valid but the "
                "quantity is not a number. Pass a window like '30m', '2h', "
                "'7d' — e.g. log_search(last='1h')."
            ) from exc
        seconds = qty * _DURATION_UNITS[text[-1]]
    else:
        try:
            seconds = float(text)
        except ValueError as exc:
            raise ValueError(
                f"invalid duration: {value!r}. Expected a shorthand window like "
                "'30m', '2h', '7d' (units s/m/h/d), or a bare number of "
                "seconds. Pass e.g. log_search(last='1h')."
            ) from exc
    if seconds <= 0:
        raise ValueError(
            f"duration must be positive: {value!r}. Pass a shorthand window "
            "like '30m', '2h', '7d', or a positive number of seconds to "
            "log_search / log_aggregate."
        )
    return int(seconds * 1000)


def _segment(field: str, operator: str, value: str) -> str:
    """Encode one ``field/<OPERATOR value>`` constraint.

    The operator and value form a single path segment joined by a space; the
    whole segment is percent-encoded (space -> %20, '/' -> %2F, '>' -> %3E) so
    a value can never split into an extra path segment. EXISTS has no value.
    """
    if operator not in VALID_OPERATORS:
        raise ValueError(
            f"unknown operator {operator!r}; valid: {sorted(VALID_OPERATORS)}. "
            "Pick one of those exact strings — filters are encoded as "
            "field/<OPERATOR value> pairs for log_search and log_aggregate."
        )
    if not field:
        raise ValueError(
            "constraint field must not be empty: expected a field name. Run "
            "log_fields to list the fields this appliance actually extracts, "
            "then use one of those names."
        )
    if operator == "EXISTS":
        return f"{quote(field, safe='')}/EXISTS"
    # safe="" so '/', spaces, and special chars are escaped and the
    # "OPERATOR value" pair stays ONE path segment.
    return f"{quote(field, safe='')}/{quote(f'{operator} {value}', safe='')}"


def build_constraints(
    *,
    text: str | None = None,
    last: str | int | None = None,
    begin_ms: int | None = None,
    end_ms: int | None = None,
    filters: list[tuple[str, str, str]] | None = None,
) -> str:
    """Build the constraints path segment for an events/aggregated-events query.

    Args:
        text: Free-text search; becomes ``text/CONTAINS%20<text>``.
        last: Relative time window (e.g. "1h", "30m", int seconds); becomes
            ``timestamp/LAST%20<ms>``. Mutually exclusive with begin_ms/end_ms.
        begin_ms / end_ms: Absolute epoch-ms window; become
            ``timestamp/%3E%20<begin>`` and ``timestamp/%3C%20<end>``.
        filters: Extra ``(field, operator, value)`` constraints.

    Returns:
        The ``/``-joined constraints string. Defaults to the last hour when no
        time window is supplied, so a query is never unbounded.
    """
    segments: list[str] = []

    if last is not None and (begin_ms is not None or end_ms is not None):
        raise ValueError(
            "pass either `last` or begin_ms/end_ms, not both — expected exactly "
            "one time window. Use last='1h' for a relative window, or "
            "begin_ms/end_ms for an absolute epoch-millisecond window, in "
            "log_search / log_aggregate."
        )

    if last is not None:
        segments.append(_segment("timestamp", "LAST", str(parse_duration_ms(last))))
    elif begin_ms is not None or end_ms is not None:
        if begin_ms is not None:
            segments.append(_segment("timestamp", ">", str(int(begin_ms))))
        if end_ms is not None:
            segments.append(_segment("timestamp", "<", str(int(end_ms))))
    else:
        # Never issue an unbounded query — default to the last hour.
        segments.append(_segment("timestamp", "LAST", str(parse_duration_ms("1h"))))

    if text:
        segments.append(_segment("text", "CONTAINS", text))

    for field, operator, value in filters or []:
        segments.append(_segment(field, operator, value))

    return "/".join(segments)
