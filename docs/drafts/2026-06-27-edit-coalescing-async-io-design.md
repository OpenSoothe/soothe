# Edit Coalescing Middleware + Async I/O

**Status:** Draft
**Date:** 2026-06-27
**Author:** Design Session

---

## Problem Statement

Parallel file edit operations suffer from three issues:

1. **Race conditions** — Multiple concurrent edits to the same file read-modify-write independently, clobbering each other's changes
2. **Middleware overhead** — Each tool call traverses 15+ middleware layers (policy, skill activation, rate limit, concurrency, timeout, etc.), adding significant latency
3. **Event loop blocking** — File I/O operations are synchronous wrappers, blocking the event loop during reads/writes
4. **Redundant reads** — Each edit reads the entire file, even when 10 edits target the same file in one turn

Current throughput ceiling: bounded by ToolConcurrencyMiddleware (5 concurrent tools) and middleware chain traversal per call.

---

## Solution Overview

Implement an **Edit Coalescing Middleware** that:

- Collects incoming edit tool calls within a detection window (50-100ms)
- Groups edits by target file path
- Merges same-file edits into a single batched operation
- Dispatches batched calls through a **fast path** that skips non-essential middleware
- Uses **aiofiles** for true async file I/O, unblocking the event loop

---

## Architecture

```
Tool Calls Arrive
       │
       ▼
┌─────────────────────────────────────┐
│  EditCoalescingMiddleware           │  ← Position ~2-3 in chain
│  - Detection window (50-100ms)      │
│  - Group edits by file path         │
│  - Merge edits (deletions →         │
│    insertions → replacements)       │
│  - Reject overlapping edits         │
└─────────────────────────────────────┘
       │
       ├──────────────────────────────┐
       │                              │
       ▼                              ▼
┌─────────────────────┐    ┌─────────────────────┐
│  Batched Call       │    │  Non-Edit Calls     │
│  (_batched=True)    │    │  (pass through)     │
└─────────────────────┘    └─────────────────────┘
       │                              │
       ▼                              ▼
┌─────────────────────┐    ┌─────────────────────┐
│  Fast Path          │    │  Full Middleware    │
│  - Skip policy      │    │  Chain              │
│  - Skip skill       │    │  (unchanged)        │
│  - Skip rate limit  │    │                     │
│  - Skip concurrency │    │                     │
└─────────────────────┘    └─────────────────────┘
       │                              │
       ▼                              ▼
┌───────────────────────────────────────────────────┐
│  SootheFilesystemMiddleware                       │
│  LocalFilesystem                                  │
│  - aiofiles async I/O (aread, awrite, aedit)      │
│  - edit_batched() for merged operations           │
└───────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────┐
│  Result Mapping                      │
│  - Map batched result to original    │
│    call IDs                          │
│  - Conflict errors to failed edits   │
│  - Success to successful edits       │
└─────────────────────────────────────┘
```

---

## Component Details

### 1. EditCoalescingMiddleware

**Location:** `packages/soothe/src/soothe/middleware/edit_coalescing.py`

**Responsibilities:**

1. **Detection Window:** Collect incoming edit tool calls for 50-100ms before processing
2. **Grouping:** Partition collected edits by target file path
3. **Merging:** For each file group, merge edits into a single `BatchedEdit` operation
4. **Conflict Detection:** Reject edits with overlapping line ranges
5. **Dispatch:** Submit batched calls with `_batched=True` metadata marker
6. **Result Mapping:** After execution, map results back to original call IDs

**Detection Window Implementation:**

```python
class EditCoalescingMiddleware:
    _pending_edits: dict[str, list[PendingEdit]]  # file_path → edits
    _window_task: asyncio.Task | None

    async def awrap_tool_call(self, call: ToolCall, next_handler):
        if not is_edit_tool(call.tool_name):
            return await next_handler(call)

        # Extract file path from tool arguments (path or file_path argument)
        file_path = extract_file_path(call.tool_args)

        # Add to pending queue
        self._pending_edits[file_path].append(PendingEdit(call, next_handler))

        # Start detection window if not running
        if self._window_task is None:
            self._window_task = asyncio.create_task(self._process_after_window())

        # Wait for result (will be filled after batch execution)
        return await call.result_future

    async def _process_after_window(self):
        await asyncio.sleep(0.05)  # 50ms detection window
        await self._dispatch_batched_edits()
        self._window_task = None
```

