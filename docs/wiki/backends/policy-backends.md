# Policy Backends

PolicyProtocol implementations for security and filesystem policies.

---

## Overview

Policy backends implement `PolicyProtocol` for managing security policies, filesystem access rules, and least-privilege delegation. They enforce security boundaries and permission checks across Soothe's execution.

---

## PolicyProtocol Interface

### Core Operations

```python
class PolicyProtocol(Protocol):
    """Permission-based access control."""

    def check(self, action: ActionRequest, context: PolicyContext) -> PolicyDecision: ...
    def narrow_for_child(self, parent_permissions: PermissionSet, child_name: str) -> PermissionSet: ...
```

---

## Policy Data Model

### PolicyContext

Policy evaluation context:

```python
class PolicyContext(BaseModel):
    """Context for policy evaluation."""

    model_config = {"arbitrary_types_allowed": True}

    active_permissions: Any  # PermissionSet (the currently granted permissions)
    scope_id: str | None = None  # Opaque execution scope for audit (e.g. loop id)
    workspace: str | None = None  # Absolute workspace root (from config)
```

### Permission

A structured permission with category, action, and scope:

```python
@dataclass(frozen=True)
class Permission:
    """A structured permission."""

    category: str  # Permission category (fs, shell, net, mcp, subagent)
    action: str    # Action type (read, write, execute, connect, spawn)
    scope: str = "*"  # Scope qualifier (* for all, glob for paths, name or !name for commands)

    def matches(self, requested: Permission) -> bool: ...
```

### PermissionSet

Immutable collection of permissions with scope-aware matching:

```python
class PermissionSet:
    """Immutable collection of permissions."""

    def __init__(self, permissions: frozenset[Permission] | None = None) -> None: ...

    @property
    def permissions(self) -> frozenset[Permission]: ...

    def contains(self, requested: Permission) -> bool: ...
    def narrow(self, allowed: frozenset[Permission]) -> PermissionSet: ...
```

### PolicyDecision

Result of a policy check:

```python
class PolicyDecision(BaseModel):
    """Result of a policy check."""

    model_config = {"arbitrary_types_allowed": True}

    verdict: Literal["allow", "deny", "need_approval"]
    reason: str
    matched_permission: Any = None  # Permission | None
```

### PolicyProfile

A named policy configuration:

```python
class PolicyProfile(BaseModel):
    """A named policy configuration."""

    model_config = {"arbitrary_types_allowed": True}

    name: str  # Profile name (e.g., "readonly", "standard", "privileged")
    permissions: Any  # PermissionSet (granted permissions)
    approvable: Any = None  # PermissionSet | None (permissions that can be approved interactively)
    deny_rules: list[Any] = []  # list[Permission] (explicit deny rules that override grants)
```

---

## Available Backends

### ConfigDrivenPolicy

Configuration-based policy management with flexible rules.

#### Features

- **Config-based**: Policies defined in YAML configuration
- **Least-privilege**: Fine-grained permission control
- **Path Whitelisting**: Allow specific paths for file operations
- **Tool Filtering**: Restrict available tools per context
- **Sandbox Enforcement**: Execute operations in sandboxed environment
- **Dynamic Policies**: Policy rules can change based on context

#### Architecture

```
ConfigDrivenPolicy Architecture
├─ Policy Profiles
│  ├─ Named profiles (readonly, standard, privileged)
│  ├─ PermissionSet per profile
│  ├─ Approvable permissions (interactive approval)
│  └─ Deny rules (explicit overrides)
│
├─ Policy Evaluation Engine
│  ├─ Action → Permission extraction
│  ├─ Deny-rule check (first priority)
│  ├─ Permission grant check
│  ├─ Approvable set check
│  └─ Default deny
│
├─ Least-Privilege Delegation
│  ├─ narrow_for_child() for subagent spawning
│  └─ Intersection semantics
│
├─ Operation Security
│  ├─ WorkspaceToolOperationSecurity integration
│  ├─ Filesystem path extraction
│  └─ Shell command extraction
│
└─ Child Restrictions
   ├─ Per-child permission overrides
   └─ Delegation depth tracking
```

