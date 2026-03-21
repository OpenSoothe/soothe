"""ConfigDrivenPolicy -- configuration-driven policy implementation."""

from __future__ import annotations

import fnmatch
import logging
from pathlib import Path
from typing import Any

from soothe.protocols.policy import (
    ActionRequest,
    Permission,
    PermissionSet,
    PolicyContext,
    PolicyDecision,
    PolicyProfile,
)
from soothe.utils import expand_path

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
    if action.action_type == "skillify_retrieve":
        return Permission("subagent", "spawn", "skillify")
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
        config: SootheConfig instance for security policy checks.
    """

    def __init__(
        self,
        profiles: dict[str, PolicyProfile] | None = None,
        child_restrictions: dict[str, frozenset[Permission]] | None = None,
        config: Any = None,
    ) -> None:
        """Initialize the config-driven policy.

        Args:
            profiles: Mapping of profile name to PolicyProfile.
            child_restrictions: Per-child permission overrides.
            config: SootheConfig instance for security policy checks.
        """
        self._profiles = profiles or dict(DEFAULT_PROFILES)
        self._child_restrictions = child_restrictions or {}
        self._config = config

    def check(self, action: ActionRequest, context: PolicyContext) -> PolicyDecision:
        """Check if an action is permitted under the active profile."""
        # Check filesystem-specific security policy first
        if action.action_type == "tool_call" and action.tool_name and action.tool_name.startswith("fs_"):
            fs_decision = self._check_filesystem_permission(action, context)
            if fs_decision.verdict != "allow":
                return fs_decision

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

    def _check_filesystem_permission(
        self,
        action: ActionRequest,
        context: PolicyContext,  # noqa: ARG002
    ) -> PolicyDecision:
        """Check filesystem access permissions.

        Handles:
        - Path blacklist/whitelist patterns
        - File type restrictions
        - Workspace boundary enforcement
        - User approval requirements
        """
        if not self._config or not hasattr(self._config, "security"):
            return PolicyDecision(verdict="allow", reason="No security config")

        security = self._config.security
        file_path = action.tool_args.get("file_path", "")

        if not file_path:
            return PolicyDecision(verdict="allow", reason="No file path specified")

        resolved_path = expand_path(file_path)

        # 1. Check denied_paths (blacklist) - highest priority
        for pattern in security.denied_paths:
            expanded_pattern = self._expand_path_pattern(pattern)
            if self._path_matches_pattern(resolved_path, expanded_pattern):
                return PolicyDecision(
                    verdict="deny",
                    reason=f"Path '{file_path}' matches denied pattern '{pattern}'",
                )

        # 2. Check allowed_paths (whitelist)
        is_allowed = False
        for pattern in security.allowed_paths:
            expanded_pattern = self._expand_path_pattern(pattern)
            if self._path_matches_pattern(resolved_path, expanded_pattern):
                is_allowed = True
                break

        if not is_allowed:
            return PolicyDecision(
                verdict="deny",
                reason=f"Path '{file_path}' does not match any allowed pattern",
            )

        # 3. Check workspace boundary
        if hasattr(self._config, "workspace_dir") and self._config.workspace_dir:
            workspace = expand_path(self._config.workspace_dir)
            try:
                resolved_path.relative_to(workspace)
            except ValueError:
                # Outside workspace
                if not security.allow_paths_outside_workspace:
                    return PolicyDecision(
                        verdict="deny",
                        reason=f"Path '{file_path}' is outside workspace",
                    )
                if security.require_approval_for_outside_paths:
                    return PolicyDecision(
                        verdict="need_approval",
                        reason=f"Path '{file_path}' is outside workspace and requires approval",
                    )

        # 4. Check file type restrictions
        file_ext = resolved_path.suffix.lower()

        if file_ext in security.denied_file_types:
            return PolicyDecision(
                verdict="deny",
                reason=f"File type '{file_ext}' is explicitly denied",
            )

        if file_ext in security.require_approval_for_file_types:
            return PolicyDecision(
                verdict="need_approval",
                reason=f"Access to '{file_ext}' files requires approval",
            )

        # 5. All checks passed
        return PolicyDecision(verdict="allow", reason="All security checks passed")

    def _expand_path_pattern(self, pattern: str) -> str:
        """Expand ~ and environment variables in path patterns."""
        if pattern.startswith("~"):
            return str(Path(pattern).expanduser())
        return pattern

    def _path_matches_pattern(self, path: Path, pattern: str) -> bool:
        """Check if a path matches a glob pattern.

        Supports:
        - ** recursive wildcard
        - * single-level wildcard
        - Exact path matching
        """
        path_str = str(path)
        return fnmatch.fnmatch(path_str, pattern) or path_str.startswith(pattern.rstrip("*"))
