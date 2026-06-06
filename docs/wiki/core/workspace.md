# Workspace Management

Unified workspace resolution, validation, and backend management.

---

## Overview

The workspace module (`soothe.core.workspace`) provides unified workspace resolution and validation for Soothe. It manages workspace-aware backends, the FrameworkFilesystem singleton, and workspace resolution for daemon and runner.

---

## Architecture

### Workspace System Components

```
Workspace Management Architecture
├─ Workspace Resolution
│  ├─ Daemon workspace validation
│  ├─ Client workspace validation
│  ├─ Stream workspace resolution
│  └─ Workspace path normalization
│
├─ Workspace Validation
│  ├─ Path validation
│  ├─ Permission checks
│  ├─ Existence verification
│  └─ Security validation
│
├─ Workspace-Aware Backends
│  ├─ Backend wrapper
│  ├─ Workspace context injection
│  └─ Isolated workspace operations
│
└─ FrameworkFilesystem
   ├─ Singleton instance
   ├─ Unified filesystem operations
   ├─ Policy enforcement
   └─ Audit logging
```

---

## Core Components

### FrameworkFilesystem

Singleton filesystem backend for Soothe:

```python
class FrameworkFilesystem:
    """Singleton filesystem backend for Soothe.
    
    Provides unified filesystem operations with:
    - Policy enforcement
    - Audit logging
    - Rate limiting
    - Workspace isolation
    """
    
    # Singleton instance
    _instance: FrameworkFilesystem | None = None
    
    def __new__(cls):
        """Singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    async def read_file(self, path: str) -> str:
        """Read file with policy enforcement."""
        
    async def write_file(self, path: str, content: str):
        """Write file with policy enforcement."""
        
    async def list_directory(self, path: str) -> list[str]:
        """List directory with validation."""
    
    async def glob(self, pattern: str) -> list[str]:
        """Glob pattern with validation."""
```

---

## Workspace Resolution

### Daemon Workspace Resolution

Resolve workspace for daemon server:

```python
def resolve_daemon_workspace(
    workspace_dir: str | None,
    config: SootheConfig
) -> str:
    """Resolve workspace for daemon.
    
    Args:
        workspace_dir: Explicit workspace directory
        config: Soothe configuration
        
    Returns:
        Resolved workspace path
        
    Raises:
        WorkspaceValidationError: If workspace invalid
    """
```

### Stream Workspace Resolution

Resolve workspace for runner stream:

```python
def resolve_workspace_for_stream(
    stream_id: str,
    config: SootheConfig
) -> str:
    """Resolve workspace for stream.
    
    Args:
        stream_id: Stream identifier
        config: Soothe configuration
        
    Returns:
        Resolved workspace path
    """
```

---

## Workspace Validation

### Path Validation

Validate workspace path:

```python
def validate_workspace_path(path: str) -> bool:
    """Validate workspace path.
    
    Checks:
    - Path exists
    - Is directory
    - Readable
    - Writable (if required)
    
    Args:
        path: Workspace path
        
    Returns:
        True if valid
        
    Raises:
        WorkspaceValidationError: If invalid
    """
```

### Security Validation

Validate workspace security:

```python
def validate_workspace_security(path: str, policy: PolicyProtocol):
    """Validate workspace against security policy.
    
    Checks:
    - Path allowed by policy
    - No forbidden patterns
    - Appropriate permissions
    
    Args:
        path: Workspace path
        policy: Security policy
        
    Raises:
        PolicyViolationError: If policy violation
    """
```

---

## Workspace-Aware Backend

### Backend Wrapper

Wrap backends with workspace context:

```python
class WorkspaceAwareBackend:
    """Workspace-aware backend wrapper.
    
    Wraps any backend to inject workspace context
    and enforce workspace isolation.
    """
    
    def __init__(self, backend: Any, workspace: str):
        """Initialize with backend and workspace."""
        self.backend = backend
        self.workspace = workspace
    
    async def operation(self, *args, **kwargs):
        """Execute operation with workspace context."""
        
        # Inject workspace context
        kwargs["workspace"] = self.workspace
        
        # Validate workspace
        validate_workspace_path(self.workspace)
        
        # Execute backend operation
        return await self.backend.operation(*args, **kwargs)
```

---

## Workspace Isolation

### Thread Isolation

Isolate workspace per thread:

```python
def isolate_workspace_for_thread(
    base_workspace: str,
    thread_id: str
) -> str:
    """Isolate workspace for thread.
    
    Creates thread-specific workspace directory
    within base workspace.
    
    Args:
        base_workspace: Base workspace path
        thread_id: Thread identifier
        
    Returns:
        Thread-isolated workspace path
    """
```

### Goal Isolation

Isolate workspace per goal:

```python
def isolate_workspace_for_goal(
    base_workspace: str,
    goal_id: str
) -> str:
    """Isolate workspace for goal.
    
    Args:
        base_workspace: Base workspace path
        goal_id: Goal identifier
        
    Returns:
        Goal-isolated workspace path
    """
```

---

## Policy Enforcement

### Filesystem Policy

Enforce filesystem policy:

