"""ConfigDrivenPolicy -- configuration-driven policy implementation."""

from __future__ import annotations

import logging
from typing import Any

from soothe_sdk.tools.metadata import (
    extract_filesystem_path_for_policy,
    get_tool_meta,
    is_policy_filesystem_tool,
)

from soothe.core.security.operation_security import WorkspaceToolOperationSecurity
from soothe.protocols.operation_security import (
    OperationKind,
    OperationSecurityContext,
    OperationSecurityRequest,
)
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
        if name in ("execute", "shell", "bash", "run_command"):
            cmd = action.tool_args.get("command") or action.tool_args.get("cmd", "")
            cmd_s = str(cmd) if cmd is not None else ""
            first_word = cmd_s.split()[0] if cmd_s.split() else "*"
            return Permission("shell", "execute", first_word)
        meta = get_tool_meta(name)
        if meta and meta.category == "file_ops":
            scope = extract_filesystem_path_for_policy(name, action.tool_args) or "*"
            action_kind = "write" if meta.outcome_type == "file_write" else "read"
            return Permission("fs", action_kind, scope)
        if meta and meta.category == "execution":
            cmd = action.tool_args.get("command", "") or action.tool_args.get("cmd", "")
            cmd_s = str(cmd) if cmd is not None else ""
            first_word = cmd_s.split()[0] if cmd_s.split() else "*"
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
        self._operation_security = WorkspaceToolOperationSecurity()

    def check(self, action: ActionRequest, context: PolicyContext) -> PolicyDecision:
        """Check if an action is permitted under the active profile."""
        if action.action_type == "tool_call" and action.tool_name:
            request = self._build_operation_security_request(action)
            op_context = OperationSecurityContext(
                thread_id=context.thread_id,
                workspace=context.workspace,
                security_config=getattr(self._config, "security", None),
            )
            op_decision = self._operation_security.evaluate(request, op_context)
            if op_decision.verdict != "allow":
                return PolicyDecision(verdict=op_decision.verdict, reason=op_decision.reason)

        required = _extract_required_permission(action)
        if required is None:
            return PolicyDecision(verdict="allow", reason="No permission required")

        permissions: PermissionSet = context.active_permissions

        profile = self._find_profile(permissions)

        if profile and any(
            Permission(d.category, d.action, d.scope).matches(required)
            if isinstance(d, Permission)
            else False
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

    def _build_operation_security_request(self, action: ActionRequest) -> OperationSecurityRequest:
        tool_name = action.tool_name or ""
        tool_args = action.tool_args or {}
        meta = get_tool_meta(tool_name)
        operation_kind: OperationKind = "generic"
        target_path: str | None = None
        command: str | None = None

        if is_policy_filesystem_tool(tool_name):
            target_path = extract_filesystem_path_for_policy(tool_name, tool_args)
            if meta and meta.outcome_type == "file_write":
                operation_kind = "filesystem_write"
            else:
                operation_kind = "filesystem_read"
        elif meta and meta.category == "execution":
            command_value = tool_args.get("command") or tool_args.get("cmd")
            if command_value is not None:
                command = str(command_value)
                operation_kind = "shell_execute"
            elif tool_name == "run_python":
                operation_kind = "python_execute"

        return OperationSecurityRequest(
            action_type=action.action_type,
            tool_name=tool_name,
            tool_args=tool_args,
            operation_kind=operation_kind,
            target_path=target_path,
            command=command,
        )
