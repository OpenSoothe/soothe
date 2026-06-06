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
    """Security and filesystem policy."""
    
    async def check_permission(self, action: str, resource: str, context: PolicyContext) -> bool: ...
    async def get_allowed_tools(self, context: PolicyContext) -> list[str]: ...
    async def get_allowed_paths(self, context: PolicyContext) -> list[str]: ...
    async def validate_file_access(self, path: str, operation: str, context: PolicyContext) -> bool: ...
    async def get_sandbox_config(self, context: PolicyContext) -> SandboxConfig: ...
```

---

## Policy Data Model

### PolicyContext

Policy evaluation context:

```python
class PolicyContext(BaseModel):
    """Policy evaluation context."""
    
    thread_id: str          # Thread identifier
    workspace: str          # Workspace directory
    user_id: str            # User identifier
    goal: str               # Current goal
    metadata: dict[str, Any] = {}  # Additional context
```

### SandboxConfig

Sandbox execution configuration:

```python
class SandboxConfig(BaseModel):
    """Sandbox configuration."""
    
    enabled: bool = True          # Enable sandboxing
    allowed_paths: list[str] = []  # Allowed file paths
    denied_paths: list[str] = []   # Denied file paths
    allowed_commands: list[str] = []  # Allowed shell commands
    network_access: bool = False    # Allow network access
    timeout: int = 60               # Execution timeout (seconds)
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
├─ Policy Configuration
│  ├─ YAML-based rules
│  ├─ Path policies (allow/deny)
│  ├─ Tool policies (allow/deny)
│  ├─ Command policies
│  ├─ Network policies
│  └─ Sandbox settings
│
├─ Policy Evaluation Engine
│  ├─ Permission checks
│  ├─ Resource validation
│  ├─ Path normalization
│  ├─ Wildcard matching
│  └─ Context-aware decisions
│
├─ Enforcement Layer
│  ├─ Filesystem interception
│  ├─ Tool filtering
│  ├─ Command blocking
│  ├─ Network blocking
│  └─ Timeout enforcement
│
└─ Audit & Logging
   ├─ Policy decisions
   ├─ Denied operations
   ├─ Sandbox violations
   └─ Security events
```

#### Implementation

```python
class ConfigDrivenPolicy(PolicyProtocol):
    """PolicyProtocol implementation using configuration."""
    
    def __init__(self, config: PolicyConfig):
        """Initialize config-driven policy backend."""
        
        self._config = config
        
        # Parse policy rules
        self._path_rules = self._parse_path_rules(config.path_policies)
        self._tool_rules = self._parse_tool_rules(config.tool_policies)
        self._command_rules = self._parse_command_rules(config.command_policies)
        
    async def check_permission(
        self,
        action: str,
        resource: str,
        context: PolicyContext
    ) -> bool:
        """Check if action is permitted on resource."""
        
        # Check path permissions for file operations
        if action in ["read", "write", "delete"]:
            return await self.validate_file_access(resource, action, context)
        
        # Check tool permissions
        if action == "use_tool":
            allowed_tools = await self.get_allowed_tools(context)
            return resource in allowed_tools
        
        # Check command permissions
        if action == "execute":
            allowed_commands = self._get_allowed_commands(context)
            return self._match_command(resource, allowed_commands)
        
        # Default deny
        return False
    
    async def get_allowed_tools(self, context: PolicyContext) -> list[str]:
        """Get list of allowed tools for context."""
        
        # Start with default allowed tools
        allowed = self._config.default_tools.copy()
        
        # Apply tool rules based on context
        for rule in self._tool_rules:
            if self._matches_context(rule, context):
                if rule["action"] == "allow":
                    allowed.extend(rule["tools"])
                elif rule["action"] == "deny":
                    allowed = [t for t in allowed if t not in rule["tools"]]
        
        return allowed
    
    async def get_allowed_paths(self, context: PolicyContext) -> list[str]:
        """Get list of allowed paths for context."""
        
        # Start with workspace (always allowed)
        allowed = [context.workspace]
        
        # Apply path rules based on context
        for rule in self._path_rules:
            if self._matches_context(rule, context):
                if rule["action"] == "allow":
                    allowed.extend(rule["paths"])
                elif rule["action"] == "deny":
                    allowed = [p for p in allowed if not self._matches_path(p, rule["paths"])]
        
        # Normalize paths
        allowed = [self._normalize_path(p) for p in allowed]
        
        return allowed
    
    async def validate_file_access(
        self,
        path: str,
        operation: str,
        context: PolicyContext
    ) -> bool:
        """Validate file access permission."""
        
        # Normalize path
        norm_path = self._normalize_path(path)
        
        # Check denied paths first
        denied_paths = self._get_denied_paths(context)
        for denied in denied_paths:
            if self._matches_path(norm_path, [denied]):
                return False
        
        # Check allowed paths
        allowed_paths = await self.get_allowed_paths(context)
        for allowed in allowed_paths:
            if self._matches_path(norm_path, [allowed]):
                return True
        
        # Default deny
        return False
    
    async def get_sandbox_config(self, context: PolicyContext) -> SandboxConfig:
        """Get sandbox configuration for context."""
        
        # Build sandbox config from policy rules
        sandbox = SandboxConfig(
            enabled=self._config.sandbox_enabled,
            allowed_paths=await self.get_allowed_paths(context),
            denied_paths=self._get_denied_paths(context),
            allowed_commands=self._get_allowed_commands(context),
            network_access=self._get_network_access(context),
            timeout=self._config.timeout
        )
        
        return sandbox
    
    # Helper methods
    def _parse_path_rules(self, policies: list[dict]) -> list[dict]: ...
    def _parse_tool_rules(self, policies: list[dict]) -> list[dict]: ...
    def _parse_command_rules(self, policies: list[dict]) -> list[dict]: ...
    def _matches_context(self, rule: dict, context: PolicyContext) -> bool: ...
    def _matches_path(self, path: str, patterns: list[str]) -> bool: ...
    def _normalize_path(self, path: str) -> str: ...
    def _get_denied_paths(self, context: PolicyContext) -> list[str]: ...
    def _get_allowed_commands(self, context: PolicyContext) -> list[str]: ...
    def _match_command(self, command: str, patterns: list[str]) -> bool: ...
    def _get_network_access(self, context: PolicyContext) -> bool: ...
