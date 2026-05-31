# Security Layer

Comprehensive security framework for path validation, policy enforcement, and access control.

## Overview

The security layer provides defense-in-depth protection against path traversal attacks,
symlink escapes, and unauthorized filesystem access. It consists of three main components:

1. **PathValidator** - Low-level path validation with traversal detection
2. **SecurityPolicy** - Configurable policy rules for access control
3. **SecurityEnforcer** - High-level enforcement with audit logging and rate limiting

## Quick Start

```python
from soothe.core.security import SecurityEnforcer
from soothe.core.security.policy import STRICT_POLICY

# Create enforcer with strict policy
enforcer = SecurityEnforcer(
    workspace="/safe/workspace",
    policy=STRICT_POLICY,
)

# Check access
decision = enforcer.check_access("../etc/passwd", "read")
if decision.is_denied:
    print(f"Access denied: {decision.reason}")

# Get safe path (raises SecurityError if denied)
try:
    safe_path = enforcer.get_safe_path("config.json", "read")
    with open(safe_path) as f:
        data = f.read()
except SecurityError as e:
    print(f"Security violation: {e}")
```

## Components

### PathValidator

Low-level path validation with comprehensive security checks:

```python
from soothe.core.security import PathValidator

validator = PathValidator(
    workspace="/safe/workspace",
    allow_absolute=False,
    allow_home_expansion=False,
    follow_symlinks=False,
)

result = validator.validate("../etc/passwd")
if not result.is_valid:
    print(f"Blocked: {result.violation_type}")
```

