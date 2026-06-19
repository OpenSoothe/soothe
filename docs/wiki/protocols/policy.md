# PolicyProtocol

**RFC**: 305 (Protocol Specifications series)
**Module**: RFC-000 Module 4
**Location**: `packages/soothe-sdk/src/soothe_sdk/protocols/policy.py` (SDK)
**Re-exported**: `packages/soothe/src/soothe/protocols/policy.py`
**Note**: Reclassified from 4xx to 3xx per RFC-900 series semantics
**Status**: Implemented  

## Overview

PolicyProtocol defines the interface for **permission-based access control** in Soothe. It implements the least-privilege delegation principle (RFC-000 Principle 7), checking whether actions (tool calls, subagent spawns, MCP connections) are permitted under the current permission set.

## Purpose

- **Permission enforcement**: Check actions before execution
- **Least-privilege delegation**: Subagents inherit narrower permissions
- **Structured permissions**: Category + action + scope granularity
- **Profile-based configuration**: Named permission profiles
- **Approval workflow**: Allow/deny/need-approval decisions

## Protocol Interface

```python
@runtime_checkable
class PolicyProtocol(Protocol):
    """Protocol for permission-based access control.
    
    Every tool invocation and subagent spawn passes through
    PolicyProtocol before execution. Permissions are structured
    with category, action, and scope for fine-grained control.
    """

    def check(self, request: ActionRequest, context: PolicyContext) -> PolicyDecision:
        """Check if an action is permitted.
        
        Args:
            request: The action being requested.
            context: Current policy context (profile, delegation depth).
            
        Returns:
            PolicyDecision (allowed, denied, need_approval).
        """
        ...

    def get_permissions(self, profile: str) -> PermissionSet:
        """Get the permission set for a policy profile.
        
        Args:
            profile: Profile name (readonly, standard, privileged).
            
        Returns:
            PermissionSet for the profile.
        """
        ...
```

## Data Models

### Permission

```python
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
        scope: Scope qualifier (* for all, glob for paths, 
               name or !name for commands).
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
        ...
```

**Permission Categories**:
- **fs**: File system operations (read, write)
- **shell**: Shell command execution
- **net**: Network outbound connections
- **mcp**: MCP server connections
- **subagent**: Subagent spawning

**Scope Patterns**:
- `*`: All items in category
- `path/**`: Glob pattern for paths
- `name`: Specific item (command, server, subagent)
- `!name`: Exclusion pattern (anything except)

### PermissionSet

```python
class PermissionSet:
    """Immutable collection of permissions with scope-aware matching.
    
    Args:
        permissions: The set of granted permissions.
    """

    def __init__(self, permissions: frozenset[Permission] | None = None) -> None:
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
```

### ActionRequest

```python
class ActionRequest(BaseModel):
    """Request to perform an action requiring permission check.
    
    Args:
        action: The action being requested.
        context: Additional context for the request.
        delegation_depth: How many levels deep the delegation is.
    """

    action: Permission
    context: dict[str, Any] = Field(default_factory=dict)
    delegation_depth: int = 0
```

### PolicyContext

```python
class PolicyContext(BaseModel):
    """Context for policy decisions.
    
    Args:
        profile: Active policy profile name.
        thread_id: Current thread ID.
        delegation_depth: Current delegation depth (for subagent spawning).
        parent_permissions: Permission set of parent (for narrowing).
    """

    profile: str = "standard"
    thread_id: str | None = None
    delegation_depth: int = 0
    parent_permissions: PermissionSet | None = None
```

### PolicyDecision

```python
class PolicyDecision(BaseModel):
    """Decision from policy check.
    
    Args:
        allowed: Whether the action is permitted.
        reason: Explanation for the decision.
        need_approval: Whether manual approval is needed.
        approval_message: Message for approval request.
    """

    allowed: bool
    reason: str
    need_approval: bool = False
    approval_message: str | None = None
```

### PolicyProfile

```python
class PolicyProfile(BaseModel):
    """Named configuration of permitted actions.
    
    Args:
        name: Profile name.
        permissions: List of granted permissions.
        description: Human-readable description.
        approval_required: Actions requiring manual approval.
    """

    name: str
    permissions: list[Permission]
    description: str = ""
    approval_required: list[str] = Field(default_factory=list)
```

## Backend Implementations

### ConfigDrivenPolicy

