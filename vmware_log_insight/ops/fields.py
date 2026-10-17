"""Field + appliance metadata: GET /api/v2/fields and GET /api/v2/version."""

from __future__ import annotations

from typing import TYPE_CHECKING

from vmware_policy import paginated, sanitize

from vmware_log_insight.connection import LogInsightApiError
from vmware_log_insight.ops._shape import expect_list, expect_object

if TYPE_CHECKING:
    from vmware_log_insight.connection import LogInsightClient


def _pack_namespaces(client: LogInsightClient) -> dict[str, str] | None:
    """Map each installed content pack's display name to its namespace.

    None when the list cannot be read: the fields are then listed by display
    name only, and the result says that content-pack names are unresolved.
    """
    try:
        data = expect_object(client.get("/content/contentpack"), "GET /content/contentpack")
    except LogInsightApiError:
        return None
    out: dict[str, str] = {}
    for pack in data.get("contentPackMetadataList") or []:
        if isinstance(pack, dict) and pack.get("name") and pack.get("namespace"):
            out[str(pack["name"])] = str(pack["namespace"])
    return out


def _summarize_field(f: dict, packs: dict[str, str] | None) -> dict:
    """Project one ``/fields`` entry onto {name, internal_name, type, ...}.

    ``name`` is what a query takes. For a static field that is its
    ``displayName``. A content-pack field (one with ``displayNamespace``, the
    pack's display name) is only addressable as ``<pack namespace>:<displayName>``
    — verified on 8.18.7: aggregating ``com.vmware.vsphere:vmw_esxi_auth_failed_user``
    counted the event, while ``vmw_esxi_auth_failed_user`` and the encoded
    ``internalName`` matched nothing. Such a field also carries ``display_name``
    and ``content_pack``.
    """
    display = sanitize(str(f.get("displayName", "")), 200)
    out = {
        "name": display,
        "internal_name": sanitize(str(f.get("internalName", "")), 200),
        "type": sanitize(str(f.get("fieldType", "")), 50),
    }
    pack = f.get("displayNamespace")
    if pack:
        out["display_name"] = display
        out["content_pack"] = sanitize(str(pack), 200)
        namespace = (packs or {}).get(str(pack))
        if namespace:
            out["name"] = sanitize(f"{namespace}:{f.get('displayName', '')}", 300)
    return out


def list_fields(client: LogInsightClient, name_filter: str | None = None) -> dict:
    """List the fields this appliance knows (static and extracted).

    Args:
        client: Authenticated Log Insight client.
        name_filter: Optional case-insensitive substring filter on the field's
            name (for a content-pack field, the qualified name, which contains
            the display name).

    Returns:
        The family list envelope; `items` is a list of {name, internal_name,
        type} dicts; content-pack fields add `display_name` and `content_pack`,
        and their `name` is the qualified "<pack namespace>:<display name>".
        `name` is what aggregate_logs' `field` takes. There is no limit: every
        matching field is returned, so `total` is real and `truncated` is always
        False. "note" says so if the content-pack list could not be read.
    """
    items = [f for f in expect_list(client.get("/fields"), "GET /fields") if isinstance(f, dict)]
    packs = _pack_namespaces(client) if any(f.get("displayNamespace") for f in items) else {}
    filt = name_filter.lower() if name_filter else None
    out: list[dict] = []
    for f in items:
        summary = _summarize_field(f, packs)
        if not summary["name"]:
            continue
        if filt and filt not in summary["name"].lower():
            continue
        out.append(summary)
    result = paginated(out, total=len(out))
    if packs is None:
        result["note"] = (
            "The content-pack list could not be read, so content-pack fields are "
            "named by display name only; a query needs '<pack namespace>:<name>'."
        )
    return result


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
