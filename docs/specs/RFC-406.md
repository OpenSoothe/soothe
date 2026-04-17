# RFC-406: PolicyProtocol Architecture

**RFC**: 406
**Title**: PolicyProtocol: Permission Checking & Scope Matching
**Status**: Draft
**Kind**: Architecture Design
**Created**: 2026-04-17
**Dependencies**: RFC-000, RFC-001
**Related**: RFC-100 (CoreAgent)

---

## Abstract

This RFC defines PolicyProtocol, Soothe's permission checking interface for least-privilege delegation. PolicyProtocol provides action request validation, permission set management, and child permission narrowing for fine-grained security control. Every tool invocation and subagent spawn passes through PolicyProtocol before execution, ensuring controlled access to filesystem, shell commands, network resources, and remote services.

---

## Protocol Interface

```python
class PolicyProtocol(Protocol):
    """Permission checking protocol."""

    def check(
        self,
        action: ActionRequest,
        context: PolicyContext,
    ) -> PolicyDecision:
        """Check if action permitted under current permissions."""
        ...

    def narrow_for_child(
        self,
        parent_permissions: PermissionSet,
        child_name: str,
    ) -> PermissionSet:
        """Create narrower permission set for child agent."""
        ...
```

---

## Data Models

### Permission

```python
class Permission(BaseModel):
    """Structured permission with category, action, scope."""
    category: Literal["fs", "shell", "net", "mcp", "subagent"]
    """Permission category."""
    action: Literal["read", "write", "execute", "connect", "spawn"]
    """Permission action."""
    scope: str
    """Scope pattern (glob, command name, or *)."""
```

### PermissionSet

```python
class PermissionSet(BaseModel):
    """Collection of permissions with scope-aware matching."""
    permissions: list[Permission]
    """Granted permissions."""
    deny_rules: list[Permission] = []
    """Deny rules (highest priority)."""
    approvable: list[Permission] = []
    """Permissions requiring approval."""
```

### ActionRequest

```python
class ActionRequest(BaseModel):
    """Action being requested for permission check."""
    action_type: Literal["tool_call", "subagent_spawn", "mcp_connect"]
    """Action type."""
    tool_name: str | None
    """Tool name for tool_call."""
    tool_args: dict[str, Any] | None
    """Tool arguments."""
```

### PolicyDecision

```python
class PolicyDecision(BaseModel):
    """Permission decision result."""
    verdict: Literal["allow", "deny", "need_approval"]
    """Decision verdict."""
    reason: str
    """Reason for decision."""
    matched_permission: Permission | None
    """Matching permission (if allow)."""
```

### PolicyContext

```python
class PolicyContext(BaseModel):
    """Context for permission evaluation."""
    thread_id: str
    """Thread identifier."""
    parent_agent: str | None
    """Parent agent name (for child narrowing)."""
    metadata: dict[str, Any] = {}
    """Additional context."""
```

---

## Design Principles

### 1. Least-Privilege Delegation

Every delegation narrows permission set:
- Parent permissions restricted for children
- Explicit permission inheritance
- Scope reduction for security
- No implicit permission escalation

### 2. Fine-Grained Control

Permissions structured for granular access:
- Category: fs, shell, net, mcp, subagent
- Action: read, write, execute, connect, spawn
- Scope: glob patterns, command names, wildcards

### 3. Structured Permission Matching

Scope-aware matching with glob patterns:
- `fs:read:*` → All filesystem read
- `fs:read:/tmp/*` → Read only /tmp directory
- `shell:execute:git` → Execute git command only
- Deny rules override granted permissions

### 4. Approval Workflow

Some permissions require explicit approval:
- Approvable permissions flagged in config
- `need_approval` verdict prompts user
- User grants/denies interactively
- Approval cached for session

---

## ConfigDrivenPolicy Implementation

