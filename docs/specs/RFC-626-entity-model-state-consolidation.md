# RFC-626: Entity Model and State Management Consolidation

**RFC**: 626
**Title**: Entity Model and State Management Consolidation — LoopState Elimination
**Status**: Draft
**Kind**: Architecture Design
**Created**: 2026-06-16
**Updated**: 2026-06-16
**Dependencies**: RFC-624 (Context Engine), RFC-625 (AutopilotMonitor and ContextEngine Unification), RFC-203 (StrangeLoop State & Memory), RFC-201 (StrangeLoop Plan-Execute Loop)
**Related**: RFC-228 (Autopilot Job IPC), RFC-222 (Autopilot Architecture), RFC-216 (Checkpoint Tree)
**Extends**: RFC-625 — entity model consolidation, LoopState elimination, job abstraction refinement

---

## Abstract

This RFC consolidates all entity models under ContextEngine, eliminates the `LoopState` model, unifies ledger management, and refines the Job abstraction to operate directly on CE GoalNode entities. It completes the state management unification started in RFC-625 by (1) replacing `LoopState` with a thin `ExecutionState` facade backed by CE properties, (2) eliminating the split between GoalEngine goal storage and ContextEngine DAG, (3) making Job operate directly on GoalNode without intermediate containers, and (4) trimming StrangeLoop checkpoint schema to execution-only fields.

---

## Problem Statement

### Current State (Post RFC-625)

1. **LoopState persists as execution-only container**: StrangeLoop still maintains `LoopState` (RFC-203) with wave metrics, iteration tracking, and plan history. These fields duplicate ContextEngine properties (`total_tokens_used`, `iteration`, `previous_plan`) and create two sources of truth.

2. **Job abstraction uses intermediate Goal model**: RFC-228 defines Job as "root Goal" but autopilot engine still has a `Goal` model (`autopilot/engine/models.py`) that wraps GoalNode. The wrapper adds retry/backoff fields that RFC-625 already migrated to GoalNode.

3. **Ledger split between LedgerManager and loop_messages**: StrangeLoop writes to both `LoopState.loop_messages` (prompt pipeline) and `LedgerManager` (persistence). The dual-write is fragile and the adapter pattern (RFC-624 §9) adds complexity.

4. **Checkpoint schema carries non-execution fields**: `StrangeLoopStateManager` checkpoints goal-level state (description, thread_id) that ContextEngine already persists. Duplication increases checkpoint size and recovery complexity.

5. **State management split across three layers**:
   - ContextEngine: goal/step DAG, ledger persistence, projection
   - StrangeLoop state manager: checkpoint lifecycle, thread switching
   - LoopState: wave metrics, iteration tracking, plan history

### Goals

1. **Single entity model source**: All goal/step entities are GoalNode/StepNode instances managed by ContextEngine. No wrapper models, no intermediate containers.

2. **LoopState elimination**: Replace with thin `ExecutionState` facade that (a) holds only execution-only fields not in CE (wave metrics, max_iterations), and (b) provides property accessors backed by CE for shared fields.

3. **Job operates on GoalNode directly**: Job abstraction (RFC-228) queries ContextEngine for root goals (`parent_id=None`). No `Goal` wrapper model, no `GoalEngine` flat dict.

4. **Single ledger path**: StrangeLoop writes ONLY to `LedgerManager`. Prompt pipeline reads from `LedgerManager`. No `loop_messages` list in ExecutionState.

5. **Trimmed checkpoint schema**: StrangeLoop checkpoint stores only execution-only fields. Goal/step state recovered from ContextEngine persistence on restart.

### Non-Goals

- Changing StrangeLoop prompt templates or execution flow
- Modifying CoreAgent or tool interfaces
- Multi-process checkpoint coordination (deferred to RFC-221 evolution)
- RAG/vector store integration for checkpoint compaction

---

## Solution

### §1 ExecutionState Facade (Replaces LoopState)

`ExecutionState` is a thin facade holding **only execution-only fields** that ContextEngine does not track. All shared fields (tokens, iteration, plan) are property accessors backed by the current GoalNode.

