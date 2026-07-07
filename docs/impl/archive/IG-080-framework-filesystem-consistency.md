# IG-080: Framework Filesystem Consistency

**RFC Reference**: RFC-102 (Extension)
**Implementation Date**: 2026-03-28
**Status**: Draft
**Dependencies**: RFC-102, RFC-001

---

## Overview

This implementation guide extends RFC-102 to cover **framework-level filesystem operations**, ensuring consistent path handling and security across both tool and framework operations.

### Problem Statement

RFC-102 implemented `SecureFilesystemBackend` for **tool operations** only. However, **framework operations** bypass the backend entirely:

- Final report writing (`standalone.py:237`)
- Artifact store (checkpoints, manifests, reports)
- Daemon PID files
- Skill creation scripts
- Weaver agent generation
- Other internal operations

This creates inconsistencies:
1. **Security gap**: Framework operations don't respect `virtual_mode` or security policies
2. **Path resolution differences**: Tools use backend, framework uses direct pathlib
3. **Workaround complexity**: `SecureFilesystemBackend` adds unnecessary path conversion logic

### Root Cause Analysis

From deepagents FilesystemBackend source (`thirdparty/deepagents/.../filesystem.py`):

```python
def _resolve_path(self, key: str) -> Path:
    if self.virtual_mode:
        # Treat ALL paths as virtual paths under root_dir
        vpath = key if key.startswith("/") else "/" + key
        if ".." in vpath or vpath.startswith("~"):
            raise ValueError("Path traversal not allowed")
        full = (self.cwd / vpath.lstrip("/")).resolve()
        full.relative_to(self.cwd)  # Verify stays within root
        return full

    # virtual_mode=False: Absolute paths used as-is
    path = Path(key)
    if path.is_absolute():
        return path  # ← Absolute paths bypass root_dir
    return (self.cwd / path).resolve()
```

**Key insight**: This is **intentional design**, not a bug:
- `virtual_mode=True`: For backend-agnostic virtual path semantics (CompositeBackend routing) and optional sandboxing
- `virtual_mode=False`: For direct filesystem access with absolute path support

The current `SecureFilesystemBackend._normalize_for_backend()` method converts absolute paths to relative paths. While this works, it adds complexity and doesn't address framework operations that bypass the backend entirely.

---

## Solution Design

### Strategy: Single Backend, No Wrapper, Framework-Wide Access

**Goal**: Use deepagents `FilesystemBackend` directly throughout the framework without manual path conversion workarounds.

**Approach**:
1. Create `FrameworkFilesystem` singleton for framework-wide access
2. Understand and document `virtual_mode` semantics correctly (not as a "bug")
3. Replace all direct `pathlib` operations with backend calls
4. Remove `SecureFilesystemBackend` wrapper (no longer needed)

### Virtual Mode Semantics Documentation

**Critical**: Document the correct behavior, not as a "bug":

```python
# virtual_mode=True (allow_paths_outside_workspace=False)
# Purpose: Virtual path semantics, sandboxed to root_dir
backend = FilesystemBackend(root_dir="/workspace", virtual_mode=True)

backend.write("file.md", "content")       # → /workspace/file.md
backend.write("/docs/file.md", "content") # → /workspace/docs/file.md (VIRTUAL PATH!)
backend.write("/etc/passwd", "content")   # → /workspace/etc/passwd (sandboxed!)

# virtual_mode=False (allow_paths_outside_workspace=True)
# Purpose: Direct filesystem access, absolute paths allowed
backend = FilesystemBackend(root_dir="/workspace", virtual_mode=False)

backend.write("file.md", "content")       # → /workspace/file.md
backend.write("/docs/file.md", "content") # → /docs/file.md (REAL ABSOLUTE PATH!)
backend.write("/etc/passwd", "content")   # → /etc/passwd (real filesystem path!)
```

For Soothe:
- **Default** (`allow_paths_outside_workspace=False`): Use `virtual_mode=True` + policy for outside access
- **Opt-in** (`allow_paths_outside_workspace=True`): Use `virtual_mode=False` + policy for access control

---

## Implementation Plan

### Phase 1: Framework Filesystem Singleton

**File**: `src/soothe/core/filesystem.py` (NEW)

