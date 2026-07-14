# IG-496 Phase 3: Checkpoint Schema 5.0 — Execution-Only Fields

**Status**: In Progress
**RFC**: RFC-626 Phase 3 (§419–§428)
**Created**: 2026-06-16
**Dependencies**: RFC-624 Phase 4 (CE-as-LoopState-Backend), IG-480

## Goal

Trim `StrangeLoopCheckpoint` to execution-only fields. Goal/step state is recovered from ContextEngine persistence on restart. This eliminates duplicate storage and reduces checkpoint payload size by 70-80%.

**Net result**: StrangeLoopCheckpoint stores only execution metrics; CE DAG is the sole source for goal/step/ledger state.

## Scope

### In Scope

- New `ExecutionCheckpoint` model (schema 5.0) with execution-only fields
- `WaveMetrics` model extracted from LoopState wave fields
- StrangeLoopStateManager → save ExecutionCheckpoint only
- Recovery: ExecutionCheckpoint + CE.load() → full state
- Delete goal/step fields from checkpoint (goal_text, plan_revision_count, goal_completion)
- Update recovery flow to use CE DAG instead of checkpoint goal_history

### Out of Scope

- Full LoopState → ExecutionState rename (Phase 5)
- Job abstraction cleanup (Phase 4)
- Adapter deletion (IG-480 Step 7)
- PostgreSQL persistence backend improvements

## Implementation Steps

### Step 1: Create ExecutionCheckpoint Model (schema 5.0)

**Files to create:**
- `packages/soothe/src/soothe/foundation/loop/state/execution_checkpoint.py`

**ExecutionCheckpoint fields (execution-only, no goal state):**

```python
class ExecutionCheckpoint(BaseModel):
    """Execution-only checkpoint for StrangeLoop recovery (RFC-626 Phase 3).
    
    Goal/step/ledger state is recovered from ContextEngine persistence.
    This checkpoint stores only execution metrics not in CE entity model.
    """
    
    # Identity
    loop_id: str  # UUID (primary key)
    current_goal_id: str | None = None  # Current goal being executed (CE lookup key)
    
    # Execution state (NOT in CE)
    max_iterations: int = DEFAULT_STRANGE_LOOP_MAX_ITERATIONS
    iteration: int = 0  # Current iteration (1-indexed)
    
    # Wave metrics (last wave execution state)
    wave_metrics: WaveMetrics = Field(default_factory=WaveMetrics)
    
    # Thread/worker assignment
    thread_id: str
    worker_id: str | None = None
    
    # Loop status
    status: Literal["running", "idle", "finalized", "cancelled"] = "idle"
    thread_switch_pending: bool = False
    
    # Loop-level metrics (cumulative)
    total_goals_completed: int = 0
    total_thread_switches: int = 0
    total_duration_ms: int = 0
    total_tokens_used: int = 0
    
    # Timestamps
    created_at: datetime
    updated_at: datetime
    
    # Schema version for lazy migration
    schema_version: str = "5.0"
```

**WaveMetrics fields:**

```python
class WaveMetrics(BaseModel):
    """Wave execution metrics for Plan phase decisions.
    
    Extracted from LoopState wave fields (RFC-626 §1).
    """
    
    wave_index: int = 0  # 0-based wave within current iteration
    tool_call_count: int = 0
    subagent_task_count: int = 0
    hit_subagent_cap: bool = False
    hit_tool_budget: bool = False
    output_length: int = 0
    error_count: int = 0
    tokens_used: int = 0
    duration_ms: int = 0
    
    # Parallel execution flag
    parallel_multi_step: bool = False
    
    # Last wave answer tracking
    assistant_text: str | None = None
    answer_from_delegate_final: bool = False
```

### Step 2: Update StrangeLoopCheckpoint Schema

**Files to modify:**
- `packages/soothe/src/soothe/foundation/loop/state/checkpoint.py`

**Changes:**
- Replace `GoalExecutionRecord` with minimal `GoalIndexEntry` (goal_id, status only)
- `goal_history` becomes `goal_index` (list of goal_id, status for CE lookup)
- Delete goal_text, plan_revision_count, goal_completion from GoalIndexEntry
- Add `execution_checkpoint` field to StrangeLoopCheckpoint
- Update `schema_version` to "5.0"

**GoalIndexEntry (slimmed GoalExecutionRecord):**

