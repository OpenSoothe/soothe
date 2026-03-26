# RFC-0012: Secure Filesystem Path Handling and Security Policy

**RFC Number**: RFC-0012
**Kind**: Implementation Interface Design
**Status**: Implemented
**Created**: 2026-03-18
**Implemented**: 2026-03-18
**Author**: System
**Design Draft**: [secure-filesystem-path-handling.md](../drafts/secure-filesystem-path-handling.md)
**Implementation Guide**: [secure-filesystem-path-handling.md](../impl-guides/secure-filesystem-path-handling.md)
**Depends On**: RFC-0002 (Policy System)

## Abstract

This RFC proposes a secure filesystem path handling system for Soothe that fixes critical bugs in absolute path resolution and introduces a comprehensive security policy framework for filesystem access control.

## Motivation

### Bug #1: Absolute Path Mishandling

When processing tasks with absolute file paths, the `FilesystemBackend` with `virtual_mode=True` incorrectly treats absolute filesystem paths as virtual paths. The path `/Users/xiamingchen/Workspace/file.md` is converted to `Users/xiamingchen/Workspace/file.md` (leading slash stripped) and joined with the current working directory, creating incorrect nested directory structures.

### Bug #2: Input File Overwrite

The LLM agent incorrectly uses input file paths as output paths, overwriting task description files with generated content.

### Security Gap

The current system lacks comprehensive filesystem security controls, allowing unrestricted access to all files without path-based restrictions or file type validation.

## Specification

### 1. SecureFilesystemBackend Wrapper

Create a new `SecureFilesystemBackend` class in `src/soothe/backends/filesystem_secure.py` that wraps the existing `FilesystemBackend`.

#### 1.1 Path Resolution Algorithm

```python
def _resolve_and_validate_path(file_path: str, operation: str) -> Path:
    """
    Resolution Strategy:
    1. Relative path → Resolve under root_dir
    2. Absolute path under root_dir → Use as-is (after validation)
    3. Absolute path outside root_dir → Require policy approval

    Security Checks:
    - Path blacklist/whitelist matching
    - File type restrictions
    - Workspace boundary enforcement
    """
```

#### 1.2 Integration with PolicyProtocol

The wrapper must integrate with the existing `PolicyProtocol` system:

```python
class SecureFilesystemBackend:
    def __init__(
        self,
        backend: FilesystemBackend,
        root_dir: Path,
        policy: PolicyProtocol | None = None,
        policy_context: PolicyContext | None = None,
        allow_outside_root: bool = False,
    ):
        # Implementation
```

#### 1.3 Normalization for virtual_mode Bug Workaround

Convert absolute paths under root_dir to relative paths before passing to the wrapped backend:

```python
def _normalize_for_backend(file_path: str, operation: str) -> str:
    """
    Workaround for FilesystemBackend virtual_mode bug:
    - If path is under root_dir, convert to relative path
    - If path is outside root_dir, pass as-is (already validated)
    """
```

### 2. Security Policy Configuration

#### 2.1 SecurityConfig Schema

Add to `src/soothe/config.py`:

```python
class SecurityConfig(BaseModel):
    """Security policy configuration for filesystem access control."""

    # Workspace boundary
    allow_paths_outside_workspace: bool = False
    require_approval_for_outside_paths: bool = True

    # Path-based access control
    denied_paths: list[str] = Field(
        default_factory=lambda: [
            "~/.ssh/**",
            "~/.gnupg/**",
            "~/.aws/**",
            "**/.env",
            "**/credentials.json",
            "**/secrets.json",
        ]
    )
    allowed_paths: list[str] = Field(default_factory=lambda: ["**"])

    # File type restrictions
    denied_file_types: list[str] = Field(default_factory=list)
    require_approval_for_file_types: list[str] = Field(
        default_factory=lambda: [".env", ".pem", ".key", ".p12", ".pfx", ".crt"]
    )
```

#### 2.2 Path Evaluation Order

1. **Blacklist Check**: If path matches `denied_paths`, deny immediately
2. **Whitelist Check**: If path matches `allowed_paths`, proceed
3. **Workspace Boundary**: Check if path is within workspace
4. **File Type Check**: Apply file type restrictions
5. **Default**: Deny access

#### 2.3 Pattern Matching

Support glob patterns in path matching:
- `**` - Recursive wildcard
- `*` - Single-level wildcard
- `~` - Home directory expansion
- Exact path matching

### 3. Policy Backend Enhancement