```

#### Configuration

```yaml
protocols:
  policy:
    enabled: true
    backend: config          # ConfigDrivenPolicy backend
    
    # Sandbox settings
    sandbox_enabled: true    # Enable sandboxing
    timeout: 60              # Execution timeout (seconds)
    
    # Default permissions
    default_tools:
      - ls
      - read_file
      - grep
      - glob
    
    # Path policies
    path_policies:
      # Allow workspace by default
      - action: allow
        paths: ["${workspace}"]
        context: {}
      
      # Deny system paths
      - action: deny
        paths: ["/etc", "/usr", "/bin"]
        context: {}
      
      # Allow user home for specific contexts
      - action: allow
        paths: ["${HOME}"]
        context:
          tags: ["personal"]
      
      # Deny sensitive files
      - action: deny
        paths: ["**/.env", "**/secrets.*"]
        context: {}
    
    # Tool policies
    tool_policies:
      # Deny execute tool by default
      - action: deny
        tools: ["execute"]
        context: {}
      
      # Allow execute for trusted contexts
      - action: allow
        tools: ["execute"]
        context:
          tags: ["trusted"]
      
      # Allow all tools for admin contexts
      - action: allow
        tools: ["*"]
        context:
          user_id: ["admin"]
    
    # Command policies
    command_policies:
      # Allow safe commands
      - action: allow
        commands: ["ls", "cat", "grep", "find"]
        context: {}
      
      # Deny dangerous commands
      - action: deny
        commands: ["rm", "dd", "mkfs"]
        context: {}
      
      # Network access
      network_access: false   # Disable by default
```

#### Usage Example

```python
from soothe.backends.policy import ConfigDrivenPolicy
from soothe.protocols.policy import PolicyContext
from soothe.config import SootheConfig

config = SootheConfig.from_file("config.yml")
policy = ConfigDrivenPolicy(config.agent.protocols.policy)

# Check permission
context = PolicyContext(
    thread_id="thread_abc",
    workspace="/path/to/project",
    user_id="user123",
    goal="analyze codebase"
)

allowed = await policy.check_permission("read", "/path/to/project/src", context)
print(f"Read access allowed: {allowed}")

# Get allowed tools
tools = await policy.get_allowed_tools(context)
print(f"Allowed tools: {tools}")

# Get allowed paths
paths = await policy.get_allowed_paths(context)
print(f"Allowed paths: {paths}")

# Validate file access
allowed = await policy.validate_file_access("/path/to/project/.env", "read", context)
print(f"Can read .env: {allowed}")  # Should be False

# Get sandbox config
sandbox = await policy.get_sandbox_config(context)
print(f"Sandbox enabled: {sandbox.enabled}")
```

---

## Policy Rules

### Path Policies

Control filesystem access:

```yaml
path_policies:
  # Allow workspace
  - action: allow
    paths: ["${workspace}"]
    context: {}
  
  # Deny system paths
  - action: deny
    paths: ["/etc", "/usr", "/bin", "/sbin"]
    context: {}
  
  # Deny sensitive files (wildcards)
  - action: deny
    paths: ["**/.env", "**/secrets.*", "**/.git/**"]
    context: {}
  
  # Allow specific paths for trusted contexts
  - action: allow
    paths: ["/tmp", "/var/tmp"]
    context:
      tags: ["trusted"]
