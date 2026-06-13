# IG-624-1: CE Engine Completeness

**RFC**: 624 (Phase 3a)
**Status**: Draft
**Created**: 2026-06-13
**Depends on**: RFC-624, design draft `docs/drafts/2026-06-12-ce-engine-completeness-design.md`

---

## Objective

Harden `soothe.context` into a self-sufficient engine with a complete public API, full state machine, event callbacks, lossless persistence, bounded ledger growth, and complete projection output. No changes to existing StrangeLoop code.

## Implementation Steps

### Step 1: GoalStepDAG state transitions

**File**: `packages/soothe/src/soothe/context/models.py`

Add three methods to `GoalStepDAG`:

- `cancel_goal(goal_id)` — set status to `"cancelled"`, set `updated_at`
- `block_goal(goal_id)` — set status to `"blocked"`, set `updated_at`
- `unblock_goal(goal_id)` — set status to `"pending"` only if currently `"blocked"`, set `updated_at`

Follow the same pattern as `complete_goal`/`fail_goal`/`suspend_goal`. No new fields needed.

### Step 2: LedgerManager public access + compaction

**File**: `packages/soothe/src/soothe/context/ledger.py`

1. Add `max_entries: int = 200` and `compact_fn: Callable | None = None` parameters to `__init__`. Convert from `@dataclass` to explicit `__init__` if needed for the new params, or use `field(default=...)`.

2. Add `entries(phases=None)` method returning `list[tuple[BaseMessage, str | None]]`:
   ```python
   def entries(self, phases=None):
       if phases is None:
           return [(e.message, e.phase) for e in self._entries]
       phase_set = set(phases)
       return [(e.message, e.phase) for e in self._entries if e.phase in phase_set]
   ```

3. Implement `compact()`:
   - If `len(_entries) <= _max_entries`, return
   - Compute excess = `len(_entries) - _max_entries`
   - If `_compact_fn` is set, call it with `self._entries[:excess]`, replace with single `SystemMessage(content=summary, phase="compacted")`
   - If `_compact_fn` is None, drop `self._entries[:excess]`

4. Auto-trigger: at end of `record_message()`, if `len(_entries) > _max_entries`, call `self.compact()`

### Step 3: ContextEngine callback mechanism

**File**: `packages/soothe/src/soothe/context/engine.py`

1. Add `_callbacks: dict[str, list[Callable]]` to `__init__`

2. Add `EngineEvent` type alias and public methods:
   ```python
   EngineEvent = Literal[
       "goal_created", "goal_activated", "goal_completed", "goal_failed",
       "goal_suspended", "goal_cancelled", "goal_blocked", "goal_unblocked",
       "step_completed", "step_failed", "step_skipped",
   ]

   def on(self, event: EngineEvent, callback: Callable) -> None
   def off(self, event: EngineEvent, callback: Callable) -> None
   def _fire(self, event: EngineEvent, *args: Any) -> None
   ```

3. Add `_fire()` calls to all existing state-transition methods:
   - `create_goal` → `_fire("goal_created", goal.id)`
   - `activate_goal` → `_fire("goal_activated", goal_id)`
   - `complete_goal` → `_fire("goal_completed", goal_id)`
   - `fail_goal` → `_fire("goal_failed", goal_id, error)`
   - `suspend_goal` → `_fire("goal_suspended", goal_id, reason)`
   - `complete_step` → `_fire("step_completed", goal_id, step_id)`
   - `fail_step` → `_fire("step_failed", goal_id, step_id)`

4. `_fire()` catches all callback errors, logs warnings, never blocks state transition.

### Step 4: ContextEngine missing transitions

**File**: `packages/soothe/src/soothe/context/engine.py`

Add four new async methods, each delegating to `GoalStepDAG`/`StepDAG` and firing callbacks:

- `cancel_goal(goal_id)` → `self._dag.cancel_goal(goal_id)` + `_fire("goal_cancelled", goal_id)`
- `skip_step(goal_id, step_id)` → `goal.steps.mark_skipped(step_id)` + `_fire("step_skipped", goal_id, step_id)`
- `block_goal(goal_id)` → `self._dag.block_goal(goal_id)` + `_fire("goal_blocked", goal_id)`
- `unblock_goal(goal_id)` → `self._dag.unblock_goal(goal_id)` + `_fire("goal_unblocked", goal_id)`

### Step 5: ContextEngine public read API

**File**: `packages/soothe/src/soothe/context/engine.py`

Add synchronous read methods (not async — in-memory reads):

