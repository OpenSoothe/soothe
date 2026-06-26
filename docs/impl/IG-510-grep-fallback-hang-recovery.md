# IG-510: Grep Fallback Hang Recovery

**RFC**: N/A (follows IG-509 incident analysis)
**Created**: 2026-06-26
**Status**: Implemented — Phase 1 (P0) and Phase 2 (P1) complete
**Related**: [IG-509](IG-509-loop-7cba-hang-analysis.md) (root cause analysis), [IG-503](IG-503-file-descriptor-leak-and-network-resilience-fixes.md) (FD pre-flight check)

---

## Executive Summary

Loop `[7cba]` hung because `LocalFilesystem.grep()` fell back to an unbounded Python `os.walk()` when the FD pre-flight check skipped `ag`. The fallback lacked timeout, ignore directories, and resource bounds.

**Implemented Solutions**:

1. **P0 (Grep fix)**: Incremental batching with continuation token pattern
   - Processes files in bounded batches (100 files per batch, max 10 batches)
   - Applies timeout per batch (5s) and total timeout (60s)
   - Skips known large directories (.venv, node_modules, .git, etc.)
   - Returns partial results with continuation token when limits hit
   - Allows agent to request continuation if needed

2. **P1 (General tool timeout)**: `ToolTimeoutMiddleware` wrapping all tool calls
   - Default 60s timeout for standard tools
   - Category-based timeouts (filesystem: 30s, subagents: 180s)
   - Per-tool override configuration
   - Skips tools with robust internal timeout (run_command, execute)
   - Returns ToolMessage with error status on timeout (agent can adapt)

**Auto-Recovery**: Execution never blocks indefinitely. Both tool-level timeouts and middleware-level timeouts ensure bounded execution. Agents receive error messages and can adapt strategy.

---

## Implementation Details

### P0: Grep Incremental Batching

| File | Changes |
|------|---------|
| `protocol.py` | Added `is_partial`, `continuation_token`, `total_files`, `error` to `GrepResult` |
| `local.py` | Replaced `_grep_python_walk()` with `_grep_python_walk_incremental()` |
| `test_grep_search.py` | Added 9 new tests for incremental batching |

### Constants (local.py)

```python
_GREP_BATCH_SIZE: int = 100          # files per batch
_GREP_MAX_BATCHES: int = 10          # stop after this many batches
_GREP_BATCH_TIMEOUT_S: float = 5.0   # timeout per batch
_GREP_MAX_FILE_SIZE_BYTES: int = 1_000_000  # 1 MB per file limit
_GREP_TOTAL_TIMEOUT_S: float = 60.0  # overall grep timeout
_GREP_MAX_TOTAL_BYTES: int = 10 * 1024 * 1024  # 10 MB total read limit
_GREP_IGNORE_DIRS: frozenset[str] = frozenset({
    ".git", ".svn", ".hg",  # VCS
    "__pycache__", ".pytest_cache", ".mypy_cache",  # Python caches
    "node_modules", "bower_components",  # JS deps
    ".venv", "venv", "env", ".env",  # Python virtualenvs
    "dist", "build", ".tox", "*.egg-info",  # Build artifacts
    ".idea", ".vscode",  # IDE/tool dirs
    "target", "out", "bin", "obj",  # Build outputs
})
```

### GrepResult Extended

```python
@dataclass(frozen=True)
class GrepResult:
    matches: list[GrepMatch]
    files_searched: int = 0
    total_matches: int = 0
    truncated: bool = False
    is_partial: bool = False              # NEW: incomplete search
    continuation_token: dict | None = None  # NEW: for resuming
    total_files: int | None = None         # NEW: for progress tracking
    error: str | None = None               # NEW: error message
```

### Auto-Recovery Flow

1. **Grep on large workspace**: Processes first 100 files in 5s batch
2. **Batch limit hit**: Returns `GrepResult(matches=[...], is_partial=True, continuation_token={...})`
3. **Agent receives partial data**: Execution continues, step progresses
4. **Agent decides**: If results insufficient, calls `grep(continuation_token=...)`
5. **Continuation resumes**: Processes next batch from cached file list

---

## Tests Added