```python
class ExecutionState(BaseModel):
    """Thin facade for StrangeLoop execution-only state.
    
    Backed by ContextEngine GoalNode for shared fields.
    Holds ONLY fields not in CE entity model.
    """

    # Execution-only fields (NOT in CE)
    loop_id: str
    """Loop identifier for this execution."""
    
    max_iterations: int = DEFAULT_STRANGE_LOOP_MAX_ITERATIONS
    """Maximum iterations allowed (config, not CE state)."""

    wave_metrics: WaveMetrics = Field(default_factory=WaveMetrics)
    """Last wave execution metrics for Plan decisions."""

    # Shared fields backed by CE GoalNode (property accessors)
    current_goal_id: str
    """Current goal being executed (key for CE goal lookup)."""

    thread_id: str
    """Thread identifier for this goal execution."""

    assigned_worker_id: str | None = None
    """Worker assignment from AutopilotService (RFC-222)."""
    
    # Properties backed by ContextEngine
    @property
    def iteration(self) -> int:
        """Iteration count from CE GoalNode.max_iterations."""
        return self._ce.get_goal(self.current_goal_id).max_iterations
    
    @property
    def total_tokens_used(self) -> int:
        """Cumulative tokens from CE GoalNode.total_tokens_used."""
        return self._ce.get_goal(self.current_goal_id).total_tokens_used
    
    @property
    def previous_plan(self) -> dict[str, Any] | None:
        """Previous plan from CE GoalNode.previous_plan."""
        return self._ce.get_goal(self.current_goal_id).previous_plan
    
    @property
    def action_history(self) -> list[str]:
        """Action history from CE GoalNode.action_history."""
        return self._ce.get_goal(self.current_goal_id).action_history

    # Internal reference (not serialized)
    _ce: ContextEngine = PrivateAttr()
    
    def sync_to_ce(self) -> None:
        """Sync execution-only fields to CE GoalNode after wave."""
        goal = self._ce.get_goal(self.current_goal_id)
        goal.max_iterations = self.wave_metrics.iteration_count
        goal.total_tokens_used += self.wave_metrics.tokens_used
```

**WaveMetrics** (extracted from LoopState wave fields):

```python
class WaveMetrics(BaseModel):
    """Wave execution metrics for Plan phase decisions."""

    iteration_count: int = 0
    """Current iteration (1-indexed)."""

    tool_call_count: int = 0
    """Tool calls in last Execute wave."""

    subagent_task_count: int = 0
    """Subagent tasks in last Execute wave."""

    hit_subagent_cap: bool = False
    """Whether last wave hit subagent task cap."""

    output_length: int = 0
    """Character length of last wave output."""

    error_count: int = 0
    """Errors in last Execute wave."""

    tokens_used: int = 0
    """Tokens used in last wave."""

    duration_ms: int = 0
    """Duration of last wave in milliseconds."""
```

**Key invariant**: ExecutionState holds NO goal-level state (description, status, steps). All goal state lives in ContextEngine GoalNode.

---

### §2 Job Abstraction Refinement

**Definition (from RFC-228 §44)**: A Job is a **root GoalNode** with `parent_id=None`.

**Job operations operate directly on CE GoalNode**:

| Operation | Implementation | Source |
|-----------|----------------|---------|
| `create_job(goal_text)` | `ce.create_goal(description, parent_id=None)` | AutopilotService.submit_task |
| `job_status(job_id)` | `ce.get_goal(job_id).model_dump()` | RFC-228 IPC |
| `job_pause(job_id)` | `ce.suspend_goal(job_id)` | RFC-228 IPC |
| `job_resume(job_id)` | `ce.activate_goal(job_id)` | RFC-228 IPC |
| `job_cancel(job_id)` | `ce.cancel_goal(job_id)` + cancel all descendants | RFC-228 IPC |
| `job_dag(job_id)` | `ce.goal_subtree(job_id)` (new method) | RFC-228 IPC |
| `list_jobs()` | `ce.list_goals(parent_id=None)` | CLI, Desktop app |

**New ContextEngine method**:

```python
def goal_subtree(self, root_goal_id: str) -> dict[str, Any]:
    """Get DAG subtree rooted at job_id.
    
    Returns nested structure for visualization:
    {
        "root": GoalNode,
        "descendants": [GoalNode],
        "dependency_edges": [(parent_id, child_id)],
        "stats": {"total_goals": N, "completed": M, "failed": K}
    }
    """
```

**No Goal wrapper model**: The `Goal` class in `autopilot/engine/models.py` is deleted. All fields already migrated to GoalNode per RFC-625 §2.