```python
"""Framework-wide filesystem backend singleton."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from deepagents.backends.filesystem import FilesystemBackend

if TYPE_CHECKING:
    from soothe.config import SootheConfig
    from soothe.protocols.policy import PolicyContext, PolicyProtocol


class FrameworkFilesystem:
    """Singleton filesystem backend for all framework operations.

    Provides consistent path resolution and security across:
    - Tool operations (via middleware)
    - Framework operations (reports, checkpoints, manifests)
    - CLI operations (final reports, health checks)

    Uses deepagents FilesystemBackend directly with proper virtual_mode semantics.
    No wrapper or path conversion workarounds needed.
    """

    _instance: FilesystemBackend | None = None
    _root_dir: Path | None = None
    _policy: PolicyProtocol | None = None

    @classmethod
    def initialize(
        cls,
        config: SootheConfig,
        policy: PolicyProtocol | None = None,
    ) -> FilesystemBackend:
        """Initialize the singleton filesystem backend.

        Args:
            config: Soothe configuration.
            policy: Optional security policy for access control.

        Returns:
            Initialized FilesystemBackend instance.
        """
        from soothe.utils import expand_path

        resolved_workspace = expand_path(config.workspace_dir)

        # virtual_mode semantics (documented clearly, not as a "bug"):
        # - True: All paths treated as virtual under root_dir (sandboxed)
        #         Paths like "/etc/passwd" become "{root}/etc/passwd"
        # - False: Absolute paths used as-is, relative paths resolve under root
        #          Paths like "/etc/passwd" write to real /etc/passwd
        virtual_mode = not config.security.allow_paths_outside_workspace

        cls._instance = FilesystemBackend(
            root_dir=resolved_workspace,
            virtual_mode=virtual_mode,
            max_file_size_mb=config.execution.max_file_size_mb if hasattr(config.execution, 'max_file_size_mb') else 10,
        )
        cls._root_dir = resolved_workspace
        cls._policy = policy

        return cls._instance

    @classmethod
    def get(cls) -> FilesystemBackend:
        """Get the singleton filesystem backend.

        Returns:
            FilesystemBackend instance.

        Raises:
            RuntimeError: If backend not initialized.
        """
        if cls._instance is None:
            raise RuntimeError(
                "FrameworkFilesystem not initialized. Call initialize() first."
            )
        return cls._instance

    @classmethod
    def check_policy(
        cls,
        file_path: str,
        operation: str,
        policy_context: PolicyContext | None = None,
    ) -> None:
        """Check security policy for a file operation.

        This provides an additional security layer for paths outside workspace
        when virtual_mode=False (allow_paths_outside_workspace=True).

        Args:
            file_path: File path to check.
            operation: Operation type ("read", "write", "edit").
            policy_context: Optional policy context.

        Raises:
            ValueError: If access denied by policy.
        """
        if cls._policy is None or policy_context is None:
            return

        # Get the resolved path from backend
        backend = cls.get()
        resolved = backend._resolve_path(file_path)

        # Check if path is outside workspace
        try:
            resolved.relative_to(cls._root_dir)
            # Under workspace - no policy check needed (backend handles it)
        except ValueError:
            # Outside workspace - check policy
            from soothe.protocols.policy import ActionRequest

            action = ActionRequest(
                action_type="tool_call",
                tool_name=f"fs_{operation}",
                tool_args={"file_path": str(resolved)},
            )
            decision = cls._policy.check(action, policy_context)
            if decision.verdict == "deny":
                raise ValueError(
                    f"Access denied: Path '{resolved}' is outside workspace. "
                    f"Reason: {decision.reason}"
                ) from None
```

### Phase 2: Update Agent Factory

**File**: `src/soothe/core/agent.py`

**Remove** lines 236-250 (SecureFilesystemBackend wrapper).

**Replace with**:

```python
from soothe.core.filesystem import FrameworkFilesystem

# Initialize framework-wide singleton
backend = FrameworkFilesystem.initialize(
    config=config,
    policy=resolved_policy,
)
resolved_backend = backend  # Use directly, no wrapper
```

### Phase 3: Replace Direct Pathlib Operations

#### 3.1 Final Report Writing

**File**: `src/soothe/ux/cli/execution/standalone.py`

**Current** (lines 226-254):
```python
def _output_final_report(report_text: str, workspace_path: str, ...) -> None:
    if len(report_text) < display_threshold:
        sys.stdout.write(report_text)
    else:
        reports_dir = Path(workspace_path) / ".soothe" / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        report_path = reports_dir / f"report_{timestamp}.md"
        report_path.write_text(report_text, encoding="utf-8")  # ← Direct operation
```