| Test | Purpose |
|------|---------|
| `test_grep_ignores_large_directories` | Verify .venv, node_modules, .git skipped |
| `test_grep_ignores_large_files` | Verify files >1MB skipped |
| `test_grep_returns_partial_results_with_continuation_token` | Verify batch limits trigger partial results |
| `test_grep_continuation_token_resumes_search` | Verify continuation resumes from correct offset |
| `test_grep_total_timeout_limits_execution` | Verify max batches limit |
| `test_grep_bytes_limit_stops_reading` | Verify bytes read limit |
| `test_grep_single_file_bypasses_batching` | Verify single files processed directly |
| `test_grep_invalid_regex_returns_error` | Verify error handling for bad regex |
| `test_agrep_continuation_token` | Verify async grep supports continuation |

---

## Phase 2: General Tool Timeout Middleware (P1)

Implemented `ToolTimeoutMiddleware` to wrap all tool invocations with configurable timeouts.

### Files Changed

| File | Changes |
|------|---------|
| `middleware/tool_timeout.py` | New middleware implementing `awrap_tool_call()` with `asyncio.timeout()` |
| `middleware/_builder.py` | Added ToolTimeoutMiddleware to middleware stack (position 8) |
| `config/models.py` | Added `ToolTimeoutConfig` with `enabled`, `default_seconds`, `per_tool` fields |
| `tests/unit/middleware/test_tool_timeout.py` | 16 tests for timeout behavior |

### Configuration

```yaml
agent:
  tool_timeout:
    enabled: true
    default_seconds: 60.0
    per_tool:
      grep: 30.0
      glob: 20.0
      read_file: 30.0
      explore: 180.0
      browser_use: 180.0
    skip_tools_with_internal_timeout: true
```

### Default Category Timeout Values

| Category | Timeout | Tools |
|----------|---------|-------|
| Standard | 60s | Unknown tools |
| Filesystem | 30s | grep, glob, read_file, write_file |
| Execution | 120s | run_command, run_python |
| Subagent | 180s | explore, browser_use, plan, tacitus, *_subagent |

### Timeout Flow

1. Tool invoked via LangGraph ToolNode
2. ToolTimeoutMiddleware.awrap_tool_call() wraps handler
3. `async with asyncio.timeout(tool_timeout_s)` enforces deadline
4. On timeout: returns `ToolMessage(status="error", content="...timed out...")`
5. Agent sees error in ToolMessage, can adapt strategy (narrow scope, try alternative)

### Skip Internal Timeout Tools

Tools like `run_command` already have robust internal timeout via `subprocess.run(timeout=...)`. The middleware skips wrapping these to avoid double-timeout races.

---

## Tests Added (P1)

| Test | Purpose |
|------|---------|
| `test_default_timeout` | Verify default timeout value |
| `test_per_tool_timeout_override` | Verify per-tool override works |
| `test_filesystem_category_timeout` | Verify filesystem tools get 30s |
| `test_subagent_category_timeout` | Verify subagent tools get 180s |
| `test_skip_tools_with_internal_timeout` | Verify run_command skipped |
| `test_async_handler_completes_within_timeout` | Fast tool succeeds |
| `test_async_handler_times_out` | Slow tool returns error |
| `test_skip_internal_timeout_tools` | Skipped tool bypasses wrapper |
| `test_timeout_message_includes_tool_name` | Error message informative |
| `test_multiple_timeouts_counted` | Stats tracking |
| `test_per_tool_timeout_async` | Per-tool config works in async path |

---

## Verification

Run: `./scripts/verify_finally.sh`

Manual verification:
```python
# On soothe repo (>200 files at root, triggers FD skip)
fs = LocalFilesystem(workspace="/Users/chenxm/Workspace/soothe")
result = fs.grep("pattern", output_mode="content")

# Should complete within 60s with partial results, not hang
assert result.is_partial == True  # Search incomplete due to limits
assert result.continuation_token is not None  # Can request more
```

---

## References

- [IG-509](IG-509-loop-7cba-hang-analysis.md) — Original hang analysis
- `packages/soothe/src/soothe/foundation/core/filesystem/local.py` — Incremental batching implementation
- `packages/soothe/src/soothe/foundation/core/filesystem/protocol.py` — Extended GrepResult
- `packages/soothe/tests/core/filesystem/test_grep_search.py` — New tests