**Job-to-Worker mapping**: Job (root goal) → assigned worker via GoalNode.assigned_loop_id. Worker executes goal and all descendants via StrangeLoop iteration.

---

### §3 Ledger Management Unification

**Single write path**: StrangeLoop writes ONLY to `LedgerManager`:

```python
# StrangeLoop orchestrator nodes
class StrangeLoopOrchestrator:
    def __init__(self, ce: ContextEngine, config: SootheConfig):
        self._ce = ce
        self._ledger = ce.ledger  # LedgerManager reference
        # NO loop_messages list

    async def plan_phase(self, state: ExecutionState) -> PlanResult:
        # Ledger write via LedgerManager
        self._ledger.record_message(
            LoopAIMessage(content=plan_result.reasoning),
            phase="plan_assess"
        )
        # NO state.loop_messages.append(...)

    async def execute_wave(self, state: ExecutionState, steps: list[StepAction]) -> None:
        for event in core_agent.astream(...):
            # Forward to client via stream handler
            # Record in ledger
            self._ledger.record_message(event.message, phase="execute_step")
```

**Prompt pipeline reads from LedgerManager**:

```python
# PromptBuilder (unchanged logic, new source)
def build_system_prompt(state: ExecutionState, config: ProjectionConfig) -> SystemMessage:
    # Read from LedgerManager instead of state.loop_messages
    bundle = state._ce.project(config)
    ledger_text = bundle.ledger_summary
    # Render prompt sections (same XML fragments)
```

**LedgerManager phase filtering** (RFC-624 §4):

| Phase | Purpose | Included in projection |
|-------|---------|------------------------|
| `plan_assess` | LLM assesses progress | Plan phase only |
| `plan_generate` | LLM generates steps | Plan phase only |
| `execute_step` | CoreAgent execution | Execute phase, CoreAgent prompt |
| `clarification` | RFC-622 relay | Plan phase, veritas |
| `final_response` | User-facing output | Plan phase (done assessment) |

**LedgerManager as sole source** invariant: All message recording goes through LedgerManager. No backup list. Recovery rehydrates LedgerManager from StepExecution records in GoalNode.

---

### §4 Checkpoint Schema Consolidation

**StrangeLoop checkpoint trimmed to execution-only fields**:

```python
class ExecutionCheckpoint(BaseModel):
    """Trimmed checkpoint for StrangeLoop execution recovery.
    
    Goal/step state recovered from ContextEngine persistence.
    Contains ONLY execution-only state not in CE.
    """

    # Execution-only fields
    loop_id: str
    thread_id: str
    current_goal_id: str
    wave_metrics: WaveMetrics
    max_iterations: int

    # NO goal-level fields (description, status, steps)
    # NO ledger messages (recovered from CE StepExecution)
    # NO plan history (recovered from GoalNode.previous_plan)

    # Checkpoint metadata
    checkpoint_id: str
    created_at: datetime
    schema_version: str = "5.0"  # RFC-626 consolidated schema
```

**Recovery flow**:

1. Daemon restart → ContextEngine.load() → GoalStepDAG restored
2. StrangeLoop recovery → ExecutionCheckpoint.load() → ExecutionState created
3. ExecutionState._ce = restored ContextEngine
4. LedgerManager rehydrated from GoalNode.steps[].execution.output_messages

**Checkpoint size reduction**:

| Field | RFC-216 Checkpoint | RFC-626 ExecutionCheckpoint | Reduction |
|-------|--------------------|-----------------------------|-----------|
| Goal description | ✓ | ✗ (CE) | ~200 chars |
| Step DAG nodes | ✓ (full) | ✗ (CE) | ~5KB |
| Ledger messages | ✓ (full list) | ✗ (CE) | ~10KB |
| Previous plan | ✓ (dict) | ✗ (CE property) | ~2KB |
| Wave metrics | ✓ | ✓ (same) | 0 |
| Loop ID | ✓ | ✓ (same) | 0 |
| Thread ID | ✓ | ✓ (same) | 0 |

**Estimated reduction**: ~17KB per checkpoint (70-80% smaller).

---

### §5 Module Structure Changes

**Deleted modules**:

| Path | Reason |
|------|--------|
| `autopilot/engine/models.py:Goal` | Fields migrated to GoalNode (RFC-625) |
| `loop/state/schemas.py:LoopState` | Replaced by ExecutionState facade |
| `loop/state/adapters/*` | Adapter pattern eliminated (RFC-624 §9) |

