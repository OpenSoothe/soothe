# CE Phase 4: ContextEngine-as-LoopState-Backend

> RFC-624 Phase 4 design. Two stages: (1) big-bang migration making ContextEngine the sole data
> source for goal/step/ledger state, with CE-backed properties and loop-scoped CE lifecycle;
> (2) cleanup + deeper integration removing legacy artifacts and making CE the single authority.

## Problem

ContextEngine (CE) was wired as a per-goal shadow of LoopState:

1. CE was recreated per `run_with_progress()` — the GoalStepDAG never accumulated across goals
2. LoopState's 48 fields mixed CE-owned data (goals, steps, ledger) with execution-only data (workspace, skills, wave metrics)
3. Three adapter layers added indirection without full CE utilization
4. Cross-goal continuity depended on checkpoint fallback — not on CE itself
5. `GoalExecutionRecord` in the checkpoint duplicated data that CE should own
6. `InMemoryContextPersistence` existed as a no-op backend that defeated the purpose of persistence

---

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Migration strategy | Big-bang | Avoids intermediate dual-write states; user preference |
| Property style | CE-backed `@property` accessors | No sync-or-stale footgun; always fresh; CE is in-process so cost is negligible |
| state_manager | Keep alongside CE | Checkpoint persistence, iteration recording, and thread-switch detection are distinct from CE's data model |
| Persistence backends | Remove in-memory; keep file + sqlite; add pgsql | In-memory defeats persistence; pgsql needed for production deployments |
| CE scope | Loop-scoped (persists across goals within a loop_id) | Cross-goal continuity via DAG accumulation; ce.load() on startup |
| GER scope | Slim to metadata-only | CE-owned fields are always empty after clear_goal_state(); CE is the real data store |
| Ledger writes | CE-only (remove loop_messages param) | No dual-write path; all 6 source callers already pass CE |
| Goal history reads | CE queries replace checkpoint reads | CE DAG has completed goals; checkpoint goal_history is metadata index |

---

## Stage 1: Big-Bang Migration (IMPLEMENTED)

The following changes were implemented in the initial Phase 4 PR.

### Persistence backend polish

- **Removed `InMemoryContextPersistence`** — deleted `context/persistence/in_memory.py`, removed from `__init__.py` exports
- **Added `PgsqlContextPersistence`** — `context/persistence/pgsql_backend.py` with JSONB schema, asyncpg connection pool
- **Added projection limit config** — `ContextEngineConfig` has 6 projection fields mapping 1:1 to `ProjectionConfig`, plus `to_projection_config()` bridge method
- **Removed separate persistence config** — CE follows `persistence.default_backend` instead of its own `persistence_backend` field
- **CE defaults to sqlite :memory:** when no persistence provided — `ContextEngine.__init__()` creates an in-memory SQLite backend as default

### LoopState property migration

Converted three fields from Pydantic fields to `PrivateAttr` + `@property`:

| Field | CE source | Write path |
|---|---|---|
| `loop_messages` | `ce.ledger.entries()` + Loop-type wrapping | `ce.ledger.record_message()` |
| `step_results` | `ce.get_goal_sync(goal_id).steps.nodes` → map to `StepResult` | `ce.complete_step()` / `ce.fail_step()` |
| `completed_step_ids` | `{s.id for s in goal.steps.nodes.values() if s.status == "completed"}` | Derived from CE StepDAG |

Implementation details:
- `model_validator(mode="before")` captures constructor kwargs and stashes them on the class
- `__init__` override applies captured kwargs to private caches
- Setters write to cache for backward compatibility (tests, unbound state)
- `_build_loop_messages_from_ce()` converts CE ledger entries to Loop message types
- `_build_step_results_from_ce()` maps `StepNode` + `StepExecution` to `StepResult`
- `_step_node_to_result()` and `_clamp_error_type()` helpers for CE → LoopState mapping
- `add_step_result()` is a no-op when CE bound (returns immediately)
- `trim_loop_messages()` skips when CE bound
- `sync_loop_messages_from_ce()` is a no-op retained for backward compatibility

