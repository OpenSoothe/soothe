"""ConfigDrivenPolicy -- configuration-driven policy implementation."""

from __future__ import annotations

import logging

from soothe.protocols.policy import (
    ActionRequest,
    Permission,
    PermissionSet,
    PolicyContext,
    PolicyDecision,
    PolicyProfile,
)

logger = logging.getLogger(__name__)

STANDARD_PROFILE = PolicyProfile(
    name="standard",
    permissions=PermissionSet(
        frozenset(
            [
                Permission("fs", "read", "*"),
                Permission("fs", "write", "*"),
                Permission("shell", "execute", "*"),
                Permission("net", "outbound", "*"),
                Permission("mcp", "connect", "*"),
                Permission("subagent", "spawn", "*"),
            ]
        )
    ),
    approvable=PermissionSet(frozenset()),
    deny_rules=[],
)

READONLY_PROFILE = PolicyProfile(
    name="readonly",
    permissions=PermissionSet(
        frozenset(
            [
                Permission("fs", "read", "*"),
                Permission("net", "outbound", "*"),
                Permission("subagent", "spawn", "*"),
            ]
        )
    ),
    approvable=PermissionSet(
        frozenset(
            [
                Permission("fs", "write", "*"),
                Permission("shell", "execute", "*"),
            ]
        )
    ),
    deny_rules=[],
)

PRIVILEGED_PROFILE = PolicyProfile(
    name="privileged",
    permissions=PermissionSet(
        frozenset(
            [
                Permission("fs", "read", "*"),
                Permission("fs", "write", "*"),
                Permission("shell", "execute", "*"),
                Permission("net", "outbound", "*"),
                Permission("mcp", "connect", "*"),
                Permission("subagent", "spawn", "*"),
            ]
        )
    ),
    approvable=PermissionSet(frozenset()),
    deny_rules=[],
)

DEFAULT_PROFILES: dict[str, PolicyProfile] = {
    "standard": STANDARD_PROFILE,
    "readonly": READONLY_PROFILE,
    "privileged": PRIVILEGED_PROFILE,
}


def _extract_required_permission(action: ActionRequest) -> Permission | None:
    """Extract the permission required for an action request."""
    if action.action_type == "tool_call" and action.tool_name:
        name = action.tool_name
        if name in ("read_file", "ls", "glob", "grep"):
            return Permission("fs", "read", action.tool_args.get("path", "*"))
        if name in ("write_file", "edit_file"):
            return Permission("fs", "write", action.tool_args.get("path", "*"))
        if name == "execute":
            cmd = action.tool_args.get("command", "")
            first_word = cmd.split()[0] if cmd.split() else "*"
            return Permission("shell", "execute", first_word)
        return Permission("fs", "read", "*")
    if action.action_type == "subagent_spawn":
        return Permission("subagent", "spawn", action.tool_name or "*")
    if action.action_type == "mcp_connect":
        return Permission("mcp", "connect", action.tool_name or "*")
    return None


class ConfigDrivenPolicy:
    """PolicyProtocol implementation driven by named policy profiles.

    Evaluation order: (1) deny rules, (2) granted permissions,
    (3) approvable set, (4) default deny.

    Args:
        profiles: Mapping of profile name to PolicyProfile.
        child_restrictions: Per-child permission overrides.
    """

    def __init__(
        self,
        profiles: dict[str, PolicyProfile] | None = None,
        child_restrictions: dict[str, frozenset[Permission]] | None = None,
    ) -> None:
        self._profiles = profiles or dict(DEFAULT_PROFILES)
        self._child_restrictions = child_restrictions or {}

    def check(self, action: ActionRequest, context: PolicyContext) -> PolicyDecision:
        """Check if an action is permitted under the active profile."""
        required = _extract_required_permission(action)
        if required is None:
            return PolicyDecision(verdict="allow", reason="No permission required")

        permissions: PermissionSet = context.active_permissions

        profile = self._find_profile(permissions)

        if profile and any(
            Permission(d.category, d.action, d.scope).matches(required) if isinstance(d, Permission) else False
            for d in profile.deny_rules
        ):
            return PolicyDecision(
                verdict="deny",
                reason=f"Explicitly denied: {required}",
            )

        if permissions.contains(required):
            return PolicyDecision(
                verdict="allow",
                reason="Permitted by grant",
                matched_permission=required,
            )

        if profile and profile.approvable and profile.approvable.contains(required):
            return PolicyDecision(
                verdict="need_approval",
                reason=f"Requires approval: {required}",
            )

        return PolicyDecision(
            verdict="deny",
            reason=f"No matching permission for {required}",
        )

    def narrow_for_child(self, parent_permissions: PermissionSet, child_name: str) -> PermissionSet:
        """Compute narrowed permissions for a child subagent."""
        restrictions = self._child_restrictions.get(child_name)
        if restrictions:
            return parent_permissions.narrow(restrictions)
        return parent_permissions

    def get_profile(self, name: str) -> PolicyProfile | None:
        """Get a policy profile by name."""
        return self._profiles.get(name)

    def _find_profile(self, permissions: PermissionSet) -> PolicyProfile | None:
        for profile in self._profiles.values():
            if profile.permissions is permissions:
                return profile
        return None
