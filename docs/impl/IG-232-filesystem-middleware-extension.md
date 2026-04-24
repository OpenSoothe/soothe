# Implementation Guide: IG-232 - SootheFilesystemMiddleware Extension

**Number**: IG-232
**Title**: Filesystem Middleware Extension - Surgical File Operations
**Status**: Draft
**Created**: 2026-04-24
**Design**: docs/drafts/2026-04-24-filesystem-middleware-extension-design.md
**Related RFCs**: N/A (implementation-driven)

## Overview

Extend deepagents' `FilesystemMiddleware` to provide surgical file manipulation tools (delete_file, file_info, edit_file_lines, insert_lines, delete_lines, apply_diff) with backup support, following deepagents' implementation patterns and integrating with Soothe's configuration system.

## Implementation Scope

### Primary Deliverables

1. **SootheFilesystemMiddleware class** - Extends FilesystemMiddleware
2. **Tool schemas** - 6 schema classes following deepagents pattern
3. **Tool creation methods** - 6 methods implementing surgical tools
4. **Configuration integration** - FilesystemMiddlewareConfig in SootheConfig
5. **Plugin integration** - file_ops plugin wraps middleware
6. **Unit tests** - tests/unit/middleware/test_filesystem.py

### Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `src/soothe/middleware/filesystem.py` | **CREATE** | SootheFilesystemMiddleware + schemas + tool descriptions |
| `src/soothe/middleware/__init__.py` | **UPDATE** | Export SootheFilesystemMiddleware |
| `src/soothe/config/models.py` | **UPDATE** | Add FilesystemMiddlewareConfig |
| `src/soothe/toolkits/file_ops.py` | **UPDATE** | Wrap middleware for backward compatibility |
| `tests/unit/middleware/test_filesystem.py` | **CREATE** | Unit tests following Soothe pattern |

## Implementation Steps

### Step 1: Create Middleware Module with Schemas

**File**: `src/soothe/middleware/filesystem.py`

**Structure**:
```python
# 1. Module imports (deepagents patterns)
from deepagents.backends.filesystem import FilesystemBackend
from deepagents.backends.utils import validate_path
from deepagents.middleware.filesystem import FilesystemMiddleware
from langchain.tools import ToolRuntime
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

# 2. Tool schemas (module level, BaseModel)
class DeleteFileSchema(BaseModel):
    file_path: str = Field(description="...")

class FileInfoSchema(BaseModel):
    path: str = Field(description="...")

# ... 4 more schemas

# 3. Tool descriptions (constants)
DELETE_FILE_TOOL_DESCRIPTION = """..."""
FILE_INFO_TOOL_DESCRIPTION = """..."""

# ... 4 more descriptions

# 4. Middleware class
class SootheFilesystemMiddleware(FilesystemMiddleware):
    def __init__(self, *, backup_enabled=True, backup_dir=None, workspace_root=None, **kwargs):
        super().__init__(**kwargs)
        # Store config
        # Extend tools

    def _create_delete_file_tool(self) -> BaseTool:
        # Implementation

    # ... 5 more tool creation methods
```

**Key patterns**:
- All schemas at module level (not inside class)
- All descriptions as constants (not inline)
- Schema uses `Field(description="...")` for all parameters
- Tool creation returns `StructuredTool.from_function(infer_schema=False, args_schema=XxxSchema)`

### Step 2: Implement Tool Creation Methods

Each tool follows this exact pattern:

**Pattern**:
```python
def _create_xxx_tool(self) -> BaseTool:
    """Create the xxx tool."""

    def sync_xxx(
        runtime: ToolRuntime,
        param1: Annotated[str, "..."],
        param2: Annotated[int, "..."],
    ) -> str:
        """Synchronous wrapper."""
        backend = self._get_backend(runtime)
        try:
            validated_path = validate_path(file_path)
        except ValueError as e:
            return f"Error: {e}"

        # Implementation logic
        # Use backend.read/write/edit or direct Path operations
        # Return result string

    async def async_xxx(runtime, param1, param2) -> str:
        """Asynchronous wrapper."""
        backend = self._get_backend(runtime)
        validated_path = validate_path(file_path)

        # Use backend.aread/awrite/aedit
        # Return result string

    return StructuredTool.from_function(
        name="xxx",
        description=XXX_TOOL_DESCRIPTION,
        func=sync_xxx,
        coroutine=async_xxx,
        infer_schema=False,
        args_schema=XxxSchema,
    )
```

**Critical requirements**:
1. First parameter: `runtime: ToolRuntime` (not in schema, injected)
2. Use `validate_path()` for all file paths
3. Use `self._get_backend(runtime)` for backend access
4. Implement both sync and async versions
5. Backend operations: `backend.read/write/edit` (use async versions in async)
6. Direct operations: `Path.unlink(), Path.stat(), subprocess.run()` (with validate_path)