### Loop-scoped CE lifecycle

CE instance stored on `StrangeLoop._ce`:
- Created lazily on first `run_with_progress()` call
- Subsequent calls reuse the same CE instance
- `ce.load()` restores prior DAG + ledger state at the top of each `run_with_progress()`
- `ce.create_goal()` adds a new goal to the existing DAG alongside completed prior goals
- Projection config from `ContextEngineConfig.to_projection_config()` passed to CE constructor

### Orchestrator node updates

Removed `sync_loop_messages_from_ce()` calls from all 6 graph nodes:
- `execute_steps.py`, `goal_completion.py`, `record_iteration.py`, `plan_assess.py`, `plan_generate.py`, `resolve_decision.py`

### Remaining legacy artifacts (addressed in Stage 2)

- `sync_loop_messages_from_ce()` — no-op, zero callers, not yet deleted
- `_record_ledger_message` still takes unused `loop_messages` parameter
- `seed_loop_ledger_from_prior_goal()` — deprecated, only used in 2 test files
- `resolve_decision.py:71` — `state.completed_step_ids.clear()` is effectively no-op when CE bound
- `goal_completion.py` — save/restore pattern for `step_results` writes to cache but invisible when CE reads from DAG
- `clear_goal_state()` — calls `.clear()` on caches, redundant when CE bound
- `GoalExecutionRecord` still has CE-owned fields that are always empty after `finalize_goal()`

---

## Stage 2: Cleanup + Deeper Integration

Remove legacy dual-write artifacts and make CE the single authority for goal/step/ledger state,
while slimming the checkpoint to a metadata-only index.

### Section 1: Slim GoalExecutionRecord to Metadata-Only

Remove these always-empty fields from `GoalExecutionRecord`:
- `loop_messages` — CE ledger spans all goals
- `step_results` — CE StepDAG owns this
- `completed_step_ids` — derived from CE StepDAG
- `evidence_ledger` — not populated after `clear_goal_state()`
- `current_plan` — `clear_goal_state()` sets `current_decision = None` first, so `finalize_goal()` mirrors `None`

These fields are empty in every completed goal record because `clear_goal_state()` runs before
`finalize_goal()`. Keeping them creates the false impression that the checkpoint retains execution
data, when in fact CE is the only source.

**Kept fields:** `goal_id`, `goal_text`, `thread_id`, `iteration`, `max_iterations`, `status`,
`plan_revision_count`, `goal_completion`, `evidence_summary`, `duration_ms`, `tokens_used`,
`started_at`, `completed_at`.

**Schema version bump:** `3.3` → `3.4` to signal the field removal. `normalize_checkpoint_data()`
fills defaults for partial blobs from daemon registration, so existing persisted checkpoints
with the old fields degrade gracefully (extra fields are ignored by Pydantic).

**`sloop_manager.finalize_goal()` changes:**
Remove the mirroring block that copies `current_decision`, `completed_step_ids`, `step_results`,
`evidence_ledger`, `evidence_summary` from `LoopState` into the goal record. These copies are
always empty — `clear_goal_state()` already wiped them. Remove the corresponding lines in
`finalize_goal()` that set `goal_record.current_plan`, `goal_record.completed_step_ids`,
`goal_record.step_results`, `goal_record.evidence_ledger`.

**`sloop_manager.record_iteration()` changes:**
Remove the deep-copy of `state.loop_messages` into `goal_record.loop_messages`. CE ledger is
authoritative; the iteration update no longer needs to duplicate messages into the goal record.

**Test updates:** Tests that assert on `GoalExecutionRecord` fields like `loop_messages`,
`step_results`, or `completed_step_ids` must be updated to read from CE instead.

### Section 2: Eliminate goal_completion Save/Restore for step_results

Currently `goal_completion.py` does:

```python
pre_clear_step_results = list(state.step_results)   # save
state.clear_goal_state()                              # clear
...
state.step_results = pre_clear_step_results           # restore for synthesis
...
state.step_results = []                               # re-clear
```

