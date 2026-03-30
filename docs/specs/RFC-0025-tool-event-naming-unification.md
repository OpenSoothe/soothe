# RFC-0025: Tool Event Naming Unification

**RFC**: 0025
**Title**: Tool Event Naming Unification
**Status**: Draft
**Kind**: Architecture Design
**Created**: 2026-03-30
**Updated**: 2026-03-30
**Dependencies**: RFC-0015 (Progress Event Protocol)
**Supersedes**: ---

## Abstract

This RFC defines the naming convention for tool events, establishing a clear distinction between atomic operations (single-shot) and async operations (lifecycle). The primary change renames `backup_created` to `backup` in the `file_ops` tool, aligning it with the atomic verb pattern used by `read`, `write`, and `delete`.

## Scope and Non-Goals

### Scope

This RFC defines:

* Naming convention: atomic operations use simple verbs, async operations use `*_started`, `*_completed`, `*_failed` triplets
* Rename of `BackupCreatedEvent` to `BackupEvent` in `file_ops` tool
* Migration of type string `soothe.tool.file_ops.backup_created` → `soothe.tool.file_ops.backup`

### Non-Goals

This RFC does **not** define:

* Changes to other one-off events (`process_killed`, `cache_hit`, `quality_check`)
* Validation tests for naming pattern compliance
* New event types or event infrastructure changes

## Background & Motivation

### Problem

The `file_ops` tool events exhibit naming inconsistency:

| Event | Pattern | Category |
|-------|---------|----------|
| `read` | Simple verb | Atomic ✓ |
| `write` | Simple verb | Atomic ✓ |
| `delete` | Simple verb | Atomic ✓ |
| `search_started` | Lifecycle triplet | Async ✓ |
| `search_completed` | Lifecycle triplet | Async ✓ |
| `backup_created` | Past-tense adjective | **Neither** ❌ |

The `backup_created` event is an atomic operation (single-shot backup creation) but uses past-tense naming that doesn't match the simple verb pattern of other atomic file operations.

### Solution

Rename `backup_created` → `backup` to align with the atomic verb pattern.

## Design Principles

### Principle 1: Atomic vs Async distinction

Tool operations fall into two categories:

* **Atomic**: Single-shot operations with immediate completion. Use simple verbs: `read`, `write`, `delete`, `backup`.
* **Async**: Operations with observable lifecycle (start → progress → complete/fail). Use triplet pattern: `*_started`, `*_completed`, `*_failed`.

### Principle 2: Semantic consistency

Event names should describe the action the tool performs, not the outcome state. `backup` describes the action; `backup_created` describes a state.

### Principle 3: Type string alignment

Event type strings follow the 4-segment pattern: `soothe.tool.<component>.<action>`. The `<action>` segment uses the same naming convention as the event class.

## Specification

### Naming Convention

```
Atomic operations:  soothe.tool.<component>.<verb>
                    Examples: soothe.tool.file_ops.read
                              soothe.tool.file_ops.write
                              soothe.tool.file_ops.backup

Async operations:   soothe.tool.<component>.<action>_started
                    soothe.tool.<component>.<action>_completed
                    soothe.tool.<component>.<action>_failed
                    Examples: soothe.tool.file_ops.search_started
                              soothe.tool.file_ops.search_completed
```

### Event Class Rename

**Before:**

```python
class BackupCreatedEvent(ToolEvent):
    type: Literal["soothe.tool.file_ops.backup_created"] = "soothe.tool.file_ops.backup_created"
    original_path: str = ""
    backup_path: str = ""
    model_config = ConfigDict(extra="allow")

register_event(BackupCreatedEvent, verbosity=VerbosityTier.NORMAL, summary_template="Backup: {original_path} → {backup_path}")

TOOL_FILE_OPS_BACKUP_CREATED = "soothe.tool.file_ops.backup_created"
```

**After:**

```python
class BackupEvent(ToolEvent):
    type: Literal["soothe.tool.file_ops.backup"] = "soothe.tool.file_ops.backup"
    original_path: str = ""
    backup_path: str = ""
    model_config = ConfigDict(extra="allow")

register_event(BackupEvent, verbosity=VerbosityTier.NORMAL, summary_template="Backup: {original_path} → {backup_path}")

TOOL_FILE_OPS_BACKUP = "soothe.tool.file_ops.backup"
```

### Emission Site Update

**File**: `src/soothe/tools/file_ops/implementation.py`

**Before (line 283):**

```python
emit_progress(
    BackupCreatedEvent(original_path=str(file_path), backup_path=str(backup_path)).to_dict(),
    logger,
)
```

**After:**

```python
emit_progress(
    BackupEvent(original_path=str(file_path), backup_path=str(backup_path)).to_dict(),
    logger,
)
```

### Export Update

**File**: `src/soothe/tools/file_ops/events.py`

Update `__all__` list:

```python
# Before
__all__ = [
    "TOOL_FILE_OPS_BACKUP_CREATED",
    ...
    "BackupCreatedEvent",
    ...
]

# After
__all__ = [
    "TOOL_FILE_OPS_BACKUP",
    ...
    "BackupEvent",
    ...
]
```

## Affected Files

| File | Change |
|------|--------|
| `src/soothe/tools/file_ops/events.py` | Rename class, type string, constant, export |
| `src/soothe/tools/file_ops/implementation.py` | Update emission (1 location, line 283) |

## Migration Impact

### No External Consumers

Analysis confirms:

* Event self-registers via `register_event()` at module load
* Only emitted in `implementation.py:283`
* Not exported from `__init__.py`
* No external references to `BackupCreatedEvent` or `TOOL_FILE_OPS_BACKUP_CREATED`

### Backward Compatibility

No backward compatibility concerns within the Soothe codebase. Downstream consumers (if any) must update references:

* `BackupCreatedEvent` → `BackupEvent`
* `TOOL_FILE_OPS_BACKUP_CREATED` → `TOOL_FILE_OPS_BACKUP`
* Type string `soothe.tool.file_ops.backup_created` → `soothe.tool.file_ops.backup`

## Testing

Run `./scripts/verify_finally.sh` after implementation:

* Format check (Ruff)
* Lint check (zero errors required)
* Unit tests (900+ tests)

No new tests required—existing event registration tests validate the pattern.

## Implementation Checklist

- [ ] Rename `BackupCreatedEvent` to `BackupEvent` in `events.py`
- [ ] Update type string from `backup_created` to `backup`
- [ ] Rename constant `TOOL_FILE_OPS_BACKUP_CREATED` to `TOOL_FILE_OPS_BACKUP`
- [ ] Update `__all__` exports
- [ ] Update emission in `implementation.py` line 283
- [ ] Run `./scripts/verify_finally.sh`
- [ ] Commit changes

## References

* RFC-0015: Progress Event Protocol (event type naming pattern)
* RFC-0024: VerbosityTier Unification (verbosity classification)
* IG-052: Event System Optimization (self-registration pattern)