```python
class ConfigDrivenPolicy(PolicyProtocol):
    """Configuration-driven policy implementation."""

    def __init__(self, profiles: dict[str, PolicyProfile]) -> None:
        self._profiles = profiles

    def check(
        self,
        action: ActionRequest,
        context: PolicyContext,
    ) -> PolicyDecision:
        """Evaluate action against permission set."""

        # 1. Check deny rules (highest priority)
        for deny in context.permissions.deny_rules:
            if self._matches_permission(action, deny):
                return PolicyDecision(verdict="deny", reason=f"Denied by rule: {deny}")

        # 2. Check granted permissions
        for perm in context.permissions.permissions:
            if self._matches_permission(action, perm):
                return PolicyDecision(verdict="allow", reason=f"Granted by: {perm}", matched_permission=perm)

        # 3. Check approvable set
        for approvable in context.permissions.approvable:
            if self._matches_permission(action, approvable):
                return PolicyDecision(verdict="need_approval", reason=f"Requires approval: {approvable}")

        # 4. Default deny
        return PolicyDecision(verdict="deny", reason="No matching permission")

    def narrow_for_child(
        self,
        parent_permissions: PermissionSet,
        child_name: str,
    ) -> PermissionSet:
        """Create child permission set (subset of parent)."""
        # Narrow scope, remove sensitive categories
        child_permissions = []
        for perm in parent_permissions.permissions:
            # Reduce scope (e.g., /tmp/* → /tmp/child/*)
            narrowed_scope = self._narrow_scope(perm.scope, child_name)
            child_permissions.append(Permission(
                category=perm.category,
                action=perm.action,
                scope=narrowed_scope,
            ))

        return PermissionSet(
            permissions=child_permissions,
            deny_rules=parent_permissions.deny_rules,  # Keep deny rules
            approvable=[],  # Remove approvable for children
        )

    def _matches_permission(self, action: ActionRequest, permission: Permission) -> bool:
        """Scope-aware matching logic."""
        # Category + action matching
        if action.action_type == "tool_call":
            tool_category = self._infer_tool_category(action.tool_name)
            if tool_category != permission.category:
                return False
            # Scope matching with glob patterns
            return fnmatch.fnmatch(action.tool_name, permission.scope)
        # ... other action types
```

---

## Permission Categories

| Category | Actions | Scope Examples |
|----------|---------|----------------|
| **fs** | read, write | `/tmp/*`, `*.json`, `*` |
| **shell** | execute | `git`, `npm`, `python*` |
| **net** | connect | `https://api.example.com/*`, `*` |
| **mcp** | connect | `filesystem`, `postgres`, `*` |
| **subagent** | spawn | `research_agent`, `*` |

---

## Configuration

```yaml
policy:
  default_profile: standard  # readonly | standard | privileged
  profiles:
    readonly:
      permissions:
        - category: fs
          action: read
          scope: "*"
      deny_rules: []
      approvable: []

    standard:
      permissions:
        - category: fs
          action: read
          scope: "*"
        - category: fs
          action: write
          scope: "/tmp/*"
        - category: shell
          action: execute
          scope: "git"
      deny_rules:
        - category: shell
          action: execute
          scope: "rm -rf /"
      approvable:
        - category: net
          action: connect
          scope: "*"

    privileged:
      permissions:
        - category: "*"
          action: "*"
          scope: "*"
```

---

## Implementation Status

- ✅ PolicyProtocol interface
- ✅ Permission structured model
- ✅ PermissionSet scope-aware matching
- ✅ ConfigDrivenPolicy implementation
- ✅ Fine-grained category/action/scope
- ✅ Least-privilege delegation narrowing
- ✅ Approval workflow support
- ✅ Deny rules override logic

---

## References

- RFC-000: System Conceptual Design (§7 Least-privilege delegation)
- RFC-100: CoreAgent Runtime (tool execution)
- RFC-001: Core Modules Architecture (original Module 4)

---

## Changelog

### 2026-04-17
- Consolidated RFC-001 Module 4 (PolicyProtocol) with Permission structure design from RFC-406
- Unified fine-grained permission model with scope-aware matching
- Defined permission categories (fs, shell, net, mcp, subagent) with action/scope structure
- Maintained least-privilege delegation principle and approval workflow
- Clarified permission narrowing for child agents

---

*PolicyProtocol permission checking interface with fine-grained category/action/scope structure, scope-aware matching, and least-privilege delegation narrowing.*