### Step 3: Implement delete_file Tool

**Logic**:
1. `validate_path(file_path)` → `Path(validated_path)`
2. Check `exists()` and `is_file()`
3. If `backup_enabled`:
   - Create `.backups/` dir (or custom `backup_dir`)
   - Timestamp: `{stem}_{datetime.now(UTC).strftime("%Y%m%d_%H%M%S")}{suffix}`
   - `shutil.copy2(file, backup_path)`
4. `Path.unlink()` to delete
5. Return message: `f"Deleted: {file_path} (backup: {backup_name})"`

**No backend usage** (delete not in BackendProtocol)

### Step 4: Implement file_info Tool

**Logic**:
1. `validate_path(path)` → `Path(validated_path)`
2. Check `exists()`
3. `Path.stat()` → `st_size, st_mtime, st_atime`
4. Format timestamps: `datetime.fromtimestamp(st.st_mtime, tz=UTC).strftime("%Y-%m-%d %H:%M:%S")`
5. Return formatted string with path, size, timestamps, is_file/is_dir

**No backend usage** (metadata not in BackendProtocol)

### Step 5: Implement edit_file_lines Tool

**Logic**:
1. `validate_path(file_path)`
2. `backend.read(file_path, offset=0, limit=10000)` → get content
3. `content.splitlines(keepends=True)` → list of lines
4. Validate `start_line` (1-indexed, 1 to total_lines) and `end_line` (>= start_line, <= total_lines)
5. `new_content.splitlines(keepends=True)` → new_lines (add `\n` to last if missing)
6. `lines[start_line-1:end_line] = new_lines` (replace)
7. `modified_content = "".join(lines)`
8. `backend.write(file_path, modified_content)` (if error, use `backend.edit` with original vs modified)

**Backend usage**: `backend.read()` (or `backend.aread()`), `backend.write()` (or `backend.awrite()`)

**Line indexing**: 1-indexed, inclusive range

### Step 6: Implement insert_lines Tool

**Logic**:
1. `validate_path(file_path)`
2. `backend.read(file_path)` → content
3. `content.splitlines(keepends=True)` → lines
4. Validate `line` (1-indexed, 1 to total_lines+1)
5. `content.splitlines(keepends=True)` → new_lines
6. `lines[line-1:line-1] = new_lines` (slice insertion)
7. `modified_content = "".join(lines)`
8. `backend.write(file_path, modified_content)`

**Backend usage**: Same as edit_file_lines

### Step 7: Implement delete_lines Tool

**Logic**:
1-3: Same as edit_file_lines
4. Validate `start_line` and `end_line`
5. `del lines[start_line-1:end_line]`
6-8: Same as edit_file_lines

**Backend usage**: Same as edit_file_lines

### Step 8: Implement apply_diff Tool

**Logic**:
1. `validate_path(file_path)`
2. Check file exists
3. Create temp file: `tempfile.NamedTemporaryFile(mode="w", suffix=".patch", delete=False)`
4. Write diff content to temp file
5. `subprocess.run(["patch", "-p0", "-i", patch_path, file_path], timeout=10, check=False)`
6. Check returncode (0 = success)
7. `Path(patch_path).unlink()` cleanup
8. Return result message

**No backend usage** (patch uses subprocess)

### Step 9: Update Middleware __init__.py

**File**: `src/soothe/middleware/__init__.py`

**Add**:
```python
from soothe.middleware.filesystem import SootheFilesystemMiddleware

__all__ = [
    # ... existing exports
    "SootheFilesystemMiddleware",
]
```

### Step 10: Add FilesystemMiddlewareConfig

**File**: `src/soothe/config/models.py`

**Add after existing configs**:
```python
class FilesystemMiddlewareConfig(BaseModel):
    """Configuration for SootheFilesystemMiddleware."""

    backup_enabled: bool = True
    backup_dir: str | None = None
    workspace_root: str | None = None
    virtual_mode: bool = False
    max_file_size_mb: int = 10
    tool_token_limit_before_evict: int | None = 20000
```

**Add to SootheConfig**:
```python
filesystem_middleware: FilesystemMiddlewareConfig = Field(
    default_factory=FilesystemMiddlewareConfig
)
```

### Step 11: Update file_ops Plugin

**File**: `src/soothe/toolkits/file_ops.py`