- `get_dag_snapshot()` → `self._dag.snapshot()`
- `get_step_dag(goal_id)` → `goal.steps if goal else None`
- `get_ledger_entries(phases=None)` → `self._ledger.entries(phases)`
- `get_all_goals()` → `list(self._dag.goals.values())`
- `get_goal_lineage(goal_id)` → `self._dag.goal_lineage(goal_id)`

### Step 6: Lossless ledger persistence

**File**: `packages/soothe/src/soothe/context/engine.py`

1. Replace `save()` ledger serialization: iterate `self._ledger.entries()`, call `msg.model_dump()`, add `_phase` and `_msg_type` keys.

2. Replace `load()` deserialization:
   - Pop `_msg_type` and `_phase` from each entry dict
   - Call `_reconstruct_message(type_name, data)` which maps type names to LangChain classes
   - If reconstruction fails, fall back to content-only message
   - If `_msg_type` key is absent (old format), use legacy logic: check `type` key for "AIMessage"/"HumanMessage", construct with content only

3. Add `_MESSAGE_TYPES` dict and `_reconstruct_message()` helper at module level.

### Step 7: Complete ContextBundle projection

**File**: `packages/soothe/src/soothe/context/projection.py`

In `ProjectionEngine.project()`, after computing `ledger_summary`:

```python
ledger_messages: list[dict] = []
for msg, phase in ledger.entries():
    content = getattr(msg, "content", "")
    if not isinstance(content, str):
        content = ""
    ledger_messages.append({
        "type": type(msg).__name__,
        "phase": phase,
        "content": _truncate(content, 500),
    })
ledger_messages = ledger_messages[-cfg.max_ledger_messages:]
```

Pass `ledger_messages=ledger_messages` to `ContextBundle()` constructor.

### Step 8: Unit tests

**File**: `packages/soothe/tests/unit/context/` (new or existing test files)

| Test | Validates |
|------|-----------|
| `test_get_dag_snapshot` | Snapshot matches current DAG state |
| `test_get_step_dag` | Returns correct StepDAG or None |
| `test_get_ledger_entries` | Returns (msg, phase) tuples, phase filtering works |
| `test_get_all_goals` | Returns all goals |
| `test_get_goal_lineage` | Returns chain from root to target |
| `test_cancel_goal` | Goal transitions to "cancelled" |
| `test_skip_step` | Step transitions to "skipped" |
| `test_block_unblock_goal` | Block → "blocked", unblock → "pending" |
| `test_callback_on` | Callback fires on state change |
| `test_callback_off` | Unregistered callback doesn't fire |
| `test_callback_error_handling` | Callback error logged, state still changes |
| `test_lossless_persistence_human` | HumanMessage round-trip preserves all fields |
| `test_lossless_persistence_ai` | AIMessage with tool_calls/response_metadata round-trip |
| `test_lossless_persistence_tool` | ToolMessage round-trip |
| `test_backward_compat_persistence` | Old format (type+content+phase) loads correctly |
| `test_ledger_compact_no_fn` | Excess entries dropped when no compact_fn |
| `test_ledger_compact_with_fn` | Entries summarized into SystemMessage |
| `test_context_bundle_ledger_messages` | ledger_messages populated with type, phase, content |

### Step 9: Verify existing tests pass

Run full test suite:
```bash
python -m pytest packages/soothe/tests/unit/core/loop/ -x -q
python -m pytest packages/soothe/tests/integration/context/ -x -q
python -m pytest packages/soothe/tests/unit/context/ -x -q
```

All existing adapter (22) + integration (9) tests must pass without modification.

## Build Sequence

1. `models.py` (Step 1) — no dependencies
2. `ledger.py` (Step 2) — no dependencies
3. `engine.py` (Steps 3-6) — depends on Steps 1-2
4. `projection.py` (Step 7) — depends on Step 2 (entries())
5. Tests (Step 8) — depends on all implementation steps
6. Verification (Step 9) — final gate

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| LedgerManager dataclass → explicit `__init__` breaks existing code | Keep `@dataclass`, add `field(default=...)` for new params |
| `model_dump()` produces keys that `model_validate()` rejects on load | `_reconstruct_message` catches all validation errors, falls back to content-only |
| Callback errors block state transitions | `_fire()` catches all exceptions per callback |
| Auto-compact changes ledger behavior | Only triggers at `max_entries=200`, which is far above typical session usage |

## Acceptance Criteria

- All 6 component changes implemented and tested
- All existing tests pass without modification
- No changes to `context_adapters.py` or any StrangeLoop code
- `ContextBundle.ledger_messages` populated on projection
- Full BaseMessage round-trip persistence with backward compat
