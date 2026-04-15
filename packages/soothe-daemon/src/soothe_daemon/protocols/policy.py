"""PolicyProtocol -- permission-based access control (RFC-0002 Module 4)."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field


@dataclass(frozen=True)
class Permission:
    """A structured permission with category, action, and scope.

    Examples:
        Permission("fs", "read", "*")           -- read any file
        Permission("fs", "write", "/tmp/**")     -- write only under /tmp
        Permission("shell", "execute", "ls")     -- execute only ls
        Permission("shell", "execute", "!rm")    -- anything EXCEPT rm
        Permission("net", "outbound", "*.example.com")  -- only example.com
        Permission("mcp", "connect", "my-server")       -- specific MCP server
        Permission("subagent", "spawn", "planner")       -- specific subagent

    Args:
        category: Permission category (fs, shell, net, mcp, subagent).
        action: Action type (read, write, execute, connect, spawn).
        scope: Scope qualifier (* for all, glob for paths, name or !name for commands).
    """

    category: str
    action: str
    scope: str = "*"

    def matches(self, requested: Permission) -> bool:
        """Check if this granted permission covers a requested permission.

        Args:
            requested: The permission being requested.

        Returns:
            True if this grant covers the request.
        """
        if self.category != requested.category or self.action != requested.action:
            return False
        if self.scope == "*":
            return True
        if self.scope.startswith("!"):
            return not fnmatch.fnmatch(requested.scope, self.scope[1:])
        return fnmatch.fnmatch(requested.scope, self.scope)


class PermissionSet:
    """Immutable collection of permissions with scope-aware matching.

    Args:
        permissions: The set of granted permissions.
    """

    def __init__(self, permissions: frozenset[Permission] | None = None) -> None:
        """Initialize with a set of granted permissions."""
        self._permissions: frozenset[Permission] = permissions or frozenset()

    @property
    def permissions(self) -> frozenset[Permission]:
        """The underlying permission set."""
        return self._permissions

    def contains(self, requested: Permission) -> bool:
        """Check if a requested permission is covered by any grant.

        Args:
            requested: The permission being checked.

        Returns:
            True if any granted permission covers the request.
        """
        return any(p.matches(requested) for p in self._permissions)

    def narrow(self, allowed: frozenset[Permission]) -> PermissionSet:
        """Return a subset for child delegation.

        Args:
            allowed: The permissions allowed for the child.

        Returns:
            A narrowed PermissionSet (intersection semantics).
        """
        narrowed = self._permissions & allowed
        return PermissionSet(narrowed)

    def __contains__(self, item: Permission) -> bool:
        """Check membership via contains()."""
        return self.contains(item)

    def __repr__(self) -> str:
        """Return string representation."""
        return f"PermissionSet({self._permissions!r})"


class ActionRequest(BaseModel):
    """Describes an action requiring permission.

    Args:
        action_type: Kind of action (tool_call, subagent_spawn, mcp_connect).
        tool_name: Name of the tool being invoked (if applicable).
        tool_args: Arguments to the tool (for scope extraction).
    """

    action_type: str
    tool_name: str | None = None
    tool_args: dict[str, Any] = Field(default_factory=dict)


class PolicyContext(BaseModel):
    """Context for policy evaluation.

    Args:
        active_permissions: The currently granted permissions.
        thread_id: The current thread (for audit).
    """

    model_config = {"arbitrary_types_allowed": True}

    active_permissions: Any  # PermissionSet (Any to avoid Pydantic issues with non-BaseModel)
    thread_id: str | None = None


class PolicyDecision(BaseModel):
    """Result of a policy check.

    Args:
        verdict: The decision (allow, deny, need_approval).
        reason: Human-readable explanation.
        matched_permission: The grant that matched (if allowed).
    """

    model_config = {"arbitrary_types_allowed": True}

    verdict: Literal["allow", "deny", "need_approval"]
    reason: str
    matched_permission: Any = None  # Permission | None


class PolicyProfile(BaseModel):
    """A named policy configuration.

    Args:
        name: Profile name (e.g., "readonly", "standard", "privileged").
        permissions: Granted permissions.
        approvable: Permissions that can be approved interactively.
        deny_rules: Explicit deny rules that override grants.
    """

    model_config = {"arbitrary_types_allowed": True}

    name: str
    permissions: Any  # PermissionSet
    approvable: Any = None  # PermissionSet | None
    deny_rules: list[Any] = Field(default_factory=list)  # list[Permission]


@runtime_checkable
class PolicyProtocol(Protocol):
    """Protocol for permission checking and enforcement."""

    def check(self, action: ActionRequest, context: PolicyContext) -> PolicyDecision:
        """Check if an action is permitted.

        Args:
            action: The action being requested.
            context: The current policy context.

        Returns:
            A decision with verdict and reason.
        """
        ...

    def narrow_for_child(self, parent_permissions: PermissionSet, child_name: str) -> PermissionSet:
        """Compute a narrowed permission set for a child subagent.

        Args:
            parent_permissions: The parent's permissions.
            child_name: The child subagent's name.

        Returns:
            A narrowed PermissionSet for the child.
        """
        ...
