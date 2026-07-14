# IG-517: Fix TUI Task Display - Duplicates and Generic Labels

**Status**: ✅ Implemented

## Problem Statement

Two UX issues in TUI task delegation display:

1. **Duplicate task items**: Multiple task rows appear on step cards for the same delegation
2. **Generic "Task()" labels**: SubAgent delegations show "Task(description)" instead of specific subagent names like "Explore(...)", "Plan(...)"

## Root Cause Analysis

### Duplicate Tasks

The deduplication logic in `CognitionStepMessage.add_tool_call` (cognition_step.py:784-799) normalizes task tool_call_ids but has race conditions:

1. Streaming tool_call_chunks arrive with provider-assigned IDs (e.g., `toolu_01A...`)
2. Unified ID binding happens later via `normalize_step_task_tool_call_id`
3. Multiple chunks can create separate rows before canonical ID is known
4. The `_row_index` dict uses raw IDs, so duplicates slip through before normalization

The fix needs stronger deduplication at `_row_index` insertion time using task delegation semantics (same step + same subagent_type + same description) rather than relying solely on tool_call_id matching.

### Generic "Task()" Labels

`task_delegation_label` (cognition_step_activity.py:357-375) reads `subagent_type` from `row.args`:

```python
raw_type = args.get("subagent_type", "")
name = get_subagent_display_name(st) if st else "Task"  # Falls back to "Task"
```

The subagent_type is recorded in `StepTaskRouter._spawns_by_task_id` via `register_task_spawn` but not propagated to the task row's `args` dict. The row creation path:

1. `_ingest_main_task_tool_on_step_card` calls `register_task_spawn` with `subagent_type`
2. `_register_main_tool_on_step_card` calls `step_w.add_tool_call(tcid, "task", args)`
3. `args` may lack `subagent_type` if wire update had incomplete streaming args

Fix: Ensure `subagent_type` is always present in task row args, sourcing from:
- Wire/stream args (primary)
- Router spawn registry (fallback when args incomplete)

## Implementation Plan

### Phase 1: Fix Duplicate Task Rows

**File**: `packages/soothe-cli/src/soothe_cli/tui/widgets/messages/cognition_step.py`

Modify `add_tool_call` to:

1. When `is_task_row=True`, check for existing task rows with matching dedupe semantics
2. Use `task_delegation_dedupe_key` to identify potential duplicates before creating new row
3. Update existing row's args if found, instead of creating duplicate

```python
def add_tool_call(self, tool_call_id, tool_name, args, ...):
    # ... existing logic ...
    if is_task_row:
        dedupe_key = self._task_delegation_dedupe_key(row)  # Check by semantics
        for existing_row in self._rows:
            if not existing_row.is_task_row:
                continue
            existing_key = task_delegation_dedupe_key(existing_row, self._step_id)
            if existing_key == dedupe_key:
                # Update existing row instead of creating duplicate
                self.update_tool_args(existing_row.tool_call_id, args)
                return
    # ... create new row ...
```

### Phase 2: Propagate subagent_type to Task Row Args

**File**: `packages/soothe-cli/src/soothe_cli/tui/widgets/messages/cognition_step.py`

Modify `add_tool_call` to ensure `subagent_type` is in args for task rows:

```python
def add_tool_call(self, tool_call_id, tool_name, args, ...):
    if is_task_row and tool_name == "task":
        # Ensure subagent_type is present
        if "subagent_type" not in args or not args.get("subagent_type"):
            # Could inject from router if needed, but simpler:
            # Just preserve whatever we have and let update fill it in
            pass
```

**Alternative**: Modify `_register_main_tool_on_step_card` in textual_adapter.py to inject `subagent_type` from router:

```python
def _register_main_tool_on_step_card(...):
    if is_task_row and tool_name == "task":
        # Inject subagent_type from router if missing
        if "subagent_type" not in args or not args.get("subagent_type"):
            spawn_scope = router._spawns_by_task_id.get(tcid)
            if spawn_scope:
                args["subagent_type"] = spawn_scope[1]  # subagent_type is scope[1]
```

### Phase 3: Add Valid Subagent Display Names

**File**: `packages/soothe-cli/src/soothe_cli/tui/commands/subagent_routing.py`

Update `SUBAGENT_DISPLAY_NAMES` to include only valid soothe core subagents:
- **Built-in** (registered in `SUBAGENT_FACTORIES`): `explore`, `plan`, `deep_research`
- **Plugin-based** (registered via `@plugin` decorator): `browser_use`

```python
SUBAGENT_DISPLAY_NAMES: dict[str, str] = {
    "explore": "Explore",
    "plan": "Plan",
    "deep_research": "Deep Research",
    "browser_use": "Browser",
}
```

**Note**: Previously added invalid names (`code-review`, `research`, `write`, `judge`, `verify`) were removed since they don't exist in soothe core. Unknown subagent types fall back to displaying the raw technical name.

## Test Plan

1. **Unit test for deduplication**: Test `add_tool_call` with multiple task chunks having different IDs but same delegation
2. **Unit test for label display**: Test `task_delegation_label` with various `subagent_type` values
3. **Manual test**: Run `/explore` and verify single "Explore(...)" row per delegation

## Files Changed

1. `packages/soothe-cli/src/soothe_cli/tui/widgets/messages/cognition_step.py` - dedupe logic, subagent_type injection
2. `packages/soothe-cli/src/soothe_cli/tui/textual_adapter.py` - propagate subagent_type from router
3. `packages/soothe-cli/src/soothe_cli/tui/commands/subagent_routing.py` - expand display names

## Success Criteria

- Single task row per delegation (no duplicates)
- Task rows show specific subagent names: "Explore(files)", "Plan(next step)"
- Unknown subagent types fall back to title-cased technical name, not generic "Task"

## Implementation Summary

### Actual Changes Made

1. **cognition_step.py**: Added semantic deduplication in `add_tool_call` that checks for existing task rows with matching `(subagent_type, compacted_description)` before creating new rows. Different delegations (different type or description) create separate rows; same delegation with different streaming IDs updates existing row.

2. **textual_adapter.py**: Modified `_register_main_tool_on_step_card` to inject `subagent_type` from router registry (`_spawns_by_task_id`) when streaming args lack it.

3. **subagent_routing.py**: Expanded `SUBAGENT_DISPLAY_NAMES` with common types: `plan`, `code-review`, `research`, `write`, `judge`, `verify`.

4. **test_task_row_dedup.py**: Added 8 unit tests covering deduplication scenarios and display name mapping.