**New modules**:

| Path | Purpose |
|------|---------|
| `foundation/loop/state/execution_state.py` | ExecutionState + WaveMetrics |
| `foundation/loop/state/checkpoint_v5.py` | ExecutionCheckpoint (schema 5.0) |

**Modified modules**:

| Path | Changes |
|------|---------|
| `foundation/context/models.py:GoalNode` | Add `max_iterations` field (from LoopState) |
| `foundation/loop/orchestrator/state.py` | Replace LoopState → ExecutionState |
| `foundation/loop/orchestrator/strange_loop.py` | Remove loop_messages list, use LedgerManager |
| `foundation/autopilot/monitor/monitor.py` | Job operations → CE goal APIs |

---

## Architectural Constraints

1. **ExecutionState holds NO goal state**: All goal-level fields accessed via CE properties. Facade pattern, not state container.

2. **Job = root GoalNode**: No wrapper model, no flat dict. Job queries operate directly on CE.

3. **Single ledger path**: LedgerManager is sole write target. No backup list, no dual-write adapters.

4. **Checkpoint schema 5.0**: Execution-only fields only. Goal/step recovered from CE.

5. **Behavioral equivalence**: StrangeLoop execution produces identical outputs to current implementation. Same prompts, same step IDs, same evidence accumulation.

6. **CE property access is O(1)**: GoalNode lookup by ID is dict-based. Property accessors do NOT iterate.

---

## Data Flow

### Execute Wave Flow (Post RFC-626)

```
1. Plan phase:
   - ExecutionState.current_goal_id → CE.get_goal()
   - CE.project() → ContextBundle → PromptBuilder
   - LedgerManager.get_messages(phases=["plan_*"]) → Plan prompt
   - LLM generates PlanResult
   - CE.add_steps(plan_result.steps)
   - LedgerManager.record_message(plan_result, phase="plan_generate")

2. Execute wave:
   - CE.get_goal().steps.ready_steps() → ready step IDs
   - CoreAgent.astream(step_input)
   - Stream events → client via WebSocket
   - LedgerManager.record_message(event, phase="execute_step")
   - WaveMetrics updated (tool calls, tokens, errors)
   - CE.complete_step(step_id, execution_record)

3. Post-wave sync:
   - ExecutionState.sync_to_ce() → GoalNode.max_iterations, total_tokens_used
   - CE.save() → persistence backend
```

### Recovery Flow

```
1. Daemon startup:
   - ContextEngine.load() → GoalStepDAG + LedgerManager restored
   - AutopilotMonitor.start() → verification loop
   - WorkerPool.init() → subprocess workers

2. StrangeLoop recovery:
   - ExecutionCheckpoint.load(loop_id) → ExecutionState facade
   - ExecutionState._ce = ContextEngine instance
   - LedgerManager already rehydrated from StepExecution records

3. Resume execution:
   - ExecutionState.wave_metrics → last wave state
   - CE.get_goal(current_goal_id).steps.ready_steps() → resume point
   - Continue Plan → Execute loop
```

---

## Implementation Phases

### Phase 1: ExecutionState Facade (Foundation)

**Scope**: Create ExecutionState and WaveMetrics, wire into StrangeLoop

**Changes**:
- New `foundation/loop/state/execution_state.py`
- Replace LoopState references in orchestrator nodes
- Add ContextEngine reference injection
- Property accessors backed by CE GoalNode

**Status**: Pending

### Phase 2: Ledger Unification

**Scope**: Eliminate loop_messages list, single LedgerManager path

**Changes**:
- Remove `loop_messages` from ExecutionState
- StrangeLoop orchestrator → LedgerManager.record_message() only
- PromptBuilder → read from LedgerManager via ContextBundle
- Delete ContextEngineLedgerAdapter

**Status**: Pending

### Phase 3: Checkpoint Schema 5.0

**Scope**: Trimmed checkpoint, CE-based recovery

**Changes**:
- New `ExecutionCheckpoint` model (schema 5.0)
- StrangeLoopStateManager → save ExecutionCheckpoint only
- Recovery: ExecutionCheckpoint + CE.load() → full state
- Delete goal/step fields from checkpoint

**Status**: Pending