**New**:
```python
def _output_final_report(report_text: str, workspace_path: str, ...) -> None:
    if len(report_text) < display_threshold:
        sys.stdout.write(report_text)
    else:
        from soothe.core.filesystem import FrameworkFilesystem

        backend = FrameworkFilesystem.get()

        # In virtual_mode=True: ".soothe/reports/report.md" becomes virtual path
        # In virtual_mode=False: Relative path resolves under workspace
        report_path = f".soothe/reports/report_{timestamp}.md"

        result = backend.write(report_path, report_text)

        if result.error:
            # Fallback to temp file
            import tempfile
            with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
                f.write(report_text)
                sys.stdout.write(f"\n\n[Report saved to: {f.name}]\n")
        else:
            # Show user the resolved path
            actual_path = backend._resolve_path(report_path)
            sys.stdout.write(f"\n\n[Report: {len(report_text):,} chars → saved to: {actual_path}]\n")
```

#### 3.2 Artifact Store Operations

**File**: `src/soothe/core/artifact_store.py`

**Pattern**: Replace all `Path.write_text()` with backend calls.

**Example** (line 168):
```python
# Current
(step_dir / "report.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")

# New
from soothe.core.filesystem import FrameworkFilesystem

backend = FrameworkFilesystem.get()

# Convert to relative path from run_dir
step_report_path = str((step_dir / "report.json").relative_to(self._run_dir))
backend.write(step_report_path, report.model_dump_json(indent=2))
```

**Note**: For atomic writes (checkpoint tmp+rename), keep the pattern but use backend:
```python
# Atomic checkpoint write
tmp_path = "checkpoint.json.tmp"
backend.write(tmp_path, json.dumps(envelope, default=str, indent=2))
# Rename atomically (still need pathlib for rename)
(backend._resolve_path(tmp_path)).rename(backend._resolve_path("checkpoint.json"))
```

#### 3.3 Other Framework Operations

Apply similar changes to:
- `src/soothe/daemon/singleton.py:16` (PID file)
- `src/soothe/ux/cli/commands/health_cmd.py:90` (health report)
- `src/soothe/ux/cli/commands/config_cmd.py:165` (minimal config)
- `src/soothe/subagents/weaver/generator.py` (agent generation)
- `src/soothe/tools/_internal/document.py:246` (cache writing)
- `src/soothe/tools/audio/implementation.py:139` (audio cache)
- `src/soothe/tools/_internal/wizsearch/_helpers.py:120` (search results)
- `src/soothe/backends/persistence/json_store.py:36` (JSON persistence)
- `src/soothe/backends/memory/memu/memory/file_manager.py` (memory files)

### Phase 4: Remove SecureFilesystemBackend

**Delete**: `src/soothe/backends/filesystem_secure.py`

**Update imports** in:
- `src/soothe/core/agent.py`
- Any other files that import it

### Phase 5: Update Configuration Documentation

**File**: `src/soothe/config/models.py`

**Update docstring**:

```python
allow_paths_outside_workspace: bool = False
"""Allow access to paths outside the workspace directory.

When False (default):
    - Sets virtual_mode=True for FilesystemBackend
    - All paths treated as virtual under workspace root
    - Example: "/etc/passwd" becomes "{workspace}/etc/passwd" (sandboxed)
    - Security enforced by backend's path containment

When True:
    - Sets virtual_mode=False for FilesystemBackend
    - Absolute paths used as-is (can access any filesystem path)
    - Example: "/etc/passwd" writes to real "/etc/passwd"
    - Security enforced by PolicyProtocol only

Note: virtual_mode is for path semantics (virtual paths vs real paths),
      not security. Use PolicyProtocol for access control regardless of this setting.
      See deepagents.backends.filesystem for details.
"""
```

---

## Testing Strategy

### Unit Tests

1. **Virtual mode path resolution**:
   ```python
   def test_virtual_mode_true_sandbox():
       backend = FilesystemBackend(root_dir="/workspace", virtual_mode=True)
       backend.write("/etc/passwd", "fake")
       # Should write to /workspace/etc/passwd, not /etc/passwd
       assert Path("/workspace/etc/passwd").exists()

   def test_virtual_mode_false_absolute():
       backend = FilesystemBackend(root_dir="/workspace", virtual_mode=False)
       # Should be able to write to absolute paths outside workspace
       result = backend.write("/tmp/test.md", "content")
       assert Path("/tmp/test.md").exists()
   ```