When CE is bound, the restore writes to cache but the property reads from the CE StepDAG — so
synthesis already reads fresh CE data regardless of the cache restore. The save/restore is dead
code when CE is bound.

**New approach:**
1. Remove `pre_clear_step_results` snapshot entirely.
2. Before calling synthesis, build step_results from CE when available:
   ```python
   if ctx.ce is not None:
       ce_goal = ctx.ce.get_goal_sync(ctx.ce_goal_id)
       step_results_for_synthesis = (
           [_step_node_to_result(n) for n in ce_goal.steps.nodes.values()
            if n.execution is not None] if ce_goal else []
       )
   else:
       step_results_for_synthesis = list(state.step_results)
   ```
   The synthesis/classifier functions receive `step_results_for_synthesis` as an explicit
   parameter instead of reading from `state.step_results`. This makes the data flow explicit
   and removes the implicit save/restore coupling.
3. For `CompletionStrategy.SUMMARY`, same approach.
4. For `CompletionStrategy.LEDGER_DIRECT`, no change needed — it never reads step_results.

**`clear_goal_state()` changes:**
Keep clearing `_step_results_cache` and `_completed_step_ids_cache` for test hygiene (unbound
state still uses caches). Remove the `.clear()` calls on the property return values — they were
already no-ops (clearing a fresh list/set returned by the property). The cache clears remain.

### Section 3: Simplify _record_ledger_message — CE-Only Writes

**Signature change:**
```python
# Before
def _record_ledger_message(
    context_engine: Any | None,
    msg: Any,
    phase: str,
    loop_messages: list[Any],       # removed
) -> None:
    if context_engine is not None:
        ...
    loop_messages.append(msg)       # fallback removed

# After
def _record_ledger_message(
    context_engine: Any | None,
    msg: Any,
    phase: str,
) -> None:
    if context_engine is None:
        raise ValueError("_record_ledger_message requires a ContextEngine instance")
    if isinstance(msg, BaseMessage):
        context_engine.ledger.record_message(msg, phase)
    else:
        logger.warning("_record_ledger_message: non-BaseMessage dropped: %s", type(msg))
```

**Caller updates** (6 source files, drop 4th argument):
- `executor.py` (2 call sites: error path, success path)
- `planner.py` (2 call sites: plan_assess, plan_generate)
- `goal_completion.py` (1 call site: `_append_goal_completion_ledger_pair`)
- `execute_steps.py` (1 call site: ask-user path)

**Test updates:** Tests that call `_record_ledger_message` without a CE instance must provide
one (sqlite `:memory:`).

### Section 4: Remove completed_step_ids.clear() in resolve_decision

**Current code** (`resolve_decision.py:71`):
```python
if plan_result.plan_action == "new":
    state.completed_step_ids.clear()
    state.current_decision = decision
```

**Remove the `.clear()` call.** Rationale:
- New plans have fresh step IDs — old completions don't collide with new step IDs
- `dependency_completion_ids()` already unions `completed_step_ids` with historical
  `step_results`, so replanned steps that depend on prior-wave IDs (e.g. `step_001`)
  still resolve correctly via the historical-success path
- When CE is bound, the cache clear is invisible anyway — the property reads from the DAG
- No CE API call needed; the old step IDs simply remain in the completed set and don't
  interfere with the new plan's dependency resolution

### Section 5: Replace goal_history Reads with CE Queries

#### 5a. Replace `_prior_goal_summaries()`

**Current** (`plan_assess.py:71-98`):
Reads `checkpoint.goal_history[:-1]` (all goals except the active one), renders compact
summaries for the continuation-assess LLM prompt.

**New approach:**
```python
def _prior_goal_summaries(ctx: LoopRuntimeContext) -> list[dict]:
    if ctx.ce is None:
        # Fallback for tests without CE
        return []
    completed = [g for g in ctx.ce.get_all_goals() if g.status == "completed"]
    summaries = []
    for goal in completed:
        summaries.append({
            "goal_id": goal.id,
            "goal_text": goal.description,
            "completion": goal.action_history[-1] if goal.action_history else "",
            "step_count": len([s for s in goal.steps.nodes.values() if s.status == "completed"]),
        })
    return summaries
```