Extend `ConfigDrivenPolicy` in `src/soothe/backends/policy/config_driven.py`:

#### 3.1 Filesystem Permission Checking

```python
def _check_filesystem_permission(
    self,
    action: ActionRequest,
    context: PolicyContext
) -> PolicyDecision:
    """
    Check filesystem access against security config.

    Returns:
        - "allow": Operation proceeds
        - "deny": Operation blocked with error
        - "need_approval": Requires user confirmation
    """
```

#### 3.2 Permission Categories

Leverage existing `Permission` class:
- `fs.read` - Read operations
- `fs.write` - Write operations
- `fs.edit` - Edit operations
- `fs.delete` - Delete operations (future)

### 4. Integration Points

#### 4.1 Agent Creation

Modify `src/soothe/core/agent.py` (lines 147-150):

```python
from soothe.backends.filesystem_secure import SecureFilesystemBackend

base_backend = FilesystemBackend(
    root_dir=resolved_workspace,
    virtual_mode=True,
)
resolved_backend = SecureFilesystemBackend(
    backend=base_backend,
    root_dir=resolved_workspace,
    policy=resolved_policy,
    allow_outside_root=False,
)
```

#### 4.2 Subagent Updates

Apply similar changes to:
- `src/soothe/subagents/planner.py` (lines 117-123)
- `src/soothe/subagents/scout.py` (lines 107-113)

### 5. Error Messages

Provide clear, actionable error messages:

```python
# Example error messages
"Path '/etc/passwd' matches denied pattern '~/.ssh/**'"
"Path '/tmp/test.md' is outside workspace '/Users/user/project'"
"Access to '.env' files requires approval"
"Path '/Users/user/.ssh/id_rsa' is outside workspace. To access paths outside workspace, configure security policy or set allow_outside_root=True"
```

## Implementation Requirements

### File Structure

```
src/soothe/
├── backends/
│   ├── filesystem_secure.py     # NEW: SecureFilesystemBackend
│   └── policy/
│       └── config_driven.py      # MODIFY: Add _check_filesystem_permission
├── config.py                     # MODIFY: Add SecurityConfig
├── core/
│   └── agent.py                  # MODIFY: Wrap backend
└── subagents/
    ├── planner.py                # MODIFY: Wrap backend
    └── scout.py                  # MODIFY: Wrap backend
```

### Test Coverage

1. **Path Resolution Tests**:
   - Relative paths resolve under root
   - Absolute paths under root are used as-is
   - Absolute paths outside root trigger policy check

2. **Security Policy Tests**:
   - Blacklist patterns deny access
   - Whitelist patterns allow access
   - File type restrictions work correctly
   - Workspace boundary enforcement

3. **Integration Tests**:
   - Agent can read/write within workspace
   - Agent cannot access denied paths
   - Policy integration works end-to-end

## Security Considerations

### Defense in Depth

Multiple security layers:
1. Path normalization (prevent directory traversal)
2. Blacklist/whitelist filtering
3. Workspace boundary enforcement
4. File type restrictions
5. Policy approval workflow

### Default Secure Posture

- **Deny by default**: All paths denied unless explicitly allowed
- **Explicit permissions**: Users must opt-in to risky operations
- **Clear audit trail**: All access attempts logged with reasons

### Backward Compatibility

- Existing code continues to work (wrapper is transparent)
- Default configuration is secure but not overly restrictive
- Users can relax restrictions as needed

## Migration Path

1. **Phase 1**: Add `SecureFilesystemBackend` (backward compatible)
2. **Phase 2**: Update agent creation to use wrapper
3. **Phase 3**: Add `SecurityConfig` to configuration
4. **Phase 4**: Enhance policy backend with filesystem checks

## Success Criteria

- [x] Absolute paths under workspace resolve correctly
- [x] Absolute paths outside workspace trigger policy check
- [x] Blacklisted paths are denied
- [x] Whitelisted paths are allowed
- [x] File type restrictions work
- [x] All tests pass
- [x] No breaking changes to existing functionality

## Open Questions

1. Should we add operation-specific path restrictions (different rules for read vs write)?
2. Should we support per-subagent security configurations?
3. Should we add audit logging for all filesystem access attempts?

## References

- Design Draft: [secure-filesystem-path-handling.md](../drafts/secure-filesystem-path-handling.md)
- Policy Protocol: `src/soothe/protocols/policy.py`
- FilesystemBackend: `deepagents.backends.filesystem`