```python
class GoalIndexEntry(BaseModel):
    """Minimal goal index entry for checkpoint (RFC-626 Phase 3).
    
    Goal state recovered from CE GoalNode. Checkpoint only stores
    goal_id and status for loop-level tracking.
    """
    
    goal_id: str  # CE lookup key
    status: Literal["running", "completed", "failed", "cancelled"] = "running"
    thread_id: str  # Which thread executed this goal
    
    # Timestamps (for metrics only, not goal state)
    started_at: datetime
    completed_at: datetime | None = None
    
    # Metrics (execution-level, not goal content)
    duration_ms: int = 0
    tokens_used: int = 0
```

### Step 3: Update StrangeLoopStateManager

**Files to modify:**
- `packages/soothe/src/soothe/foundation/loop/state/sloop_manager.py`

**Changes:**
- Add `save_execution_checkpoint()` method
- Add `load_execution_checkpoint()` method
- Update `save()` to persist ExecutionCheckpoint + GoalIndex
- Update `load()` to return ExecutionCheckpoint + trigger CE.load()
- Add `build_execution_checkpoint_from_state()` helper
- Add `sync_wave_metrics_from_state()` helper

### Step 4: Update Recovery Flow

**Files to modify:**
- `packages/soothe/src/soothe/foundation/loop/engine/strange_loop.py`

**Changes:**
- Recovery path: `load_execution_checkpoint()` → `ce.load()` → rebuild LoopState
- LoopState initialization from CE GoalNode properties
- WaveMetrics sync to ExecutionCheckpoint after each wave
- Delete goal_history replay logic

**Recovery sequence:**

```
1. StrangeLoopStateManager.load_execution_checkpoint(loop_id)
2. ContextEngine.load(loop_id) → GoalStepDAG restored
3. ExecutionCheckpoint.current_goal_id → CE.get_goal()
4. CE.get_goal().steps → rebuild current_decision
5. ExecutionCheckpoint.wave_metrics → restore wave state
6. Continue Plan-Execute loop from last wave
```

### Step 5: Update StrangeLoop LoopState Integration

**Files to modify:**
- `packages/soothe/src/soothe/foundation/loop/state/schemas.py` — LoopState

**Changes:**
- Add `sync_wave_metrics()` method to LoopState
- Add `to_execution_checkpoint()` method
- Add `from_execution_checkpoint_and_ce()` factory method
- Property accessors unchanged (CE-backed)

### Step 6: Update Checkpoint Normalization

**Files to modify:**
- `packages/soothe/src/soothe/foundation/loop/state/checkpoint.py` — `normalize_checkpoint_data()`

**Changes:**
- Add schema 5.0 normalization path
- Handle missing `execution_checkpoint` field (lazy migration)
- Preserve backward compatibility with schema 3.x/4.x

### Step 7: Update Tests

**Files to create:**
- `packages/soothe/tests/unit/core/loop/state/test_execution_checkpoint.py`

**Files to modify:**
- `packages/soothe/tests/unit/core/loop/state/test_checkpoint_normalize.py`
- `packages/soothe/tests/integration/core/test_loop_agent.py`

**Test coverage:**
- ExecutionCheckpoint serialization/deserialization
- WaveMetrics extraction from LoopState
- Recovery: ExecutionCheckpoint + CE.load()
- Schema 5.0 lazy migration
- Backward compatibility with schema 3.x/4.x

## Verification

- Checkpoint payload size reduction: 70-80% smaller than schema 3.x
- Recovery produces same execution state as current checkpoint
- CE.load() restores GoalNode/StepNode correctly
- WaveMetrics round-trip through ExecutionCheckpoint
- All existing tests pass after migration

## Risks

| Risk | Mitigation |
|------|-----------|
| CE.load() latency on large DAGs | Lazy GoalNode loading; cache in LoopState |
| Schema 5.0 migration breaks recovery | Normalize function fills defaults; backward compat |
| WaveMetrics missing fields | Defaults in WaveMetrics model; property accessors fallback |

## Dependencies

- IG-480 Step 1 (CE Persistence) must be complete for CE.load()
- IG-480 Step 4 (CE-backed properties) must be complete for LoopState properties
- JobCheckpoint pattern (RFC-228) provides execution-only field template

## Migration Path

Schema 5.0 checkpoints are saved for new loops. Existing schema 3.x/4.x checkpoints:

1. Load with normalize_checkpoint_data() → fills defaults
2. ExecutionCheckpoint built from goal_history metrics
3. CE.load() restores goal/step state from persistence
4. Continue execution with schema 5.0 format

No explicit migration script needed — lazy migration on load.