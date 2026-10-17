"""Field + appliance metadata: GET /api/v2/fields and GET /api/v2/version."""

from __future__ import annotations

from typing import TYPE_CHECKING

from vmware_policy import paginated, sanitize

from vmware_log_insight.ops._shape import expect_list, expect_object

if TYPE_CHECKING:
    from vmware_log_insight.connection import LogInsightClient


def _summarize_field(f: dict) -> dict:
    """Project one ``/fields`` entry onto {name, internal_name, type[, namespace]}.

    ``displayName`` is what a person types and what the UI shows; it is the
    ``name``. ``internalName`` is what the appliance stores — for content-pack
    fields an encoded string (``vmw_esxi_audit`` is stored as ``ibadcoc7...``).
    ``displayNamespace`` only appears on content-pack fields, where two packs
    may define the same display name.
    """
    out = {
        "name": sanitize(str(f.get("displayName", "")), 200),
        "internal_name": sanitize(str(f.get("internalName", "")), 200),
        "type": sanitize(str(f.get("fieldType", "")), 50),
    }
    if f.get("displayNamespace"):
        out["namespace"] = sanitize(str(f["displayNamespace"]), 200)
    return out


def list_fields(client: LogInsightClient, name_filter: str | None = None) -> dict:
    """List the fields this appliance knows (static and extracted).

    Args:
        client: Authenticated Log Insight client.
        name_filter: Optional case-insensitive substring filter on the field's
            display name.

    Returns:
        The family list envelope; `items` is a list of {name, internal_name,
        type} dicts (plus `namespace` for content-pack fields). `name` is what
        aggregate_logs' `field` takes. There is no limit: every matching field is
        returned, so `total` is real and `truncated` is always False.
    """
    items = expect_list(client.get("/fields"), "GET /fields")
    filt = name_filter.lower() if name_filter else None
    out: list[dict] = []
    for f in items:
        if not isinstance(f, dict):
            continue
        summary = _summarize_field(f)
        if not summary["name"]:
            continue
        if filt and filt not in summary["name"].lower():
            continue
        out.append(summary)
    return paginated(out, total=len(out))


def get_version(client: LogInsightClient) -> dict:
    """Return the Log Insight appliance version/build info.

    Useful for diagnostics and for confirming query-syntax compatibility.
    """
    data = expect_object(client.get("/version"), "GET /version")
    version = str(data.get("version", ""))
    build = data.get("build", data.get("buildNumber"))
    if build is None and "-" in version:
        # 8.18.7 sends no build key; the build is the suffix: "8.18.7-25423541".
        build = version.rsplit("-", 1)[1]
    return {
        "version": sanitize(version, 100),
        "release_name": sanitize(str(data.get("releaseName", "")), 100),
        "build": sanitize(str(build or ""), 100),
    }