#### Implementation

```python
class ConfigDrivenPolicy:
    """PolicyProtocol implementation driven by named policy profiles.

    Evaluation order: (1) deny rules, (2) granted permissions,
    (3) approvable set, (4) default deny.
    """

    def __init__(
        self,
        profiles: dict[str, PolicyProfile] | None = None,
        child_restrictions: dict[str, frozenset[Permission]] | None = None,
        config: Any = None,
    ):
        """Initialize the config-driven policy.

        Args:
            profiles: Mapping of profile name to PolicyProfile.
                      Defaults to readonly/standard/privileged.
            child_restrictions: Per-child permission overrides.
            config: SootheConfig instance for security policy checks.
        """
        self._profiles = profiles or dict(DEFAULT_PROFILES)
        self._child_restrictions = child_restrictions or {}
        self._config = config
        self._operation_security = WorkspaceToolOperationSecurity()

    def check(self, action: ActionRequest, context: PolicyContext) -> PolicyDecision:
        """Check if an action is permitted under the active profile."""

        # Operation security check for tool calls
        if action.action_type == "tool_call" and action.tool_name:
            request = self._build_operation_security_request(action)
            op_context = OperationSecurityContext(
                thread_id=context.scope_id,
                workspace=context.workspace,
                security_config=getattr(self._config, "security", None),
            )
            op_decision = self._operation_security.evaluate(request, op_context)
            if op_decision.verdict != "allow":
                return PolicyDecision(verdict=op_decision.verdict, reason=op_decision.reason)

        # Extract required permission from action
        required = _extract_required_permission(action)
        if required is None:
            return PolicyDecision(verdict="allow", reason="No permission required")

        permissions: PermissionSet = context.active_permissions
        profile = self._find_profile(permissions)

        # (1) Check deny rules first
        if profile and any(
            Permission(d.category, d.action, d.scope).matches(required)
            for d in profile.deny_rules
        ):
            return PolicyDecision(verdict="deny", reason=f"Explicitly denied: {required}")

        # (2) Check granted permissions
        if permissions.contains(required):
            return PolicyDecision(
                verdict="allow",
                reason="Permitted by grant",
                matched_permission=required,
            )

        # (3) Check approvable set
        if profile and profile.approvable and profile.approvable.contains(required):
            return PolicyDecision(verdict="need_approval", reason=f"Requires approval: {required}")

        # (4) Default deny
        return PolicyDecision(verdict="deny", reason=f"Not permitted: {required}")

    def narrow_for_child(
        self, parent_permissions: PermissionSet, child_name: str
    ) -> PermissionSet:
        """Compute a narrowed permission set for a child subagent."""
        allowed = self._child_restrictions.get(child_name)
        if allowed is not None:
            return parent_permissions.narrow(allowed)
        return parent_permissions
```

#### Configuration

```yaml
agent:
  protocols:
    policy:
      enabled: true
      profile: standard          # Default policy profile (readonly, standard, privileged)
```

Built-in profiles:
- **readonly**: `fs:read:*`, `net:outbound:*`, `subagent:spawn:*` (write/execute approvable)
- **standard**: Full read/write/execute/net/mcp/subagent (default)
- **privileged**: Same as standard (no approvable restrictions)

#### Usage Example

```python
from soothe.foundation.core.security.config_policy import ConfigDrivenPolicy
from soothe.protocols.policy import ActionRequest, PolicyContext, PermissionSet, Permission
from soothe.config import SootheConfig

config = SootheConfig.from_yaml_file("config.yml")
policy = ConfigDrivenPolicy(config=config)

# Check permission for a tool call
context = PolicyContext(
    active_permissions=PermissionSet(frozenset([
        Permission("fs", "read", "*"),
        Permission("fs", "write", "/tmp/**"),
    ])),
    scope_id="loop_abc",
    workspace="/path/to/project",
)

action = ActionRequest(action_type="tool_call", tool_name="read_file", tool_args={"path": "/path/to/src"})
decision = policy.check(action, context)
print(f"Verdict: {decision.verdict}")  # "allow"

# Narrow permissions for a child subagent
child_perms = policy.narrow_for_child(context.active_permissions, "explore")
```