```

**Wildcard Patterns**:
- `*` - Single directory/file level
- `**` - Recursive (all levels)
- `${workspace}` - Current workspace
- `${HOME}` - User home directory

---

### Tool Policies

Control tool availability:

```yaml
tool_policies:
  # Deny dangerous tools by default
  - action: deny
    tools: ["execute", "delete_file"]
    context: {}
  
  # Allow execute for trusted contexts
  - action: allow
    tools: ["execute"]
    context:
      tags: ["trusted"]
  
  # Allow all tools for admin
  - action: allow
    tools: ["*"]  # Wildcard for all tools
    context:
      user_id: ["admin"]
  
  # Deny specific tools for untrusted
  - action: deny
    tools: ["requests_post", "requests_put", "requests_delete"]
    context:
      tags: ["untrusted"]
```

---

### Command Policies

Control shell command execution:

```yaml
command_policies:
  # Allow safe commands
  - action: allow
    commands: ["ls", "cat", "grep", "find", "wc", "sort"]
    context: {}
  
  # Deny dangerous commands
  - action: deny
    commands: ["rm", "dd", "mkfs", "chmod", "chown"]
    context: {}
  
  # Allow development commands for trusted
  - action: allow
    commands: ["git", "npm", "pip", "python"]
    context:
      tags: ["trusted"]
```

---

### Network Policies

Control network access:

```yaml
# Network access policy
network_access: false  # Disable by default

# Or context-based
network_policies:
  - action: allow
    context:
      tags: ["web_research"]
  
  - action: deny
    context:
      tags: ["local_only"]
```

---

## Context Matching

### Policy Context Fields

Policies can match on context fields:

```yaml
context:
  # Match by thread_id
  thread_id: ["thread_specific"]
  
  # Match by workspace
  workspace: ["trusted_workspace"]
  
  # Match by user_id
  user_id: ["admin", "trusted"]
  
  # Match by goal keywords
  goal_keywords: ["analyze", "research"]
  
  # Match by tags
  tags: ["trusted", "personal"]
  
  # Match by metadata
  metadata:
    source: ["cli", "daemon"]
```

---

## Least-Privilege Delegation

### Principle

Soothe enforces least-privilege: operations receive minimum necessary permissions.

```python
# Goal: "Read file from /tmp"
# Permission: read access to /tmp only

# Goal: "Execute build script"
# Permission: execute "npm run build" only

# Goal: "Delete temporary files"
# Permission: delete access to workspace/tmp/** only
```

### Delegation Example

```yaml
# Least-privilege delegation
tool_policies:
  # Allow read-only for analysis
  - action: allow
    tools: ["ls", "read_file", "grep", "glob"]
    context:
      goal_keywords: ["analyze", "inspect"]
  
  # Deny write for read-only goals
  - action: deny
    tools: ["write_file", "edit_file", "delete_file"]
    context:
      goal_keywords: ["analyze", "inspect"]
```

---

## Sandbox Enforcement

### Sandbox Configuration

Sandboxed execution isolates operations:

```python
sandbox = await policy.get_sandbox_config(context)

# Sandbox applies:
# - Path restrictions (allowed/denied)
# - Command filtering
# - Network blocking
# - Timeout enforcement
# - Audit logging
```

### Integration with FrameworkFilesystem

```python
class FrameworkFilesystem:
    """Workspace-aware filesystem backend."""
    
    async def read_file(self, path: str):
        # Check policy
        allowed = await self._policy.validate_file_access(
            path, "read", self._context
        )
        
        if not allowed:
            raise PolicyViolationError(f"Read access denied: {path}")
        
        # Audit log
        self._audit_logger.log("read", path, allowed=True)
        
        # Execute operation
        return await self._filesystem.read_file(path)