This removes the dependency on `checkpoint.goal_history` for planning context. CE DAG is the
source. The function signature changes to accept `LoopRuntimeContext` instead of
`StrangeLoopCheckpoint`.

**Also update `_is_fresh_loop()`** (`bounded_evidence_gather.py:22-44`):
Replace the `len(ctx.checkpoint.goal_history) < 2` condition with a CE query. The other
conditions in `_is_fresh_loop()` (checking `state.iteration == 0` and
`state.current_decision is None`) remain unchanged:
```python
# Replace this condition:
#   len(ctx.checkpoint.goal_history) < 2
# With:
has_completed_goals = (
    ctx.ce is not None
    and any(g.status == "completed" for g in ctx.ce.get_all_goals())
)
# Fresh loop = no completed goals in CE
```

#### 5b. Delete `seed_loop_ledger_from_prior_goal()`

Already deprecated with docstring noting "No longer called from `strange_loop.py`". Only used
in 2 test files:
- `test_clobbered_status_recovery.py`
- `test_plan_assess_continue_thread.py`

Delete the function and update these tests to use CE-based ledger population instead.

#### 5c. `continue_loop_mode` derivation — no change

Keep derived from `len(checkpoint.goal_history) >= 2` in `strange_loop.py`. This is simple,
reliable, and doesn't need CE involvement. The checkpoint is always available at this point
in the lifecycle.

---

## What Gets Deleted (Stage 2)

| Component | Location | Reason |
|---|---|---|
| `GoalExecutionRecord.loop_messages` | `checkpoint.py` | Always empty; CE ledger spans all goals |
| `GoalExecutionRecord.step_results` | `checkpoint.py` | Always empty; CE StepDAG owns this |
| `GoalExecutionRecord.completed_step_ids` | `checkpoint.py` | Always empty; derived from CE StepDAG |
| `GoalExecutionRecord.evidence_ledger` | `checkpoint.py` | Always empty after clear_goal_state() |
| `GoalExecutionRecord.current_plan` | `checkpoint.py` | Always None after clear_goal_state() |
| `seed_loop_ledger_from_prior_goal()` | `plan_assess.py` | Deprecated; CE ledger spans all goals |
| `sync_loop_messages_from_ce()` | `schemas.py` | No-op; zero callers |
| `_record_ledger_message` `loop_messages` param | `messages.py` | Unused when CE bound; CE-only writes |
| `pre_clear_step_results` save/restore | `goal_completion.py` | CE DAG is read directly |
| `state.completed_step_ids.clear()` | `resolve_decision.py` | Unnecessary for new-plan semantics |
| `finalize_goal()` mirroring of CE-owned fields | `sloop_manager.py` | Writes empty data |
| `record_iteration()` deep-copy of loop_messages | `sloop_manager.py` | CE ledger is authoritative |

## What Stays

| Component | Why |
|---|---|
| `GoalExecutionRecord` (slimmed) | Metadata index for checkpoint: goal_id, status, timestamps, metrics |
| `state_manager` | Checkpoint persistence, iteration recording, thread-switch detection |
| `ContextEngineGoalContextAdapter` | Already reads from CE DAG; thin convenience |
| `StepPlanManagerAdapter` | Binds goal_id to planning submodule |
| `add_step_result()` | No-op when CE bound, fallback for tests without CE |
| `clear_goal_state()` | Clears execution context (current_decision, plan_id, wave metrics) — still needed |
| `continue_loop_mode` from goal_history | Simple, reliable, doesn't need CE involvement |

---

## Error Handling

No new error surface beyond what already exists:

- CE queries in `_prior_goal_summaries` and `_is_fresh_loop` are wrapped in try/except with
  graceful fallbacks (empty list, fresh-loop default)
- `_record_ledger_message` raises `ValueError` when CE is `None` — this is a test-only path
  (production always provides CE)
- Synthesis reading from CE DAG: `get_goal_sync()` returns `None` when goal not found, which
  falls back to reading from `state.step_results` cache

---

## Testing Strategy

