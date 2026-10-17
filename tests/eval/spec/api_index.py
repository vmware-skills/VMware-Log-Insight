"""Official Aria Operations for Logs (vRealize Log Insight) REST API index.

Source of truth for spec-conformance tests (CLAUDE.md 踩坑 #36: API layers must
be validated against the official spec, never written from model memory).

Provenance (fetched 2026-06-23):
  - Broadcom developer portal — vRealize Log Insight API:
    https://developer.broadcom.com/xapis/vrealize-log-insight-api/latest/
  - Community API docs (v1, comprehensive): https://vmw-loginsight.github.io/
  - Broadcom TechDocs 8.18 "The vRealize Log Insight REST API":
    https://techdocs.broadcom.com/.../the-vrealize-log-insight-rest-api.html

Notes:
  - Base URL: https://<host>:9543/api/v2 (public API). Default port 9543, JSON.
  - Auth: POST /api/v2/sessions {username, password, provider} -> {sessionId, ttl}.
    Subsequent calls send  Authorization: Bearer <sessionId>.
  - Query constraint syntax is encoded in the URL path as /field/<OPERATOR value>
    pairs, operator and value sharing one space-separated segment (operators:
    CONTAINS, =, !=, <, >, EXISTS (no value), LAST <ms> for time windows).
  - v2 is the current line; v1 paths remain documented and are kept here so the
    spec test recognises both. Exact v2 response schemas can only be confirmed
    against a live instance's /rest-api reference — tracked in BACKLOG (same
    "needs real-hardware verification" status as VKS /wcp/login).

Each entry: (METHOD, PATH_TEMPLATE). Path params are written as {name}.
"""

from __future__ import annotations

# (method, path) pairs the client is allowed to call. The conformance test
# AST-scans the client for .get/.post/... calls and asserts each resolves to
# one of these, so a hallucinated endpoint fails CI.
OFFICIAL_OPERATIONS: frozenset[tuple[str, str]] = frozenset(
    {
        # --- Authentication / session ---
        ("POST", "/api/v2/sessions"),
        ("GET", "/api/v2/sessions/current"),
        ("POST", "/api/v2/sessions/current"),
        # --- Query: raw events ---
        ("GET", "/api/v2/events/{constraints}"),
        # --- Query: aggregated events (numeric series) ---
        ("GET", "/api/v2/aggregated-events/{constraints}"),
        # --- Metadata / fields ---
        ("GET", "/api/v2/fields"),
        # Installed content packs ({contentPackMetadataList: [{name, namespace}]}).
        # Not in the community v1 docs; verified live on 8.18.7-25423541
        # (2026-10-17) and captured in tests/fixtures/li_8_18_7.json. Needed
        # because a content-pack field is queried as "<namespace>:<displayName>"
        # (verified: UCOUNT on com.vmware.vsphere:vmw_esxi_auth_failed_user
        # returned 1 where the display and internal names returned nothing),
        # while /fields names only the pack's display name.
        ("GET", "/api/v2/content/contentpack"),
        ("GET", "/api/v2/version"),
        # --- Alerts ---
        ("GET", "/api/v2/alerts"),
        ("GET", "/api/v2/alerts/{alertId}"),
        ("GET", "/api/v2/alerts/{alertId}/history"),
        # --- Auth provider discovery (unauthenticated) ---
        ("GET", "/api/v2/auth-providers"),
    }
)

# Aggregation functions accepted by /aggregated-events (official set).
AGGREGATION_FUNCTIONS: frozenset[str] = frozenset(
    {"COUNT", "UCOUNT", "AVG", "MIN", "MAX", "SUM", "STDDEV", "VARIANCE", "SAMPLE"}
)

# Constraint operators usable in the path-encoded query syntax.
CONSTRAINT_OPERATORS: frozenset[str] = frozenset(
    {"CONTAINS", "=", "!=", "<", ">", "EXISTS", "LAST"}
)