**Status**: Current implementation  
**Location**: `packages/soothe/src/soothe/backends/policy/config_policy.py`  
**Dependencies**: Configuration-based permission profiles

**Features**:
- YAML-based profile configuration
- Permission inheritance for subagents
- Approval workflow support
- Delegation depth tracking

**Configuration**:
```yaml
# config/config.template.yml
policy:
  profiles:
    readonly:
      permissions:
        - category: fs
          action: read
          scope: "*"
        - category: shell
          action: execute
          scope: "ls"
      description: Read-only access
    
    standard:
      permissions:
        - category: fs
          action: read
          scope: "*"
        - category: fs
          action: write
          scope: "/tmp/**"
        - category: shell
          action: execute
          scope: "*"
        - category: shell
          action: execute
          scope: "!rm"  # Deny rm
      description: Standard development access
    
    privileged:
      permissions:
        - category: "*"
          action: "*"
          scope: "*"
      description: Full access (dangerous)
```

**Implementation Example**:
```python
class ConfigDrivenPolicy(PolicyProtocol):
    """Policy implementation driven by configuration profiles."""
    
    def __init__(self, config: SootheConfig) -> None:
        self._profiles = self._load_profiles(config)
    
    def check(
        self, 
        request: ActionRequest, 
        context: PolicyContext
    ) -> PolicyDecision:
        """Check action against profile permissions."""
        profile = self._profiles.get(context.profile)
        if not profile:
            return PolicyDecision(
                allowed=False,
                reason=f"Unknown profile: {context.profile}"
            )
        
        permissions = profile.permissions
        if request.action in permissions:
            return PolicyDecision(
                allowed=True,
                reason=f"Permitted by profile {context.profile}"
            )
        
        return PolicyDecision(
            allowed=False,
            reason=f"Action {request.action} not in profile {context.profile}"
        )
```

## Usage Patterns

### Permission Checking

```python
from soothe.protocols import (
    Permission, PermissionSet, ActionRequest, 
    PolicyContext, PolicyProtocol
)

policy: PolicyProtocol = resolve_policy(config)

# Check file system read permission
request = ActionRequest(
    action=Permission("fs", "read", "/project/src/main.py"),
    delegation_depth=0
)
context = PolicyContext(profile="readonly")

decision = policy.check(request, context)
if decision.allowed:
    # Proceed with file read
    ...
elif decision.need_approval:
    # Request user approval
    ...
else:
    # Deny action
    raise PermissionError(decision.reason)
```

### Subagent Permission Narrowing

```python
# Parent has standard permissions
parent_permissions = policy.get_permissions("standard")

# Child subagent gets narrower permissions
child_allowed = frozenset([
    Permission("fs", "read", "/project/**"),
    Permission("shell", "execute", "git"),
])

child_permissions = parent_permissions.narrow(child_allowed)

# Child context
child_context = PolicyContext(
    profile="standard",
    delegation_depth=1,
    parent_permissions=parent_permissions
)
```

### Exclusion Patterns

```python
# Deny rm command but allow everything else
profile_permissions = PermissionSet(frozenset([
    Permission("shell", "execute", "*"),  # Allow all commands
    Permission("shell", "execute", "!rm"),  # Deny rm
]))

# Request to execute rm
request = Permission("shell", "execute", "rm")
decision = profile_permissions.contains(request)  # False

# Request to execute ls
request = Permission("shell", "execute", "ls")
decision = profile_permissions.contains(request)  # True
```

## Integration with Other Protocols

### Policy ↔ Enforcement Integration

Policy decisions are enforced via middleware:

```python
from soothe.middleware.policy_enforcement import PolicyEnforcementMiddleware

# Middleware intercepts tool calls and subagent spawns
enforcement = PolicyEnforcementMiddleware(policy_protocol)

# Before each action:
# 1. Create ActionRequest
# 2. Call policy.check(request, context)
# 3. If allowed: proceed
# 4. If denied: raise PermissionError
# 5. If need_approval: pause for user input
```

### Policy ↔ Durability Integration

Threads carry policy profile:

```python
from soothe.protocols import ThreadMetadata

metadata = ThreadMetadata(
    policy_profile="readonly"  # Applied to all thread operations
)

thread = await durability.create_thread(metadata)
```

### Policy ↔ Subagent Integration

Subagents inherit narrowed permissions:

