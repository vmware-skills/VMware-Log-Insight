"""Check the top-level shape of an API response before reading it.

Verified against Aria Operations for Logs 8.18.7 (2026-10-17): ``GET /fields``,
``GET /alerts`` and ``GET /alerts/{id}/history`` answer with a bare JSON array;
``/events`` and ``/aggregated-events`` answer with an object. Up to 2.4.0 the ops
code assumed wrapped objects for the arrays and every call died as
``AttributeError: operation failed.`` — the one error that tells nobody anything.
A shape we did not expect now says which call returned what.
"""

from __future__ import annotations

from typing import Any

from vmware_log_insight.connection import LogInsightApiError


def _unexpected(call: str, expected: str, data: Any) -> LogInsightApiError:
    return LogInsightApiError(
        f"Unexpected response from {call}: expected {expected}, got "
        f"{type(data).__name__}. This skill was verified on Log Insight 8.18.7; "
        "run get_log_insight_version and report the version with this message."
    )


def expect_list(data: Any, call: str) -> list:
    """Return ``data`` if it is a JSON array, else raise a teaching error."""
    if isinstance(data, list):
        return data
    raise _unexpected(call, "a JSON array", data)


def expect_object(data: Any, call: str) -> dict:
    """Return ``data`` if it is a JSON object, else raise a teaching error."""
    if isinstance(data, dict):
        return data
    raise _unexpected(call, "a JSON object", data)
