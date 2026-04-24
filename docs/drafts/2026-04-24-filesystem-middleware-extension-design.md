# Design Draft: SootheFilesystemMiddleware - Surgical File Operations

**Date**: 2026-04-24
**Status**: Draft
**Author**: Claude Code
**Related**: soothe-filesystem-middleware-implementation-plan.md

## Abstract

Extend deepagents' `FilesystemMiddleware` to provide surgical file manipulation tools (delete_file, file_info, edit_file_lines, insert_lines, delete_lines, apply_diff) with backup support, following deepagents' implementation patterns and integrating with Soothe's configuration system.

## Problem Statement

### Current State

The Soothe file_ops toolkit provides 6 surgical file manipulation tools:
- `delete_file` (with optional backup)
- `file_info` (metadata retrieval)
- `edit_file_lines` (line-based replacement)
- `insert_lines` (insert at specific line)
- `delete_lines` (delete line ranges)
- `apply_diff` (unified diff patches)

deepagents' `FilesystemMiddleware` provides standard filesystem tools (ls, read_file, write_file, edit_file, glob, grep, execute) with:
- Proper tool schema validation (XxxSchema pattern)
- ToolRuntime injection for backend access
- Path validation with `validate_path()`
- Backend abstraction (BackendProtocol)
- Large result eviction
- System prompt injection

### Issues

1. **Separate toolkits**: file_ops exists as standalone plugin, separate from FilesystemMiddleware
2. **Duplicate configuration**: workspace_root, backup settings configured separately
3. **Inconsistent patterns**: file_ops uses direct filesystem access, not deepagents patterns
4. **No unified management**: Two separate filesystem tool collections

### Impact

- Configuration complexity (two sets of filesystem settings)
- Inconsistent tool implementation patterns
- Missed opportunity to leverage FilesystemMiddleware backend architecture
- Duplicate path resolution logic

## Proposed Solution

### Core Concept

Create `SootheFilesystemMiddleware` inheriting from `FilesystemMiddleware`:

```
FilesystemMiddleware (deepagents)
├── Tools: ls, read_file, write_file, edit_file, glob, grep, execute
├── Backend: BackendProtocol
├── Schemas: XxxSchema(BaseModel)
├── Runtime: ToolRuntime
├── Validation: validate_path()
└── Eviction: Large result handling
    ↓ (inheritance)
SootheFilesystemMiddleware
├── Inherits: All above
├── Adds: delete_file, file_info, edit_file_lines, insert_lines, delete_lines, apply_diff
├── Config: Backup settings, workspace_root
└── Patterns: Follows deepagents implementation patterns exactly
```

### Key Design Principles

1. **Inheritance, not duplication**: Extend FilesystemMiddleware, don't reimplement
2. **Pattern consistency**: Follow deepagents patterns exactly (schemas, ToolRuntime, validate_path)
3. **Backend delegation**: Use FilesystemBackend methods (read, write, edit) for operations
4. **Configuration integration**: FilesystemMiddlewareConfig in Soothe settings
5. **Backward compatibility**: file_ops plugin wraps middleware for compatibility

## Design Details

### Architecture

#### Middleware Extension

```python
class SootheFilesystemMiddleware(FilesystemMiddleware):
    """Extended filesystem middleware with surgical file operations."""

    def __init__(
        self,
        *,
        backup_enabled: bool = True,
        backup_dir: str | None = None,
        workspace_root: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._backup_enabled = backup_enabled
        self._backup_dir = backup_dir
        self._workspace_root = workspace_root

        # Add surgical tools following deepagents pattern
        self.tools.extend([
            self._create_delete_file_tool(),
            self._create_file_info_tool(),
            self._create_edit_file_lines_tool(),
            self._create_insert_lines_tool(),
            self._create_delete_lines_tool(),
            self._create_apply_diff_tool(),
        ])
```

#### Tool Schema Pattern

Each tool uses deepagents pattern:

```python
# Schema at module level
class DeleteFileSchema(BaseModel):
    """Input schema for delete_file tool."""
    file_path: str = Field(description="...")

# Tool creation method
def _create_delete_file_tool(self) -> BaseTool:
    def sync_delete_file(
        runtime: ToolRuntime,
        file_path: Annotated[str, "..."],
    ) -> str:
        resolved_backend = self._get_backend(runtime)
        validated_path = validate_path(file_path)
        # Use backend or direct Path operations

    return StructuredTool.from_function(
        name="delete_file",
        description=DELETE_FILE_TOOL_DESCRIPTION,
        func=sync_delete_file,
        coroutine=async_delete_file,
        infer_schema=False,  # Required pattern
        args_schema=DeleteFileSchema,
    )
```

### Implementation Patterns (from deepagents)

#### Pattern 1: Schema Validation
- All tools have `XxxSchema(BaseModel)` at module level
- Field descriptions for all parameters
- Tool creation uses `args_schema=XxxSchema`
- Always `infer_schema=False`