**Note:** File path is extracted from tool arguments. Edit tools use `path` or `file_path` as their first argument.

**Edit Types Covered:**

- `edit_file_lines` — Replace specific line ranges
- `insert_lines` — Insert content at specific line number
- `delete_lines` — Delete specific line range
- `apply_diff` — Apply unified diff patch (future: merge into batched diff)

---

### 2. Edit Merge Logic

**Order of Operations (per file):**

1. **Deletions first** — Remove lines, shifting subsequent line numbers down
2. **Insertions second** — Add new lines at specified positions
3. **Replacements last** — Apply line replacements in **descending line order** (bottom-to-top preserves line numbers during modification)

**Merge Algorithm:**

```python
def merge_edits(edits: list[EditOperation]) -> BatchedEdit:
    # Tool argument names: path, start, end, line_number, content
    deletions = [e for e in edits if e.tool_name == "delete_lines"]
    insertions = [e for e in edits if e.tool_name == "insert_lines"]
    replacements = [e for e in edits if e.tool_name == "edit_file_lines"]

    # Check overlaps within each category
    if has_overlaps(replacements):
        raise EditConflictError("Overlapping replacement edits detected")

    # Sort replacements by start line descending (bottom-to-top preserves indices)
    replacements.sort(key=lambda e: e.args["start"], reverse=True)

    # Merge deletions into contiguous ranges where possible
    merged_deletions = merge_adjacent_ranges(deletions)

    return BatchedEdit(
        file_path=edits[0].args["path"],
        deletions=merged_deletions,
        insertions=insertions,
        replacements=replacements,
    )
```

**Overlap Detection:**

Two edits overlap if their line ranges intersect:

```python
def ranges_overlap(a: EditOperation, b: EditOperation) -> bool:
    # For edit_file_lines: start/end define the range
    # For delete_lines: start/end define the range
    a_start = a.args.get("start") or a.args.get("line_number", 0)
    a_end = a.args.get("end") or a_start + 1
    b_start = b.args.get("start") or b.args.get("line_number", 0)
    b_end = b.args.get("end") or b_start + 1
    return a_start <= b_end and b_start <= a_end
```

**Conflict Handling:**

When overlaps detected:
- Reject the later-arriving edit with `EditConflictError`
- Include details: conflicting file, line ranges, original edit ID
- Successful edits in the same batch proceed normally

---

### 3. Fast Path Marker

**Mechanism:**

The coalescing middleware adds `call.metadata["_batched"] = True` to batched operations.

Downstream middleware check this marker and skip non-essential work:

| Middleware | Fast Path Behavior |
|------------|-------------------|
| PolicyMiddleware | `if _batched: return await next_handler(call)` — skip policy check |
| SkillActivationMiddleware | Skip skill matching/activation |
| RateLimitMiddleware | Skip rate limit enforcement (batch counts as 1 call) |
| ToolConcurrencyMiddleware | Skip semaphore acquisition (batch controls its own concurrency) |
| ToolTimeoutMiddleware | Apply single timeout for entire batch |

**Implementation Pattern:**

```python
async def awrap_tool_call(self, call: ToolCall, next_handler):
    if call.metadata.get("_batched"):
        return await next_handler(call)  # Fast path
    # Normal middleware logic...
```

---

### 4. Async File I/O (aiofiles)

**Location:** `packages/soothe/src/soothe/foundation/core/filesystem/local.py`

**Change Summary:**

Replace synchronous file operations with `aiofiles`:

| Method | Before | After |
|--------|--------|-------|
| `read()` | `Path.read_text()` | Wrap `aread()` with `asyncio.run()` |
| `write()` | `Path.write_text()` | Wrap `awrite()` with `asyncio.run()` |
| `aread()` | Sync wrapper | `await aiofiles.open(path, mode='r').read()` |
| `awrite()` | Sync wrapper | `await aiofiles.open(path, mode='w').write(content)` |
| `aedit()` | Sync wrapper | True async: `aread()` → modify → `awrite()` |

**Dependency:**

Add to `packages/soothe/pyproject.toml`:

```toml
dependencies = [
    ...,
    "aiofiles>=24.1.0",
]
```

**Implementation:**