### Unit tests

| Test | What it verifies |
|---|---|
| `test_ger_metadata_only.py` | GoalExecutionRecord only has metadata fields; CE-owned fields absent |
| `test_record_ledger_ce_only.py` | `_record_ledger_message` raises ValueError without CE; writes to CE.ledger with CE |
| `test_prior_goals_from_ce.py` | `_prior_goal_summaries` reads completed goals from CE DAG, not checkpoint |
| `test_is_fresh_loop_from_ce.py` | `_is_fresh_loop` queries CE instead of goal_history |
| `test_no_seed_ledger.py` | `seed_loop_ledger_from_prior_goal` is deleted; tests use CE-based approach |
| `test_goal_completion_no_save_restore.py` | Synthesis reads from CE DAG; no pre_clear_step_results |

### Integration tests

| Test | What it verifies |
|---|---|
| `test_cross_goal_ce_authority.py` | Goal 1 completes, goal 2 starts; CE DAG has both goals; checkpoint goal_history has metadata only |
| `test_no_dual_write_paths.py` | Full loop execution with all cleanup applied; no site writes to both CE and cache simultaneously |
| `test_schema_migration_3_4.py` | Checkpoints with schema 3.3 (old fields) load correctly under 3.4 (fields absent) |

### Migration verification

Before merging, run the existing equivalence tests to confirm no regressions:
1. `test_ce_property_equivalence.py` — property-based state produces identical planner output
2. `test_ce_strange_loop_equivalence.py` — full loop execution matches expectations

---

## Migration Sequence (Stage 2)

All steps ship in one PR.

### Step 1: Slim GoalExecutionRecord
- Remove 5 CE-owned fields from `GoalExecutionRecord`
- Remove mirroring logic in `finalize_goal()`
- Remove deep-copy in `record_iteration()`
- Bump schema version to `3.4`
- Update `normalize_checkpoint_data()` for new schema
- Update tests that assert on removed fields

### Step 2: Simplify _record_ledger_message
- Remove `loop_messages` parameter
- Raise `ValueError` when CE is None
- Update all 6 source callers (drop 4th argument)
- Update test callers to provide CE

### Step 3: Eliminate goal_completion save/restore
- Remove `pre_clear_step_results` snapshot
- Synthesis reads from CE DAG directly (with `state.step_results` cache fallback)
- Remove `state.step_results = pre_clear_step_results` and `state.step_results = []`
- Update `clear_goal_state()` to only clear caches (no property return-value clears)

### Step 4: Remove completed_step_ids.clear()
- Delete the `.clear()` call in `resolve_decision.py:71`

### Step 5: Replace goal_history reads with CE queries
- Rewrite `_prior_goal_summaries()` to read from `ctx.ce.get_all_goals()`
- Rewrite `_is_fresh_loop()` to query CE
- Delete `seed_loop_ledger_from_prior_goal()`
- Update 2 test files that called the deleted function

### Step 6: Delete sync_loop_messages_from_ce
- Remove the no-op method from `LoopState`
- Grep for any remaining references and clean up

### Step 7: Verification
- Run `./scripts/verify_finally.sh`
- Run integration equivalence tests
- Verify no dual-write paths remain in source code

---

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| GER field removal breaks persisted checkpoints | Low | Checkpoint load error | Schema version bump; Pydantic ignores extra fields; `normalize_checkpoint_data()` fills defaults |
| Synthesis reads stale CE data | Low | Incorrect goal completion output | CE `finalize_goal()` runs before synthesis; `get_goal_sync()` is synchronous and reads in-memory DAG |
| `_record_ledger_message` ValueError in tests | Medium | Test failures | Batch-update tests to provide CE instance (sqlite :memory:) |
| `_prior_goal_summaries` CE query returns empty | Low | Missing context in continuation prompt | Fallback to empty list; same behavior as current exception handling |
| Removing completed_step_ids.clear() changes plan semantics | Low | Old step IDs appear in dependency set | `dependency_completion_ids()` unions with step_results; old IDs are harmless — they satisfy dependencies that no longer exist in the new plan |