```

---

## Performance Characteristics

### ConfigDrivenPolicy Performance

| Operation | Performance | Notes |
|-----------|-------------|-------|
| `check_permission()` | ~5-10ms | Rule evaluation |
| `get_allowed_tools()` | ~5-10ms | Rule parsing + matching |
| `get_allowed_paths()` | ~5-10ms | Path normalization + matching |
| `validate_file_access()` | ~5-15ms | Path matching overhead |
| `get_sandbox_config()` | ~10-20ms | Config compilation |

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
| Configuration Type | YAML-based |
| Least-privilege Support | ✅ |
| Path Policies | ✅ (allow/deny, wildcards) |
| Tool Policies | ✅ (allow/deny, wildcards) |
| Command Policies | ✅ (allow/deny) |
| Network Policies | ✅ |
| Sandbox Enforcement | ✅ |
| Context-aware Decisions | ✅ |
| Audit Logging | ✅ |
| Dynamic Policies | ✅ |

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
    def __init__(self, policy: PolicyProtocol, context: PolicyContext):
        self._policy = policy
        self._context = context
        self._audit_logger = AuditLogger()
        
    async def _check_permission(self, operation: str, path: str):
        """Check permission before operation."""
        allowed = await self._policy.validate_file_access(
            path, operation, self._context
        )
        
        if not allowed:
            # Log denied access
            self._audit_logger.log_denied(operation, path)
            
            raise PolicyViolationError(
                f"Access denied: {operation} on {path}"
            )
        
        # Log allowed access
        self._audit_logger.log_allowed(operation, path)
```

---

## Testing

### Unit Testing

```python
import pytest

@pytest.mark.asyncio
async def test_config_driven_policy():
    """Test ConfigDrivenPolicy backend."""
    config = create_test_policy_config()
    policy = ConfigDrivenPolicy(config)
    
    context = PolicyContext(
        thread_id="test",
        workspace="/tmp/workspace",
        user_id="user123",
        goal="test goal"
    )
    
    # Test allowed path
    allowed = await policy.validate_file_access(
        "/tmp/workspace/file.txt", "read", context
    )
    assert allowed is True
    
    # Test denied path
    allowed = await policy.validate_file_access(
        "/etc/passwd", "read", context
    )
    assert allowed is False
    
    # Test allowed tools
    tools = await policy.get_allowed_tools(context)
    assert "ls" in tools
    assert "execute" not in tools
    
    # Test sandbox config
    sandbox = await policy.get_sandbox_config(context)
    assert sandbox.enabled is True
    assert "/etc" not in sandbox.allowed_paths
```

---

## Configuration Examples

### Basic Configuration

```yaml
protocols:
  policy:
    enabled: true
    backend: config
    sandbox_enabled: true
    timeout: 60
    
    default_tools:
      - ls
      - read_file
      - grep
    
    path_policies:
      - action: allow
        paths: ["${workspace}"]
      - action: deny
        paths: ["/etc", "/usr"]
```

### Advanced Configuration

```yaml
protocols:
  policy:
    enabled: true
    backend: config
    sandbox_enabled: true
    timeout: 300
    
    # Default permissions
    default_tools:
      - ls
      - read_file
      - write_file
      - grep
      - glob
    
    # Path policies
    path_policies:
      # Workspace access
      - action: allow
        paths: ["${workspace}"]
        context: {}
      
      # Deny system paths
      - action: deny
        paths: ["/etc", "/usr", "/bin", "/sbin"]
        context: {}
      
      # Deny sensitive files
      - action: deny
        paths: ["**/.env", "**/secrets.*", "**/.git/**"]
        context: {}
      
      # Allow home for personal
      - action: allow
        paths: ["${HOME}"]
        context:
          tags: ["personal"]
    
    # Tool policies
    tool_policies:
      # Deny execute by default
      - action: deny
        tools: ["execute"]
        context: {}
      
      # Allow execute for trusted
      - action: allow
        tools: ["execute"]
        context:
          tags: ["trusted"]
      
      # All tools for admin
      - action: allow
        tools: ["*"]
        context:
          user_id: ["admin"]
    
    # Command policies
    command_policies:
      - action: allow
        commands: ["ls", "cat", "grep", "find"]
        context: {}
      
      - action: deny
        commands: ["rm", "dd", "mkfs"]
        context: {}
    
    # Network policy
    network_access: false
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
class ConfigDrivenPolicy(PolicyProtocol):
    """PolicyProtocol implementation using configuration."""
    
    def __init__(self, config: PolicyConfig) -> None: ...
    
    async def check_permission(self, action: str, resource: str, context: PolicyContext) -> bool: ...
    async def get_allowed_tools(self, context: PolicyContext) -> list[str]: ...
    async def get_allowed_paths(self, context: PolicyContext) -> list[str]: ...
    async def validate_file_access(self, path: str, operation: str, context: PolicyContext) -> bool: ...
    async def get_sandbox_config(self, context: PolicyContext) -> SandboxConfig: ...
```

---

## See Also

- **[Policy Protocol](../architecture/protocols.md)** - Protocol definition
- **[Protocol Resolver](../core/resolver.md)** - Backend resolution
- **[Workspace Management](../core/workspace.md)** - Workspace security