---

## Permission Model

### Permission Categories

Permissions use a structured `category:action:scope` format:

| Category | Actions | Scope Examples |
|----------|---------|----------------|
| `fs` | `read`, `write` | `*`, `/tmp/**`, `/home/user/**` |
| `shell` | `execute` | `ls`, `git`, `!rm` (anything except rm) |
| `net` | `outbound` | `*.example.com`, `*` |
| `mcp` | `connect`, `invoke`, `read_resource` | server name |
| `subagent` | `spawn` | subagent name |

### Built-in Profiles

Three built-in policy profiles are available:

```python
# readonly: read-only filesystem + network + subagent spawn
READONLY_PROFILE = PolicyProfile(
    name="readonly",
    permissions=PermissionSet(frozenset([
        Permission("fs", "read", "*"),
        Permission("net", "outbound", "*"),
        Permission("subagent", "spawn", "*"),
    ])),
    approvable=PermissionSet(frozenset([
        Permission("fs", "write", "*"),
        Permission("shell", "execute", "*"),
    ])),
)

# standard: full read/write/execute/net/mcp/subagent
STANDARD_PROFILE = PolicyProfile(name="standard", ...)

# privileged: same as standard, no approvable restrictions
PRIVILEGED_PROFILE = PolicyProfile(name="privileged", ...)
```

### Permission Matching

Matching uses glob patterns with negation support:

```python
Permission("fs", "read", "*")           # Read any file
Permission("fs", "write", "/tmp/**")     # Write only under /tmp
Permission("shell", "execute", "ls")     # Execute only ls
Permission("shell", "execute", "!rm")    # Anything EXCEPT rm
Permission("net", "outbound", "*.example.com")  # Only example.com
```

---

## Least-Privilege Delegation

### Principle

Soothe enforces least-privilege: subagents receive a narrowed subset of the parent's permissions.

```python
# Parent has: fs:read:*, fs:write:/tmp/**
# Child "explore" gets: fs:read:* (intersection)
child_perms = policy.narrow_for_child(parent_permissions, "explore")
```

### Child Restrictions

Per-child overrides can restrict further:

```python
policy = ConfigDrivenPolicy(
    profiles=dict(DEFAULT_PROFILES),
    child_restrictions={
        "explore": frozenset({Permission("fs", "read", "*")}),
    },
)
```

---

## Sandbox Enforcement

### Operation Security Integration

ConfigDrivenPolicy integrates with `WorkspaceToolOperationSecurity` for tool-call evaluation:

```python
# When a tool_call action is checked, ConfigDrivenPolicy first evaluates
# operation security (filesystem path validation, shell command validation)
# before checking permissions.
decision = policy.check(action, context)
# decision.verdict: "allow", "deny", or "need_approval"
```

### Integration with FrameworkFilesystem

```python
class FrameworkFilesystem:
    """Workspace-aware filesystem backend."""

    async def read_file(self, path: str):
        # Policy is enforced via middleware, not direct calls
        # PolicyEnforcementMiddleware intercepts tool calls and
        # calls policy.check(action, context) before execution
        ...
```

---

## Performance Characteristics

### ConfigDrivenPolicy Performance

| Operation | Performance | Notes |
|-----------|-------------|-------|
| `check()` | ~5-15ms | Permission extraction + matching |
| `narrow_for_child()` | ~1-5ms | Set intersection |
| `_find_profile()` | ~1-2ms | Profile lookup |

**Optimization Tips**:
- Cache policy decisions per context
- Pre-compile wildcard patterns
- Minimize rule count for fast evaluation
- Use specific rules over wildcards

---

## Comparison Table

### Policy Backend Comparison

