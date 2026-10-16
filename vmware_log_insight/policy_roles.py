"""What vmware-policy needs to apply roles to this skill (HLD §18 D-21/D-22).

Policy cannot see which tools escape a role or how a missing target resolves; this
module declares them. Imported by the MCP server (roles apply only to a network
MCP server). With a vmware-policy that has no roles module (< 1.24) nothing is
declared.
"""

from __future__ import annotations

from vmware_policy import mtime_cached_loader, skill_name

from vmware_log_insight.config import CONFIG_FILE, load_config

_cached_config = mtime_cached_loader("VMWARE_LOG_INSIGHT_CONFIG", CONFIG_FILE, load_config)


#: Tools that give their holder more than a role. Host-path tools are added by
#: policy while a file root is set.
ESCAPES = frozenset()


def _target_name(target: str | None) -> str:
    """The target the connection layer would use for ``target`` (or the default)."""
    config = _cached_config()
    return config.get_target_strict(target or config.default_target or "").name


try:
    from vmware_policy.roles import declare_role_metadata
except ImportError:  # vmware-policy without roles: nothing to declare
    declare_role_metadata = None

if declare_role_metadata is not None:
    declare_role_metadata(
        skill_name(__name__),
        escapes=ESCAPES,
        resolver=_target_name,
    )