```
Parent (depth=0, profile=standard):
  → PermissionSet([...])
  
Child Subagent (depth=1):
  → Narrowed to allowed subset
  → Cannot exceed parent permissions
  
Grandchild Subagent (depth=2):
  → Further narrowed
  → Depth tracking for auditing
```

## Permission Categories

### File System (fs)

```python
# Read any file
Permission("fs", "read", "*")

# Write only under /tmp
Permission("fs", "write", "/tmp/**")

# Read specific project directory
Permission("fs", "read", "/project/**")
```

### Shell (shell)

```python
# Execute any command
Permission("shell", "execute", "*")

# Execute only safe commands
Permission("shell", "execute", "ls")
Permission("shell", "execute", "git")
Permission("shell", "execute", "cat")

# Deny dangerous commands
Permission("shell", "execute", "!rm")
Permission("shell", "execute", "!sudo")
```

### Network (net)

```python
# Outbound to any host
Permission("net", "outbound", "*")

# Outbound only to specific domains
Permission("net", "outbound", "*.example.com")
Permission("net", "outbound", "api.github.com")
```

### MCP (mcp)

```python
# Connect to any MCP server
Permission("mcp", "connect", "*")

# Connect to specific MCP server
Permission("mcp", "connect", "filesystem-server")
Permission("mcp", "connect", "github-server")
```

### Subagent (subagent)

```python
# Spawn any subagent
Permission("subagent", "spawn", "*")

# Spawn specific subagents
Permission("subagent", "spawn", "planner")
Permission("subagent", "spawn", "explore")
Permission("subagent", "spawn", "research")
```

## Policy Profiles

### readonly Profile

```yaml
readonly:
  permissions:
    - category: fs
      action: read
      scope: "*"
    - category: shell
      action: execute
      scope: "ls"
    - category: shell
      action: execute
      scope: "cat"
  description: Read-only access, no modifications
```

### standard Profile

```yaml
standard:
  permissions:
    - category: fs
      action: read
      scope: "*"
    - category: fs
      action: write
      scope: "/tmp/**"
    - category: shell
      action: execute
      scope: "*"
    - category: shell
      action: execute
      scope: "!rm"
    - category: mcp
      action: connect
      scope: "*"
    - category: subagent
      action: spawn
      scope: "*"
  description: Standard development access
```

### privileged Profile

```yaml
privileged:
  permissions:
    - category: "*"
      action: "*"
      scope: "*"
  description: Full access (dangerous, use with caution)
```

## Configuration

### Policy Protocol Settings

```yaml
# config/config.template.yml
policy:
  profiles:
    readonly: [...]
    standard: [...]
    privileged: [...]
  
  default_profile: standard
  approval_timeout: 300  # seconds
```

### Resolution

```python
from soothe.core.resolver import resolve_policy

# Resolve policy protocol from config
policy = resolve_policy(config)

# Returns: PolicyProtocol implementation
# Backend: ConfigDrivenPolicy
```

## Testing

### Unit Tests

**Location**: `packages/soothe/tests/unit/backends/policy/`

Tests verify:
- Permission matching logic
- Scope pattern evaluation
- Exclusion pattern handling
- Permission set narrowing
- Profile-based decisions

### Integration Tests

Policy integration tests verify:
- Enforcement middleware integration
- Subagent permission inheritance
- Thread profile application
- Approval workflow

## Design Rationale

### Why Structured Permissions?

String-based permissions lack granularity:
- `fs:read:/tmp/**` vs `fs_read_tmp` is clearer
- Category/action separation enables grouping
- Scope patterns support glob matching
- Exclusion patterns (!) enable deny semantics

### Why Permission Narrowing?

Least-privilege principle (RFC-000 Principle 7):
- Children cannot exceed parent permissions
- Intersection semantics ensure safety
- Delegation depth tracking for auditing

### Why Profile-Based?

Named profiles simplify configuration:
- `readonly`, `standard`, `privileged` are intuitive
- Users select profiles, not permission lists
- Profiles are reusable across threads

## Specification Reference

- **RFC-305**: Policy Protocol Architecture
- **RFC-102**: Security Filesystem Policy
- **RFC-000**: System Conceptual Design (least-privilege principle)

## Related Documentation

- [Operation Security Protocol](operation-security.md)
- [Durability Protocol](durability.md)
- [Middleware Integration](../middleware.md)