**Validation Checks:**
- Path traversal patterns (`..`, `../`, `..\`)
- URL-encoded traversal (`%2e%2e%2f`)
- Null byte injection (`\x00`)
- Control characters
- Suspicious unicode ranges
- Dangerous path components (`.`, `..`, `.git`)
- Blocked system paths (`/etc`, `/bin`, etc.)
- Workspace boundary violations
- Symlink escapes
- Path length limits
- Component count limits

### SecurityPolicy

Configurable policy rules for access control:

```python
from soothe.core.security.policy import SecurityPolicy, PolicyAction

policy = SecurityPolicy(
    name="custom",
    allow_absolute=False,
    allow_traversal=False,
    blocked_extensions={".exe", ".dll", ".sh"},
    blocked_patterns={"*.secret", "*.key"},
    blocked_paths={"/etc", "/root"},
    allowed_operations={"read", "ls", "glob"},
    on_violation=PolicyAction.DENY,
)

decision = policy.evaluate("../secret.key", "read")
```

**Policy Features:**
- Operation whitelisting
- Path pattern blocking
- Extension blocking
- Read-only paths
- No-delete paths
- Rate limiting configuration
- Custom validators

### SecurityEnforcer

High-level enforcement with comprehensive logging:

```python
from soothe.core.security import SecurityEnforcer
from soothe.core.security.policy import STRICT_POLICY

enforcer = SecurityEnforcer(
    workspace="/safe/workspace",
    policy=STRICT_POLICY,
    enable_audit_log=True,
    enable_rate_limiting=True,
)

# Check access
decision = enforcer.check_access(path, operation)

# Get safe path
safe_path = enforcer.get_safe_path(path, operation)

# Get audit log
recent_violations = enforcer.get_violations(since=time.time() - 3600)

# Get statistics
stats = enforcer.get_stats()
```

## Predefined Policies

| Policy | Description | Use Case |
|--------|-------------|----------|
| `STRICT_POLICY` | Maximum security | Production, untrusted input |
| `PERMISSIVE_POLICY` | Allows more operations | Development, trusted environments |
| `READONLY_POLICY` | Read-only access | Log viewing, reporting |
| `SANDBOX_POLICY` | Strict sandbox | Running untrusted code |

```python
from soothe.core.security.policy import (
    STRICT_POLICY,
    PERMISSIVE_POLICY,
    READONLY_POLICY,
    SANDBOX_POLICY,
)
```

## Integration

### With FilesystemBackend

```python
from soothe.core.security.integration import SecureFilesystemWrapper
from deepagents.backends.filesystem import FilesystemBackend

backend = FilesystemBackend("/workspace")
secure_backend = SecureFilesystemWrapper(
    backend,
    workspace="/workspace",
    policy=STRICT_POLICY,
)

# All operations are now validated
secure_backend.read("../etc/passwd")  # Raises SecurityError
```

### As Decorator

```python
from soothe.core.security.integration import secure_operation

@secure_operation("read")
def read_config(path: str) -> dict:
    import json
    with open(path) as f:
        return json.load(f)

# Automatically validated
config = read_config("../secret.json")  # Raises SecurityError
```

### Context Manager

```python
from soothe.core.security.enforcement import SecurityContext

with SecurityContext(enforcer, PERMISSIVE_POLICY):
    # Temporarily use permissive policy
    result = enforcer.check_access("/allowed/path", "read")
# Policy automatically restored
```

## Security Checks

### Path Traversal Detection

```python
# All these are detected and blocked:
"../etc/passwd"
"..\\Windows\\System32"
"foo/../../etc/passwd"
"%2e%2e%2fetc%2fpasswd"  # URL-encoded
"....//....//etc/passwd"  # Double encoding
```

### Symlink Protection

```python
validator = PathValidator(
    workspace="/workspace",
    follow_symlinks=False,  # Default: don't follow symlinks
)

# Detects symlinks pointing outside workspace
result = validator.validate("symlink_to_outside")
if result.violation_type == "symlink_escape":
    print("Symlink escape detected!")
```

### Rate Limiting

```python
enforcer = SecurityEnforcer(
    workspace="/workspace",
    policy=STRICT_POLICY.with_restrictions(
        max_operations_per_minute=100,
    ),
    enable_rate_limiting=True,
)

# Automatically rate-limited
for i in range(200):
    decision = enforcer.check_access(f"file{i}.txt", "read")
    if decision.violation_type == "rate_limit_exceeded":
        break
```

## Audit Logging

```python
enforcer = SecurityEnforcer(
    workspace="/workspace",
    enable_audit_log=True,
)

# Operations are automatically logged
enforcer.check_access("test.txt", "read")

# Query audit log
recent = enforcer.get_audit_log(since=time.time() - 3600)
violations = enforcer.get_violations()

# Get statistics
stats = enforcer.get_stats()
print(f"Blocked: {stats['blocked_operations']}")
```

## Testing

```python
import pytest
from soothe.core.security import PathValidator

@pytest.fixture
def validator():
    return PathValidator(
        workspace="/tmp/test",
        allow_absolute=False,
    )

def test_traversal_blocked(validator):
    result = validator.validate("../etc/passwd")
    assert result.is_valid is False
    assert "traversal" in result.violation_type
```

## Best Practices

1. **Always use strict validation for untrusted input**
   ```python
   validator = create_strict_validator(workspace)
   ```

2. **Enable audit logging in production**
   ```python
   enforcer = SecurityEnforcer(..., enable_audit_log=True)
   ```

3. **Use rate limiting for public-facing APIs**
   ```python
   enforcer = SecurityEnforcer(..., enable_rate_limiting=True)
   ```

4. **Never disable security in production**
   ```python
   # Don't do this:
   enforcer._disable_security()
   ```

5. **Validate paths before any filesystem operation**
   ```python
   decision = enforcer.check_access(path, operation)
   if decision.is_denied:
       return error_response
   # Only then access filesystem
   ```

## Architecture

```
┌─────────────────────────────────────────┐
│         SecurityEnforcer                │
│  ┌─────────────────────────────────┐   │
│  │      SecurityPolicy             │   │
│  │  ┌─────────────────────────┐   │   │
│  │  │     PathValidator       │   │   │
│  │  │  - Traversal detection  │   │   │
│  │  │  - Pattern matching       │   │   │
│  │  │  - Boundary checks        │   │   │
│  │  └─────────────────────────┘   │   │
│  │  - Operation rules            │   │
│  │  - Path restrictions          │   │
│  │  - Rate limits                │   │
│  └─────────────────────────────────┘   │
│  - Audit logging                        │
│  - Violation callbacks                  │
│  - Statistics                           │
└─────────────────────────────────────────┘
```

## License

MIT License - See LICENSE file for details.