**Replace implementation**:
```python
@plugin(name="file_ops", version="2.0.0", trust_level="built-in")
class FileOpsPlugin:
    def __init__(self):
        self._tools: list[BaseTool] = []

    async def on_load(self, context):
        from soothe.middleware.filesystem import SootheFilesystemMiddleware
        from deepagents.backends.filesystem import FilesystemBackend

        workspace_root = context.config.get("workspace_root", "")
        fs_config = context.config.get("filesystem_middleware", {})

        backend = FilesystemBackend(
            root_dir=workspace_root,
            virtual_mode=fs_config.virtual_mode,
            max_file_size_mb=fs_config.max_file_size_mb,
        )

        middleware = SootheFilesystemMiddleware(
            backend=backend,
            backup_enabled=fs_config.backup_enabled,
            backup_dir=fs_config.backup_dir,
            workspace_root=workspace_root,
            tool_token_limit_before_evict=fs_config.tool_token_limit_before_evict,
        )

        # Extract surgical tools only
        surgical_names = [
            "delete_file", "file_info", "edit_file_lines",
            "insert_lines", "delete_lines", "apply_diff",
        ]

        self._tools = [t for t in middleware.tools if t.name in surgical_names]

        context.logger.info(
            "Loaded %d file_ops tools via SootheFilesystemMiddleware",
            len(self._tools),
        )

    def get_tools(self) -> list[BaseTool]:
        return self._tools
```

### Step 12: Create Unit Tests

**File**: `tests/unit/middleware/test_filesystem.py`

**Test categories**:
```python
class TestSootheFilesystemMiddleware:
    """Unit tests for SootheFilesystemMiddleware."""

    def test_delete_file_with_backup(self, tmp_path):
        # Test backup creation

    def test_delete_file_without_backup(self, tmp_path):
        # Test no backup

    def test_backup_file_naming(self, tmp_path):
        # Test timestamp format

    def test_file_info(self, tmp_path):
        # Test metadata retrieval

    def test_edit_file_lines(self, tmp_path):
        # Test line replacement

    def test_insert_lines(self, tmp_path):
        # Test insertion at various positions

    def test_delete_lines(self, tmp_path):
        # Test line deletion

    def test_apply_diff(self, tmp_path):
        # Test patch application

    def test_inherits_deepagents_tools(self):
        # Verify all inherited tools present

    def test_tool_schema_validation(self):
        # Verify all tools have args_schema
```

**Key test patterns**:
- Use `tmp_path` fixture from pytest
- Create `ToolRuntime` mock for tool invocation
- Test both success and error cases
- Verify backup file naming (timestamp format)
- Verify schema validation (args_schema is BaseModel)

## Verification Checklist

Before declaring completion:

1. ✅ All 6 tool schemas defined (BaseModel, Field descriptions)
2. ✅ All 6 tool descriptions defined (constants)
3. ✅ All 6 tool creation methods implemented (sync + async)
4. ✅ All tools use `validate_path()` before operations
5. ✅ Backend tools use `backend.read/write/edit`
6. ✅ Direct tools use Path operations with validation
7. ✅ SootheFilesystemMiddleware inherits FilesystemMiddleware
8. ✅ Middleware exports updated
9. ✅ FilesystemMiddlewareConfig added to models.py
10. ✅ file_ops plugin wraps middleware
11. ✅ Unit tests created in tests/unit/middleware/
12. ✅ All tests pass: `./scripts/verify_finally.sh`
13. ✅ No linting errors: `make lint`
14. ✅ Backward compatibility verified (file_ops API unchanged)

## Success Criteria (from Design Draft)

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

## Dependencies

**From deepagents**:
- `deepagents.middleware.filesystem.FilesystemMiddleware`
- `deepagents.backends.filesystem.FilesystemBackend`
- `deepagents.backends.utils.validate_path`
- `langchain.tools.ToolRuntime`
- `langchain_core.tools.BaseTool, StructuredTool`

**From Soothe**:
- Existing config system (`SootheConfig`)
- Plugin infrastructure (`@plugin` decorator)
- Test organization pattern (`tests/unit/<module>/`)

## Implementation Notes

**Pattern compliance is critical**:
- Do NOT skip `infer_schema=False` in StructuredTool.from_function
- Do NOT inline tool descriptions (use constants)
- Do NOT place schemas inside class (module level)
- Do NOT skip validate_path() (security requirement)
- Do NOT use backend for delete/info/patch (no methods available)

**Line indexing convention**:
- All line-based tools: 1-indexed (first line is 1)
- Ranges are inclusive (start_line to end_line both included)
- Slice operations: `lines[start-1:end]` (Python 0-indexed slices)

**Backup naming**:
- Format: `{original_stem}_{YYYYMMDD_HHMMSS}.{extension}`
- Example: `myfile_20260424_143022.txt`
- Timezone: UTC (not local)

**Error handling**:
- `validate_path()` raises ValueError → catch and return error string
- Backend operations return error in result → check and return error string
- File operations → check exists/is_file before operations

## Estimated Complexity

**Moderate** (5-7 implementation steps):
- Schema creation: Low (straightforward pattern)
- Tool implementations: Medium (backend pattern + direct operations)
- Configuration: Low (add model)
- Plugin integration: Low (wrap middleware)
- Testing: Medium (7+ test methods)

**Total estimated time**: 2-3 hours

---

**Status**: Draft - Ready for implementation