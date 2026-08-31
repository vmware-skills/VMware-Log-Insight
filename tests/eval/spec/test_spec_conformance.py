"""Spec conformance (CLAUDE.md 踩坑 #36): every HTTP endpoint the code calls
must exist in the official API index — no endpoints written from memory.

AST-scans connection.py + ops/*.py for HTTP calls (``.get/.post/.put/.delete``
on a client, and ``_request(METHOD, path)``), reconstructs each path template
(f-string interpolations -> ``{}``), prepends the client base path ``/api/v2``,
and asserts (method, path) is in OFFICIAL_OPERATIONS. A hallucinated endpoint
fails CI.
"""

from __future__ import annotations

import ast
import importlib.util
import re
from pathlib import Path

_HERE = Path(__file__).resolve()
REPO_ROOT = _HERE.parents[3]
_PKG = REPO_ROOT / "vmware_log_insight"
_BASE = "/api/v2"  # httpx.Client base_url path; code uses paths relative to it
_HTTP_METHODS = {"get", "post", "put", "delete"}


def _load_api_index():
    spec = importlib.util.spec_from_file_location("api_index", _HERE.parent / "api_index.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.OFFICIAL_OPERATIONS


def _norm(path: str) -> str:
    """Collapse any ``{param}`` to ``{}`` so templates compare structurally."""
    return re.sub(r"\{[^}]*\}", "{}", path)


def _allowed() -> set[tuple[str, str]]:
    # OFFICIAL_OPERATIONS holds full paths; code calls are relative to /api/v2.
    out = set()
    for method, path in _load_api_index():
        rel = path[len(_BASE):] if path.startswith(_BASE) else path
        out.add((method, _norm(rel)))
    return out


def _path_from_node(node: ast.AST) -> str | None:
    """Reconstruct a string/f-string path; return None for dynamic paths."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for v in node.values:
            parts.append(str(v.value) if isinstance(v, ast.Constant) else "{}")
        return "".join(parts)
    return None


def _calls_in(source: str) -> list[tuple[str, str]]:
    """Return (METHOD, path) for every HTTP call with a literal/f-string path."""
    found: list[tuple[str, str]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        attr = node.func.attr
        if attr in _HTTP_METHODS and node.args:
            path = _path_from_node(node.args[0])
            if path and path.startswith("/"):
                found.append((attr.upper(), _norm(path)))
        elif attr in ("request", "_request") and len(node.args) >= 2:
            method = node.args[0]
            path = _path_from_node(node.args[1])
            if isinstance(method, ast.Constant) and path and path.startswith("/"):
                found.append((str(method.value).upper(), _norm(path)))
    return found


def _source_files() -> list[Path]:
    return [_PKG / "connection.py", *sorted((_PKG / "ops").glob("*.py"))]


def test_all_called_endpoints_are_in_official_spec():
    allowed = _allowed()
    violations = []
    for f in _source_files():
        for method, path in _calls_in(f.read_text(encoding="utf-8")):
            if (method, path) not in allowed:
                violations.append(f"{f.name}: {method} {path}")
    assert not violations, (
        "Endpoints not in the official API index (tests/eval/spec/api_index.py):\n"
        + "\n".join(violations)
    )


def test_scan_actually_found_the_core_endpoints():
    """Guard against a no-op scan: the known core calls must be detected."""
    seen = set()
    for f in _source_files():
        seen.update(_calls_in(f.read_text(encoding="utf-8")))
    assert ("POST", "/sessions") in seen
    assert ("GET", "/events/{}") in seen
    assert ("GET", "/aggregated-events/{}") in seen
    assert ("GET", "/alerts/{}/history") in seen