#### Pattern 2: Runtime Injection
- First parameter: `runtime: ToolRuntime`
- Backend access: `self._get_backend(runtime)`
- Path validation: `validate_path(file_path)` before use
- Tool call ID from runtime for ToolMessage

#### Pattern 3: Backend Usage
- Read files: `backend.read(path, offset, limit)`
- Write files: `backend.write(path, content)` (new files)
- Edit files: `backend.edit(path, old_string, new_string)` (existing files)
- List files: `backend.ls(path)`
- Search: `backend.grep(pattern, path, glob)`
- Find: `backend.glob(pattern, path)`

#### Pattern 4: Sync + Async Pair
- Implement sync version: `sync_xxx(runtime, ...)`
- Implement async version: `async_xxx(runtime, ...)`
- Async delegates to backend async methods
- Return to StructuredTool.from_function with both

### Tool Implementations

#### delete_file

**Operation**: Delete file with optional backup

**Implementation**:
```python
1. validate_path(file_path)
2. Check file exists and is_file()
3. If backup_enabled:
   - Create .backups/ directory (or custom backup_dir)
   - Generate timestamped backup name: {stem}_{YYYYMMDD_HHMMSS}.{suffix}
   - shutil.copy2(file, backup_path)
4. Path.unlink() to delete
5. Return message with backup path if created
```

**Backend usage**: None (direct filesystem operation for delete)

**Backup naming**: `{original_stem}_{20260424_143022}.{extension}`

#### file_info

**Operation**: Get file metadata (size, mtime, atime, is_file, is_dir)

**Implementation**:
```python
1. validate_path(path)
2. Check path exists
3. Path.stat() for metadata
4. Format timestamps: datetime.fromtimestamp(st.st_mtime, tz=UTC)
5. Return formatted info string
```

**Backend usage**: None (direct filesystem metadata retrieval)

#### edit_file_lines

**Operation**: Replace specific line range (1-indexed, inclusive)

**Implementation**:
```python
1. validate_path(file_path)
2. backend.read(file_path, offset=0, limit=10000) to get all lines
3. Split content into lines (keepends=True)
4. Validate start_line and end_line (1-indexed, within bounds)
5. Prepare new_lines from new_content (add \n to last if needed)
6. Replace: lines[start_line-1:end_line] = new_lines
7. Join lines back to content
8. backend.write(file_path, modified_content) (or backend.edit for existing)
```

**Backend usage**: `backend.read()` for reading, `backend.write()` or `backend.edit()` for writing

**Line indexing**: 1-indexed (first line is 1), inclusive range

#### insert_lines

**Operation**: Insert content at specific line number (1-indexed)

**Implementation**:
```python
1. validate_path(file_path)
2. backend.read(file_path) to get all lines
3. Validate line number (1 to total_lines+1)
4. Prepare new_lines from content
5. Insert: lines[line-1:line-1] = new_lines (slice assignment)
6. backend.write(file_path, modified_content)
```

**Backend usage**: `backend.read()`, `backend.write()`

**Edge cases**: Can insert at beginning (line=1), end (line=total_lines+1)

#### delete_lines

**Operation**: Delete specific line range (1-indexed, inclusive)

**Implementation**:
```python
1. validate_path(file_path)
2. backend.read(file_path)
3. Validate start_line and end_line
4. Delete: del lines[start_line-1:end_line]
5. backend.write(file_path, modified_content)
```

**Backend usage**: `backend.read()`, `backend.write()`

#### apply_diff

**Operation**: Apply unified diff patch using `patch` command

**Implementation**:
```python
1. validate_path(file_path)
2. Create temp .patch file with diff content
3. subprocess.run(["patch", "-p0", "-i", patch_path, file_path], timeout=10)
4. Check returncode, handle errors
5. Clean up temp file
6. Return success/error message
```

**Backend usage**: None (uses subprocess for patch command)

**Timeout**: 10 seconds

### Configuration

#### FilesystemMiddlewareConfig

```python
class FilesystemMiddlewareConfig(BaseModel):
    backup_enabled: bool = True
    backup_dir: str | None = None
    workspace_root: str | None = None
    virtual_mode: bool = False  # Passed to FilesystemBackend
    max_file_size_mb: int = 10  # Passed to FilesystemBackend
    tool_token_limit_before_evict: int | None = 20000  # Inherited
```

Integration in SootheConfig:
```python
filesystem_middleware: FilesystemMiddlewareConfig = Field(default_factory=FilesystemMiddlewareConfig)
```

### file_ops Plugin Integration

**Strategy**: Wrap middleware for backward compatibility

```python
@plugin(name="file_ops", version="2.0.0")
class FileOpsPlugin:
    async def on_load(self, context):
        # Create middleware
        middleware = SootheFilesystemMiddleware(
            backend=FilesystemBackend(root_dir=workspace_root, ...),
            backup_enabled=fs_config.backup_enabled,
            ...
        )

        # Extract surgical tools only (not ls, read_file, etc.)
        surgical_tools = [t for t in middleware.tools
                         if t.name in ["delete_file", "file_info", ...]]
        self._tools = surgical_tools
```