```python
class FilesystemPolicy:
    """Filesystem policy enforcement."""
    
    def __init__(self, policy: PolicyProtocol):
        """Initialize with policy."""
        self.policy = policy
    
    def check_read(self, path: str) -> bool:
        """Check if read allowed."""
        return self.policy.allow_read(path)
    
    def check_write(self, path: str) -> bool:
        """Check if write allowed."""
        return self.policy.allow_write(path)
    
    def check_execute(self, path: str) -> bool:
        """Check if execute allowed."""
        return self.policy.allow_execute(path)
```

### Audit Logging

Log filesystem operations:

```python
class AuditLogger:
    """Filesystem audit logging."""
    
    def log_read(self, path: str, result: str):
        """Log read operation."""
        
    def log_write(self, path: str, content_size: int):
        """Log write operation."""
        
    def log_execute(self, path: str, result: str):
        """Log execute operation."""
```

---

## Rate Limiting

### Filesystem Rate Limiting

Limit filesystem operation rate:

```python
class RateLimiter:
    """Filesystem rate limiter."""
    
    def __init__(self, max_ops: int, window: int):
        """Initialize rate limiter."""
        self.max_ops = max_ops
        self.window = window
    
    async def acquire(self):
        """Acquire rate limit permit."""
        await self.wait_for_permit()
    
    async def release(self):
        """Release rate limit permit."""
```

---

## Usage Patterns

### Basic Workspace Resolution

```python
from soothe.core.workspace import resolve_daemon_workspace
from soothe.config import SootheConfig

config = SootheConfig.from_file("config.yml")

# Resolve daemon workspace
workspace = resolve_daemon_workspace(
    workspace_dir=None,  # Use config default
    config=config
)
print(workspace)  # "/path/to/workspace"
```

### FrameworkFilesystem Usage

```python
from soothe.core.workspace import FrameworkFilesystem

# Get singleton instance
fs = FrameworkFilesystem()

# Read file
content = await fs.read_file("/path/to/file")

# Write file
await fs.write_file("/path/to/file", "content")

# List directory
files = await fs.list_directory("/path/to/dir")
```

### Workspace-Aware Backend

```python
from soothe.core.workspace import WorkspaceAwareBackend

# Wrap backend with workspace
backend = WorkspaceAwareBackend(
    backend=my_backend,
    workspace="/path/to/workspace"
)

# Execute operation with workspace context
result = await backend.operation()
```

---

## Configuration

### Workspace Settings

```yaml
workspace:
  dir: "."                # Workspace directory
  isolation: thread       # Isolation mode (thread/goal/none)
  validate: true          # Validate workspace
  
  policy:
    read: true            # Allow read operations
    write: true           # Allow write operations
    execute: true         # Allow execute operations
  
  rate_limit:
    max_ops: 100          # Max operations per window
    window: 60            # Window in seconds
```

---

## Error Handling

### Workspace Validation Errors

Handle validation failures:

```python
try:
    workspace = resolve_daemon_workspace(workspace_dir, config)
except WorkspaceValidationError as e:
    logger.error(f"Workspace validation failed: {e}")
    # Fallback or exit
```

### Policy Violations

Handle policy violations:

```python
try:
    await fs.write_file("/restricted/path", "content")
except PolicyViolationError as e:
    logger.error(f"Policy violation: {e}")
    # Handle violation
```

---

## Related Documentation

- **[Agent Factory](agent-factory.md)** - Workspace integration
- **[SootheRunner](runner.md)** - Runner workspace handling
- **[Security Policy](../architecture/security-policy.md)** - Policy details
- **[RFC-102](../../specs/RFC-102-security-filesystem-policy.md)** - Security policy spec
- **[RFC-103](../../specs/RFC-103-thread-aware-workspace.md)** - Thread workspace spec

---

## API Reference

### Core Functions

```python
def resolve_daemon_workspace(
    workspace_dir: str | None,
    config: SootheConfig
) -> str: ...

def resolve_workspace_for_stream(
    stream_id: str,
    config: SootheConfig
) -> str: ...

def validate_workspace_path(path: str) -> bool: ...
def validate_workspace_security(path: str, policy: PolicyProtocol): ...

def isolate_workspace_for_thread(base_workspace: str, thread_id: str) -> str: ...
def isolate_workspace_for_goal(base_workspace: str, goal_id: str) -> str: ...
```

### FrameworkFilesystem Class

```python
class FrameworkFilesystem:
    """Singleton filesystem backend."""
    
    async def read_file(self, path: str) -> str: ...
    async def write_file(self, path: str, content: str): ...
    async def list_directory(self, path: str) -> list[str]: ...
    async def glob(self, pattern: str) -> list[str]: ...
    async def delete_file(self, path: str): ...
    async def file_info(self, path: str) -> FileInfo: ...
```

### WorkspaceAwareBackend Class

```python
class WorkspaceAwareBackend:
    """Workspace-aware backend wrapper."""
    
    def __init__(self, backend: Any, workspace: str): ...
    
    async def operation(self, *args, **kwargs): ...
```

---

## See Also

- **[Security Policy](../architecture/security-policy.md)** - Policy enforcement
- **[Thread Management](../user-guide/thread-management.md)** - Thread handling
- **[Filesystem Backend](../modules/backends/filesystem.md)** - Backend details