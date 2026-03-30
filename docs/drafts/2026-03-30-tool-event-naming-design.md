# Tool Event Naming Unification - Design Draft

**Date**: 2026-03-30
**Status**: Draft
**Scope**: Rename `backup_created` → `backup` to align with atomic verb pattern

---

## Problem

The `file_ops` tool events use inconsistent naming:
- Atomic operations: `read`, `write`, `delete` (simple verbs)
- Async operations: `search_started`, `search_completed` (lifecycle triplet)
- One outlier: `backup_created` (past-tense adjective)

The `backup_created` naming doesn't fit the atomic verb pattern used by other atomic file operations.

---

## Solution

Rename `backup_created` → `backup` to match the atomic verb pattern.

### Pattern Definition

| Operation Type | Naming Pattern | Examples |
|----------------|----------------|----------|
| Atomic (single-shot) | Simple verb | `read`, `write`, `delete`, `backup` |
| Async (lifecycle) | `*_started`, `*_completed`, `*_failed` | `search_started`, `search_completed` |

---

## Changes

### 1. Event Class Definition

**File**: `src/soothe/tools/file_ops/events.py`

```python
# Before
class BackupCreatedEvent(ToolEvent):
    type: Literal["soothe.tool.file_ops.backup_created"] = "soothe.tool.file_ops.backup_created"
    ...

register_event(BackupCreatedEvent, ...)

TOOL_FILE_OPS_BACKUP_CREATED = "soothe.tool.file_ops.backup_created"

# After
class BackupEvent(ToolEvent):
    type: Literal["soothe.tool.file_ops.backup"] = "soothe.tool.file_ops.backup"
    ...

register_event(BackupEvent, ...)

TOOL_FILE_OPS_BACKUP = "soothe.tool.file_ops.backup"
```

### 2. Event Emission

**File**: `src/soothe/tools/file_ops/implementation.py` (line 283)

```python
# Before
emit_progress(
    BackupCreatedEvent(original_path=str(file_path), backup_path=str(backup_path)).to_dict(),
    logger,
)

# After
emit_progress(
    BackupEvent(original_path=str(file_path), backup_path=str(backup_path)).to_dict(),
    logger,
)
```

### 3. Export Update

**File**: `src/soothe/tools/file_ops/events.py` (`__all__`)

```python
# Before
__all__ = ["TOOL_FILE_OPS_BACKUP_CREATED", ..., "BackupCreatedEvent", ...]

# After
__all__ = ["TOOL_FILE_OPS_BACKUP", ..., "BackupEvent", ...]
```

---

## Affected Files

| File | Change Type |
|------|-------------|
| `src/soothe/tools/file_ops/events.py` | Rename class, type, constant, export |
| `src/soothe/tools/file_ops/implementation.py` | Update event emission (1 location) |

---

## Consumers

No external consumers found. The event:
- Self-registers via `register_event()` at module load
- Is only emitted in `implementation.py:283`
- Is not exported from `__init__.py`

---

## Testing

Run `./scripts/verify_finally.sh` after changes:
- Format check
- Lint (zero errors)
- Unit tests (900+ tests)

No new tests required - existing event registration tests cover this.

---

## Migration Notes

If downstream consumers reference `BackupCreatedEvent` or `TOOL_FILE_OPS_BACKUP_CREATED`, they must update to `BackupEvent` and `TOOL_FILE_OPS_BACKUP`.

---

## Out of Scope

- Other one-off events (`process_killed`, `cache_hit`, `quality_check`) remain unchanged
- No RFC documentation update (minimal change scope)
- No validation tests for naming pattern