2. **Framework operations use backend**:
   ```python
   def test_final_report_uses_backend():
       # Mock the backend
       with patch('soothe.core.filesystem.FrameworkFilesystem.get') as mock_get:
           mock_backend = Mock()
           mock_get.return_value = mock_backend

           _output_final_report("large report...", "/workspace")

           # Verify backend.write was called, not Path.write_text
           mock_backend.write.assert_called_once()
   ```

3. **Policy integration**:
   ```python
   def test_policy_check_for_outside_paths():
       # When virtual_mode=False and path outside workspace
       backend = FrameworkFilesystem.initialize(
           config=Config(allow_paths_outside_workspace=True),
           policy=mock_policy
       )

       # Should trigger policy check
       with pytest.raises(ValueError, match="Access denied"):
           FrameworkFilesystem.check_policy("/etc/passwd", "write", context)
   ```

### Integration Tests

1. **End-to-end autonomous run**:
   - Run autonomous mode with large report
   - Verify report written via backend
   - Check path matches virtual_mode setting

2. **Backward compatibility**:
   - Existing configs work without changes
   - Paths resolve correctly for both virtual_mode settings
   - Security policies still enforced

---

## Migration Path

### Step-by-Step Rollout

1. **Add FrameworkFilesystem singleton** (Phase 1)
   - New module, initialize in agent factory
   - Keep SecureFilesystemBackend temporarily

2. **Replace framework operations** (Phase 3)
   - Start with final report (most visible)
   - Then artifact store (critical for durability)
   - Then daemon and CLI commands
   - Finally skills and tool internals

3. **Remove SecureFilesystemBackend** (Phase 4)
   - Once all operations use FrameworkFilesystem
   - Verify all tests pass
   - Delete `filesystem_secure.py`

4. **Update documentation** (Phase 5)
   - Document virtual_mode semantics clearly
   - Update RFC-102 to reflect extension
   - Add migration guide for users

---

## Success Criteria

- [ ] All framework operations use FilesystemBackend (no direct pathlib)
- [ ] virtual_mode semantics documented correctly (not as "bug")
- [ ] SecureFilesystemBackend removed (no wrapper needed)
- [ ] Tests pass (unit + integration)
- [ ] No regression in existing functionality
- [ ] Configuration migration not required (backward compatible)

---

## Benefits

### Security
- **Consistent sandboxing**: All operations respect virtual_mode
- **No bypass vectors**: Direct pathlib operations eliminated
- **Clear semantics**: Users understand virtual_mode behavior

### Architecture
- **Single backend**: No wrapper workaround
- **Clean inheritance**: Use deepagents as designed
- **Framework-wide access**: Singleton ensures consistency

### Maintainability
- **Less code**: Remove SecureFilesystemBackend workaround
- **Clear patterns**: All file operations use same backend
- **Easier debugging**: Path resolution centralized

---

## References

- **RFC-102**: Secure Filesystem Path Handling and Security Policy
- **deepagents FilesystemBackend**: `thirdparty/deepagents/libs/deepagents/deepagents/backends/filesystem.py`
- **Current workaround**: `src/soothe/backends/filesystem_secure.py` (to be removed)
- **Agent factory**: `src/soothe/core/agent.py`
- **Final report**: `src/soothe/ux/cli/execution/standalone.py`
- **Artifact store**: `src/soothe/core/artifact_store.py`

---

## Appendix: Path Resolution Examples

### virtual_mode=True (Default, Secure)

```python
backend = FilesystemBackend(root_dir="/Users/alice/project", virtual_mode=True)

# Relative path
backend.write("docs/readme.md", "content")
# → /Users/alice/project/docs/readme.md

# "Absolute" path (treated as virtual!)
backend.write("/etc/passwd", "fake")
# → /Users/alice/project/etc/passwd (sandboxed!)

# Path traversal blocked
backend.read("/../secret.key")
# → ValueError: Path traversal not allowed
```

### virtual_mode=False (Opt-in, Direct Access)

```python
backend = FilesystemBackend(root_dir="/Users/alice/project", virtual_mode=False)

# Relative path
backend.write("docs/readme.md", "content")
# → /Users/alice/project/docs/readme.md

# Absolute path (real filesystem path!)
backend.write("/etc/passwd", "content")
# → /etc/passwd (real system file!)

# Path traversal allowed
backend.read("../secret.key")
# → /Users/alice/secret.key (escapes workspace!)
```

### Policy Integration

Regardless of virtual_mode, add policy checks for defense in depth:

```python
# Check policy before operation
FrameworkFilesystem.check_policy(file_path, "write", policy_context)
backend.write(file_path, content)
```

---

**End of Implementation Guide**