| Feature | ConfigDrivenPolicy |
|---------|--------------------|
| Configuration Type | Profile-based (named profiles) |
| Least-privilege Support | ✅ (narrow_for_child) |
| Permission Model | Structured (category/action/scope) |
| Built-in Profiles | readonly, standard, privileged |
| Custom Profiles | ✅ |
| Child Restrictions | ✅ (per-subagent overrides) |
| Deny Rules | ✅ (override grants) |
| Approvable Permissions | ✅ (interactive approval) |
| Operation Security | ✅ (WorkspaceToolOperationSecurity) |
| Context-aware Decisions | ✅ |

---

## Error Handling

### Policy Violations

```python
try:
    await filesystem.read_file("/etc/passwd")
except PolicyViolationError as e:
    logger.warning(f"Policy violation: {e}")
    
    # Handle specific violations:
    if "path_denied" in str(e):
        # Notify user of denied access
        pass
    
    elif "tool_denied" in str(e):
        # Suggest alternative tool
        pass
    
    elif "command_denied" in str(e):
        # Suggest alternative command
        pass
```

---

## Integration with Security

### Integration with FrameworkFilesystem

```python
class FrameworkFilesystem:
    def __init__(self, policy: ConfigDrivenPolicy, context: PolicyContext):
        self._policy = policy
        self._context = context

    async def _check_permission(self, action: ActionRequest):
        """Check permission before operation."""
        decision = self._policy.check(action, self._context)

        if decision.verdict != "allow":
            raise PolicyViolationError(
                f"Access denied: {decision.reason}"
            )
```

---

## Testing

### Unit Testing

```python
import pytest

@pytest.mark.asyncio
async def test_config_driven_policy():
    """Test ConfigDrivenPolicy backend."""
    policy = ConfigDrivenPolicy()

    context = PolicyContext(
        active_permissions=PermissionSet(frozenset([
            Permission("fs", "read", "*"),
            Permission("fs", "write", "/tmp/**"),
        ])),
        scope_id="test",
        workspace="/tmp/workspace",
    )

    # Test allowed read
    action = ActionRequest(action_type="tool_call", tool_name="read_file", tool_args={"path": "/tmp/workspace/file.txt"})
    decision = policy.check(action, context)
    assert decision.verdict == "allow"

    # Test denied write outside /tmp
    action = ActionRequest(action_type="tool_call", tool_name="write_file", tool_args={"path": "/etc/passwd"})
    decision = policy.check(action, context)
    assert decision.verdict == "deny"

    # Test narrow_for_child
    child_perms = policy.narrow_for_child(context.active_permissions, "explore")
    assert child_perms.contains(Permission("fs", "read", "*"))
```

---

## Configuration Examples

### Basic Configuration

```yaml
agent:
  protocols:
    policy:
      enabled: true
      profile: standard    # readonly, standard, or privileged
```

### Advanced Configuration

```yaml
agent:
  protocols:
    policy:
      enabled: true
      profile: standard

agent:
  security:
    sandbox: true
    allow_paths_outside_workspace: false
    denied_paths:
      - /etc
      - /usr
    denied_file_types:
      - .env
      - .pem
```

---

## Related Documentation

- **[Backends Overview](README.md)** - Backend layer introduction
- **[Workspace Management](../core/workspace.md)** - Workspace security
- **[RFC-102](../../specs/RFC-102-security-filesystem-policy.md)** - Security policy spec
- **[RFC-001](../../specs/RFC-001-core-modules-architecture.md)** - Policy protocol spec

---

## API Reference

### ConfigDrivenPolicy Class

```python
class ConfigDrivenPolicy:
    """PolicyProtocol implementation driven by named policy profiles."""

    def __init__(
        self,
        profiles: dict[str, PolicyProfile] | None = None,
        child_restrictions: dict[str, frozenset[Permission]] | None = None,
        config: Any = None,
    ) -> None: ...

    def check(self, action: ActionRequest, context: PolicyContext) -> PolicyDecision: ...
    def narrow_for_child(self, parent_permissions: PermissionSet, child_name: str) -> PermissionSet: ...
```

---

## See Also

- **[Policy Protocol](../architecture/protocols.md)** - Protocol definition
- **[Protocol Resolver](../core/resolver.md)** - Backend resolution
- **[Workspace Management](../core/workspace.md)** - Workspace security