```python
class LocalFilesystem(UnifiedFilesystem):
    async def aread(self, path: Path) -> str:
        async with aiofiles.open(path, mode='r') as f:
            return await f.read()

    async def awrite(self, path: Path, content: str) -> None:
        async with aiofiles.open(path, mode='w') as f:
            await f.write(content)

    async def aedit_batched(self, path: Path, batch: BatchedEdit) -> EditResult:
        content = await self.aread(path)
        lines = content.splitlines(keepends=True)

        # Apply deletions (shift line numbers)
        # Apply insertions
        # Apply replacements (descending order)

        new_content = ''.join(lines)
        await self.awrite(path, new_content)
        return EditResult(success=True, lines_modified=len(batch.total_operations()))
```

---

### 5. Result Mapping

After batched execution completes, the coalescing middleware maps results back to original call IDs.

**Success Case:**

```python
for edit in batch.edits:
    edit.original_call.result_future.set_result(
        ToolResult(success=True, output=f"Edit applied to {batch.file_path}")
    )
```

**Partial Failure (Conflict):**

```python
for edit in batch.edits:
    if edit.has_conflict:
        edit.original_call.result_future.set_result(
            ToolResult(success=False, error=EditConflictError(...))
        )
    else:
        edit.original_call.result_future.set_result(
            ToolResult(success=True, ...)
        )
```

---

## Files Modified/Created

| File | Change |
|------|--------|
| `middleware/edit_coalescing.py` | **Create** — Coalescing middleware implementation |
| `middleware/_builder.py` | Insert `EditCoalescingMiddleware` at position 3 |
| `middleware/policy.py` | Add fast-path check for `_batched` marker |
| `middleware/skill_activation.py` | Add fast-path check |
| `middleware/rate_limit.py` | Add fast-path check |
| `middleware/tool_concurrency.py` | Add fast-path check |
| `middleware/tool_timeout.py` | Adjust timeout handling for batched calls |
| `foundation/core/filesystem/local.py` | Convert to aiofiles async I/O, add `aedit_batched()` |
| `foundation/core/filesystem/unified.py` | Add `edit_batched()` to interface |
| `packages/soothe/pyproject.toml` | Add `aiofiles>=24.1.0` dependency |

---

## Out of Scope (Phase 2)

- Backend cache synchronization (`_backend_cache` locking)
- Grep operation optimization (IG-510 already addressed)
- `apply_diff` merging into batched operations (future extension)
- Increasing ToolConcurrencyMiddleware default limit (can tune separately)

---

## Success Criteria

1. **No race conditions** — Parallel edits to same file produce correct merged result or explicit `EditConflictError`
2. **Middleware overhead reduced** — Batched operations skip ~12 middleware layers
3. **Event loop unblocked** — File I/O is async via aiofiles; parallel reads/writes run concurrently
4. **Single read per file** — Merged edits read file once, apply all changes, write once
5. **Throughput improved** — Measure batch edit latency vs N individual edits (target: 50%+ reduction for same-file edits)

---

## Testing Strategy

1. **Unit tests** — `edit_coalescing.py`:
   - Edit grouping by file path
   - Merge logic correctness (deletions, insertions, replacements ordering)
   - Overlap detection and conflict rejection
   - Result mapping to original calls

2. **Unit tests** — `local.py`:
   - aiofiles async read/write correctness
   - `aedit_batched()` applies all edit types correctly

3. **Integration tests**:
   - Parallel edits to different files (verify independent execution)
   - Parallel edits to same file (verify merged result)
   - Overlapping edits (verify conflict error)
   - Measure throughput improvement vs baseline

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Detection window latency adds delay for single edits | Window is 50ms; negligible for typical edit operations. Can tune downward if needed. |
| aiofiles compatibility issues with encoding | aiofiles supports text mode with encoding; match existing behavior. |
| Complex result mapping edge cases | Thorough unit tests for partial failure scenarios. |
| Fast path middleware skip breaks assumptions | Document which middleware are safe to skip and why. Each middleware's fast-path logic is explicit. |

---

## Implementation Sequence

1. Add `aiofiles` dependency
2. Convert `LocalFilesystem` to async I/O
3. Add `aedit_batched()` to interface and implementation
4. Create `EditCoalescingMiddleware`
5. Add fast-path checks to downstream middleware
6. Wire middleware in `_builder.py` at position 3
7. Unit and integration tests
8. Verify with `./scripts/verify_finally.sh`