### Phase 4: Job Abstraction Cleanup

**Scope**: Delete Goal wrapper, direct CE operations

**Changes**:
- Delete `autopilot/engine/models.py:Goal` (already migrated fields)
- AutopilotService.submit_task → ce.create_goal()
- IPC handlers → ce.get_goal(), ce.goal_subtree()
- CLI/Desktop → ce.list_goals(parent_id=None)

**Status**: Pending

### Phase 5: Module Cleanup

**Scope**: Delete deprecated modules, update imports

**Changes**:
- Delete `loop/state/schemas.py:LoopState`
- Delete adapter modules (ContextEnginePlanAdapter, etc.)
- Update all imports to ExecutionState
- Remove LoopState references from tests

**Status**: Pending

---

## Validation Criteria

### Behavioral Equivalence Tests

1. **Same plan prompts**: ContextBundle.ledger_summary produces identical XML to current loop_messages rendering.

2. **Same step IDs**: GoalNode.steps[].id uses same composite format (KFA-01) as current PlanDAG.

3. **Same evidence accumulation**: StepExecution records identical metrics to current StepResult.

4. **Same checkpoint recovery**: ExecutionCheckpoint + CE recovery produces same state as current checkpoint.

### Performance Benchmarks

1. **CE property access latency**: O(1) dict lookup, < 1ms per property.

2. **Checkpoint size reduction**: 70-80% smaller than RFC-216 checkpoint.

3. **Recovery time**: CE.load() + ExecutionCheckpoint < 500ms.

### Integration Tests

1. **Solo mode execution**: StrangeLoop with ExecutionState completes goal.

2. **Autopilot mode**: Job operations on CE GoalNode.

3. **Crash recovery**: Daemon restart → CE.load() → resume execution.

4. **Desktop app**: Job DAG visualization via ce.goal_subtree().

---

## Related RFCs

| RFC | Relationship |
|-----|--------------|
| RFC-624 | ContextEngine base design |
| RFC-625 | GoalEngine deletion, Goal field migration |
| RFC-203 | LoopState origin (replaced by ExecutionState) |
| RFC-216 | Checkpoint tree origin (trimmed to ExecutionCheckpoint) |
| RFC-228 | Job IPC commands (operate on CE GoalNode) |
| RFC-222 | Autopilot architecture (Job = root GoalNode) |
| RFC-221 | LoopRunner protocol (checkpoint recovery) |

---

## Terminology

| Term | Definition | Source |
|------|------------|--------|
| **ExecutionState** | Thin facade holding execution-only fields, backed by CE GoalNode properties | RFC-626 §1 |
| **WaveMetrics** | Last wave execution metrics for Plan decisions | RFC-626 §1 |
| **Job** | Root GoalNode with parent_id=None, operated on directly by CE | RFC-228 §44, RFC-626 §2 |
| **ExecutionCheckpoint** | Trimmed checkpoint (schema 5.0) for execution recovery, goal/step state in CE | RFC-626 §4 |
| **LedgerManager** | Sole ledger write target, phase-filtered message retrieval | RFC-624 §4 |
| **ContextBundle** | Structured projection output from CE | RFC-624 §3 |

---

## Appendix: Field Migration Matrix

| Field | LoopState (RFC-203) | ExecutionState | GoalNode |
|-------|--------------------|----------------|----------|
| `loop_id` | ✓ | ✓ (facade) | ✗ |
| `thread_id` | ✓ | ✓ (facade) | ✓ |
| `current_goal_id` | ✓ (derived) | ✓ (facade key) | ✓ (id) |
| `iteration` | ✓ | ✗ (CE property) | ✓ (max_iterations) |
| `max_iterations` | ✓ | ✓ (config) | ✗ (execution) |
| `total_tokens_used` | ✓ | ✗ (CE property) | ✓ |
| `wave_metrics.*` | ✓ (spread) | ✓ (WaveMetrics) | ✗ |
| `previous_plan` | ✓ | ✗ (CE property) | ✓ |
| `loop_messages` | ✓ (list) | ✗ (LedgerManager) | ✗ |
| `action_history` | ✓ | ✗ (CE property) | ✓ |

**ExecutionState holds**: loop_id, max_iterations, WaveMetrics, facade keys
**GoalNode holds**: thread_id, iteration, tokens, plan, action_history
**LedgerManager holds**: all messages (no backup list)