**Benefits**:
- Backward compatibility (plugin API unchanged)
- Unified middleware implementation
- Tools from single source

### Test Organization

Following Soothe pattern: `tests/unit/middleware/test_filesystem.py`

Test categories:
1. Tool creation (schema validation, infer_schema=False)
2. delete_file (backup enabled/disabled, naming)
3. file_info (metadata retrieval)
4. edit_file_lines (line replacement)
5. insert_lines (insertion positions)
6. delete_lines (line deletion)
7. apply_diff (patch application)
8. Inheritance verification (has all FilesystemMiddleware tools)

### File Structure

```
packages/soothe/
├── src/soothe/
│   ├── middleware/
│   │   ├── filesystem.py              # NEW: SootheFilesystemMiddleware + schemas
│   │   └── __init__.py                # UPDATE: export
│   ├── toolkits/
│   │   └── file_ops.py                # UPDATE: wrap middleware
│   └── config/
│       └── models.py                  # UPDATE: FilesystemMiddlewareConfig
└── tests/unit/middleware/
    └── test_filesystem.py             # NEW: unit tests
```

## Dependencies

- deepagents.middleware.filesystem.FilesystemMiddleware
- deepagents.backends.filesystem.FilesystemBackend
- deepagents.backends.utils.validate_path
- langchain.tools.ToolRuntime
- langchain_core.tools.BaseTool, StructuredTool
- pydantic.BaseModel, Field

## Constraints

1. Must follow deepagents tool implementation patterns exactly
2. Must inherit from FilesystemMiddleware (not duplicate)
3. Must use backend methods where applicable (read, write, edit)
4. Must maintain backward compatibility with file_ops plugin
5. Tests must follow Soothe organization pattern

## Risks

1. **Pattern deviation**: If implementation doesn't follow deepagents patterns, loses consistency
   - **Mitigation**: Strict adherence to schema, ToolRuntime, validate_path patterns

2. **Backend method limitations**: Some operations (delete, metadata, patch) not in backend
   - **Mitigation**: Use direct filesystem operations with validate_path security

3. **Breaking changes**: file_ops plugin users expect current tool API
   - **Mitigation**: Plugin wraps middleware, maintains same tool interface

4. **Performance**: backend.read() for large files in edit_file_lines
   - **Mitigation**: Use pagination (limit parameter), consider chunked reading

## Alternatives Considered

### Alternative 1: Create standalone backend (SootheFilesystemBackend)
- **Pros**: Complete control, protocol abstraction
- **Cons**: Duplicate FilesystemBackend functionality, doesn't leverage deepagents
- **Rejected**: Violates "extend, don't duplicate" principle

### Alternative 2: Replace file_ops entirely with middleware
- **Pros**: Single tool collection
- **Cons**: Breaking change for file_ops users, loses plugin modularity
- **Rejected**: Backward compatibility requirement

### Alternative 3: Keep file_ops separate, no middleware
- **Pros**: Minimal change
- **Cons**: Duplicate patterns, missed architecture benefits
- **Rejected**: Doesn't solve the stated problems

## Success Criteria

1. ✅ SootheFilesystemMiddleware inherits from FilesystemMiddleware
2. ✅ All 6 surgical tools implemented with deepagents patterns
3. ✅ Tool schemas follow XxxSchema(BaseModel) pattern
4. ✅ All tools use validate_path() before operations
5. ✅ Backend methods used for read/write/edit operations
6. ✅ file_ops plugin wraps middleware successfully
7. ✅ Tests pass in tests/unit/middleware/
8. ✅ Backward compatibility maintained (same tool API)
9. ✅ Configuration integrated (FilesystemMiddlewareConfig)
10. ✅ All tests pass with ./scripts/verify_finally.sh

## Questions

1. Should edit_file_lines use backend.edit() or backend.write() for existing files?
   - **Answer**: backend.write() errors on existing files, so use backend.edit() after reading original content

2. Should backup files be stored relative to workspace_root or absolute?
   - **Answer**: Relative to deleted file's parent (or custom backup_dir), not workspace_root

3. How to handle workspace resolution (RFC-103) in middleware?
   - **Answer**: Backend's root_dir set to workspace_root, backend handles resolution

## Next Steps

Phase 2 (Implementation):
1. Create tool schemas (DeleteFileSchema, FileInfoSchema, etc.)
2. Implement SootheFilesystemMiddleware class
3. Implement each tool creation method following patterns
4. Add FilesystemMiddlewareConfig to models.py
5. Update file_ops plugin to wrap middleware
6. Write unit tests in tests/unit/middleware/
7. Run verification and ensure all tests pass

---

**Draft Status**: This design captures the architectural approach and implementation patterns. Ready for refinement into RFC specification.