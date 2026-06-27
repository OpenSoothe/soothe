# IG-517: Edit Coalescing Middleware + Async I/O

**IG**: 517
**Title**: Edit Coalescing Middleware + Async File I/O
**Status**: Implemented
**Created**: 2026-06-27
**Design**: `docs/drafts/2026-06-27-edit-coalescing-async-io-design.md`
**Dependencies**: RFC-101 (Tool Interface), RFC-211 (Tool Result Optimization)

---

## Summary

Implement edit coalescing middleware to:
- Eliminate race conditions for parallel same-file edits
- Reduce middleware overhead via fast-path for batched operations
- Unblock event loop with aiofiles async I/O
- Reduce redundant file reads through edit merging

---

## Scope

| In Scope | Out of Scope |
|----------|--------------|
| EditCoalescingMiddleware (new) | Backend cache synchronization |
| aiofiles integration in LocalFilesystem | Grep optimization (IG-510) |
| Fast-path marker in downstream middleware | `apply_diff` batch merging |
| `edit_batched()` method | ToolConcurrency limit tuning |

---

## Files

| File | Action |
|------|--------|
| `middleware/edit_coalescing.py` | **Create** |
| `middleware/_builder.py` | **Modify** — insert middleware at position 3 |
| `middleware/policy.py` | **Modify** — add fast-path check |
| `middleware/skill_activation.py` | **Modify** — add fast-path check |
| `middleware/rate_limit.py` | **Modify** — add fast-path check |
| `middleware/tool_concurrency.py` | **Modify** — add fast-path check |
| `middleware/tool_timeout.py` | **Modify** — adjust for batched timeout |
| `foundation/core/filesystem/local.py` | **Modify** — aiofiles + `aedit_batched()` |
| `foundation/core/filesystem/unified.py` | **Modify** — add `edit_batched()` interface |
| `packages/soothe/pyproject.toml` | **Modify** — add aiofiles dependency |

---

## Implementation Sequence

1. Add `aiofiles>=24.1.0` dependency
2. Convert `LocalFilesystem` to true async I/O with aiofiles
3. Add `aedit_batched()` method to interface and implementation
4. Create `EditCoalescingMiddleware` with detection window, grouping, merging
5. Add fast-path `_batched` marker checks to downstream middleware
6. Wire middleware in `_builder.py` at position 3
7. Unit tests for coalescing logic
8. Integration tests for parallel edit scenarios
9. Run `./scripts/verify_finally.sh`

---

## Key Classes

### EditCoalescingMiddleware

```python
class EditCoalescingMiddleware(SootheMiddleware):
    """Coalesces parallel edits to same file into batched operations."""

    _pending_edits: dict[str, list[PendingEdit]]
    _window_task: asyncio.Task | None
    _window_ms: int = 50

    async def awrap_tool_call(self, call, next_handler):
        # Non-edit tools pass through
        # Edit tools collected, grouped by file, merged after window
        # Batched calls dispatched with _batched=True marker
```

### BatchedEdit

```python
class BatchedEdit(BaseModel):
    file_path: str
    deletions: list[DeleteOperation]
    insertions: list[InsertOperation]
    replacements: list[ReplaceOperation]  # sorted descending by line

    def total_operations(self) -> int: ...
```

### EditConflictError

```python
class EditConflictError(Exception):
    """Raised when edits have overlapping line ranges."""
    file_path: str
    conflicting_ranges: list[tuple[int, int]]
    edit_ids: list[str]
```

---

## Fast Path Middleware

Each downstream middleware adds:

```python
async def awrap_tool_call(self, call, next_handler):
    if call.metadata.get("_batched"):
        return await next_handler(call)  # Skip normal logic
    # ... existing middleware logic ...
```

---

## Testing

1. **Unit**: edit grouping, merge order, overlap detection, result mapping
2. **Integration**: parallel edits (different files, same file, overlapping)
3. **Performance**: measure batch latency vs N individual edits

---

## Success Criteria

1. Parallel same-file edits produce merged result or explicit conflict error
2. Batched ops skip ~12 middleware layers
3. Event loop unblocked during file I/O
4. Single read/write per file for merged edits
5. All tests pass (`./scripts/verify_finally.sh`)

---

## References

- Design: `docs/drafts/2026-06-27-edit-coalescing-async-io-design.md`
- RFC-101: Tool Interface
- RFC-211: Tool Result Optimization