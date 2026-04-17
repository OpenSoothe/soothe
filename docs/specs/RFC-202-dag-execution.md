# RFC-202: DAG Execution & Failure Recovery

**Status**: Deprecated
**Authors**: Xiaming Chen
**Created**: 2026-03-31
**Last Updated**: 2026-04-12
**Depends on**: `RFC-200-autonomous-goal-management.md` (GoalEngine), `RFC-201-agentloop-plan-execute-loop.md` (AgentLoop), RFC-100 (CoreAgent)
**Supersedes**: RFC-0009, RFC-0010
**Kind**: Architecture Design
**Redirect**: Superseded by `RFC-201-agentloop-plan-execute-loop.md` and `RFC-203-agentloop-state-memory.md`

---

## 1. Abstract

This RFC defines the DAG-based execution architecture for Soothe's cognition layer, enabling parallel execution of independent plan steps and goals within configurable limits. It also specifies the failure recovery mechanism with progressive persistence, checkpointing after each step/goal completion, and structured artifact storage for human-browsable run outputs.

---

## Implementation Status

This RFC's core architecture is fully implemented:

- ✅ **ConcurrencyController** (§5.1)
  - Hierarchical semaphore control at goal, step, and LLM levels
  - Unlimited mode handling (limit=0 creates no semaphore)
  - Global LLM budget circuit breaker
  - Implementation: `src/soothe/core/concurrency.py`
  
- ✅ **StepScheduler** (§5.2)
  - DAG-based step scheduling with dependency resolution
  - Cycle detection in step dependencies
  - ready_steps() with sequential/dependency/max modes
  - Transitive failure propagation to blocked steps
  - Implementation: `src/soothe/core/step_scheduler.py`
  
- ✅ **RunArtifactStore** (§5.5)
  - Structured run directory: `$SOOTHE_HOME/runs/{thread_id}/`
  - Atomic checkpoint writes (tmp → rename)
  - StepReport and GoalReport in JSON + Markdown
  - Artifact tracking with manifest
  - Implementation: `src/soothe/core/artifact_store.py`
  
- ✅ **CheckpointEnvelope** (§8.1)
  - Progressive checkpoint model
  - Goal/plan/step state serialization
  - Recovery restoration
  - Implementation: `src/soothe/protocols/planner.py`

- ✅ **Recovery Flow** (§9)
  - Thread resume from checkpoint
  - Crash mid-step-loop recovery
  - Crash mid-goal-DAG recovery
  - Implementation: `src/soothe/core/runner/_runner_checkpoint.py`

- ⚠️ **GoalEngine AgentLoop Integration** (IG-154)
  - Previous: GoalEngine bypassed AgentLoop (architectural violation)
  - Fixed: GoalEngine now delegates to AgentLoop properly (IG-154)
  - After IG-154: GoalEngine integrates with StepScheduler correctly

**Verification**: All core modules are in production use. See code locations above for implementation details.

---

## 2. Scope and Non-Goals

### 2.1 Scope

This RFC defines:

* DAG-based scheduling for steps (within plan) and goals (across plans)
* Concurrency hierarchy with `ConcurrencyController`
* Parallel execution modes (sequential, dependency, max)
* Progressive checkpointing and recovery flow
* Structured artifact storage layout
* Cross-validated final report synthesis

### 2.2 Non-Goals

This RFC does **not** define:

* Goal management lifecycle (see RFC-200)
* Single-goal execution loop (see RFC-200)
* CoreAgent runtime (see RFC-100)
* PlannerProtocol interface (see RFC-301)

---

## 3. Background & Motivation

### 3.1 Execution Problems

| Problem | Current State | Target |
|---------|---------------|--------|
| Plan step iteration | Only step[0] tracked | All steps executed |
| ConcurrencyPolicy | Orphaned, never read | Active control |
| Goal parallelism | Serial `next_goal()` | DAG scheduling |
| Resource protection | No circuit breaker | Global LLM budget |
| Crash recovery | All progress lost | Resume from checkpoint |
| Artifact storage | Untracked in CWD | Structured per-run directory |

### 3.2 Design Goals

1. Execute all plan steps via runner-driven step loop
2. Activate ConcurrencyPolicy for actual execution control
3. DAG-based scheduling for steps and goals
4. Progressive persistence after each step/goal completion
5. Recovery from crash with checkpoint restoration
6. Structured artifacts in `$SOOTHE_HOME/runs/{thread_id}/`

---

## 4. Architecture Overview

### 4.1 Concurrency Hierarchy

```
Level 0: Pre-Stream IO          -- asyncio.gather (memory + context)
Level 1: Goal Scheduling        -- ConcurrencyController.goal_semaphore
  Level 2: Step Scheduling      -- ConcurrencyController.step_semaphore
    Level 3: Agent Turn         -- ConcurrencyController.llm_semaphore
      Level 4a: Tool Calls      -- LangGraph-native
      Level 4b: Subagent Calls  -- LangGraph-native
```

Each level nests inside the one above. The `global_max_llm_calls` semaphore acts as a cross-level circuit breaker.

### 4.2 Step vs Goal Parallelism

| Dimension | Step Parallelism | Goal Parallelism |
|-----------|-----------------|-----------------|
| Scope | Within single goal's plan | Across independent goals |
| Mode | Both autonomous and non-autonomous | Autonomous only |
| Thread model | Parent thread_id (RFC-207) | `{tid}__goal_{gid}` |
| DAG source | `PlanStep.depends_on` | `Goal.depends_on` |
| Typical scale | 1-5 parallel steps | 1-3 parallel goals |

### 4.3 Autonomous vs Non-Autonomous Mode

| Dimension | Non-Autonomous | Autonomous |
|-----------|---------------|------------|
| Goal creation | Single implicit goal | GoalEngine creates/manages |
| Iteration | Single pass | Outer goal loop with reflection |
| Goal parallelism | N/A | Parallel via GoalDAG |
| Reflection | Informational only | Drives revision and new goals |

---

## 5. Components

### 5.1 ConcurrencyController

Central concurrency coordinator using `asyncio.Semaphore`.

```python
class ConcurrencyController:
    def __init__(self, policy: ConcurrencyPolicy) -> None:
        # Create semaphores for positive limits
        # 0 = unlimited (no semaphore, pass-through)

    @asynccontextmanager
    async def acquire_goal(self) -> AsyncGenerator[None, None]: ...

    @asynccontextmanager
    async def acquire_step(self) -> AsyncGenerator[None, None]: ...

    @asynccontextmanager
    async def acquire_llm_call(self) -> AsyncGenerator[None, None]: ...

    @property
    def has_goal_limit(self) -> bool: ...  # True if limited
    @property
    def has_step_limit(self) -> bool: ...
    @property
    def has_llm_limit(self) -> bool: ...
```

### 5.2 StepScheduler

DAG-based step scheduler, created per plan execution.

```python
class StepScheduler:
    def __init__(self, plan: Plan) -> None: ...

    def ready_steps(self, limit: int = 0) -> list[PlanStep]:
        """Returns steps whose dependencies are all completed."""

    def mark_completed(self, step_id: str, result: str) -> None: ...
    def mark_failed(self, step_id: str, error: str) -> None: ...
    def is_complete(self) -> bool: ...
    def summary(self) -> dict[str, Any]: ...
```

**Parallelism modes** (from `ConcurrencyPolicy.step_parallelism`):

| Mode | Behavior |
|------|----------|
| `sequential` | Always returns 1 step |
| `dependency` | All deps-met steps up to limit |
| `max` | All non-blocked steps eligible |

### 5.3 Enhanced GoalEngine

```python
class Goal(BaseModel):
    # ... existing fields ...
    depends_on: list[str] = []
    report: GoalReport | None = None

class GoalEngine:
    async def ready_goals(self, limit: int = 1) -> list[Goal]:
        """Goals whose depends_on are all completed."""

    def is_complete(self) -> bool: ...
```

### 5.4 ConcurrencyPolicy

```python
class ConcurrencyPolicy(BaseModel):
    max_parallel_goals: int = 1           # 0 = unlimited
    max_parallel_steps: int = 1           # 0 = unlimited
    max_parallel_subagents: int = 1       # Reserved for future
    max_parallel_tools: int = 3           # Reserved for future
    global_max_llm_calls: int = 5         # Cross-level circuit breaker
    step_parallelism: Literal["sequential", "dependency", "max"] = "dependency"
```

### 5.5 RunArtifactStore

```python
class RunArtifactStore:
    """Manages $SOOTHE_HOME/runs/{thread_id}/ directory."""

    def ensure_step_dir(self, goal_id: str, step_id: str) -> Path: ...
    def write_step_report(self, goal_id: str, step: PlanStep, duration_ms: int) -> None: ...
    def write_goal_report(self, report: GoalReport) -> None: ...
    def record_artifact(self, entry: ArtifactEntry) -> None: ...
    def save_checkpoint(self, envelope: CheckpointEnvelope) -> None: ...
    def load_checkpoint(self) -> CheckpointEnvelope | None: ...
    def save_manifest(self) -> None: ...
```

---

## 6. Data Flow

### 6.1 Non-Autonomous Execution Flow

```
User Input → Pre-Stream → StepScheduler.init(plan)
    |
    v
while not scheduler.is_complete():
    ready = scheduler.ready_steps(limit=max_parallel_steps)
    |
    +-- if len(ready) == 1 and step_parallelism != "max":
    |       Execute on main thread (sequential)
    |
    +-- else:
    |       asyncio.gather(*[_execute_step(step) for step in ready])
    |
    +-- For each completed:
    |       scheduler.mark_completed(step.id, result)
    |       ContextProtocol.ingest(step_result)
    |       artifact_store.write_step_report()
    |       artifact_store.save_checkpoint()
    |
    +-- For each failed:
            scheduler.mark_failed(step.id, error)
            Dependent steps become blocked
    |
    v
Post-Stream (reflect, persist final)
```

### 6.2 Autonomous Execution Flow

```
User Input → Pre-Stream → GoalEngine.create_goal(user_input)
    |
    v
while not goal_engine.is_complete() and iterations < max:
    ready_goals = goal_engine.ready_goals(limit=max_parallel_goals)
    |
    +-- asyncio.gather(*[_execute_goal(goal) for goal in ready_goals])
    |
    +-- For each goal:
    |       1. Create plan via PlannerProtocol
    |       2. Run StepScheduler loop (same as non-autonomous)
    |       3. Reflect on results
    |       4. If should_revise: revise plan, continue
    |       5. Else: complete goal, generate GoalReport
    |       6. artifact_store.write_goal_report()
    |       7. artifact_store.save_checkpoint()
    |
    +-- iterations++
    |
    v
Persist final state, synthesize cross-validated report
```

---

## 7. Storage Layout

```
$SOOTHE_HOME/
  runs/{thread_id}/               # Per-run directory
    conversation.jsonl            # Conversation log
    checkpoint.json               # CheckpointEnvelope
    manifest.json                 # Artifact index
    goals/
      {goal_id}/
        report.json               # GoalReport (machine-readable)
        report.md                 # Human-readable summary
        steps/
          {step_id}/
            report.json           # StepReport
            report.md             # Human-readable output
            artifacts/            # Produced files (copied)
  durability/data/                # Thread metadata + index
    thread_{thread_id}.json
    thread_index.json
  logs/soothe.log                 # Global log
```

---

## 8. Abstract Schemas

### 8.1 CheckpointEnvelope

```python
class CheckpointEnvelope(BaseModel):
    version: int = 1
    timestamp: str = ""
    mode: Literal["single_pass", "autonomous"] = "single_pass"
    last_query: str = ""
    thread_id: str = ""
    goals: list[dict[str, Any]] = []      # GoalEngine snapshot
    active_goal_id: str | None = None
    plan: dict[str, Any] | None = None    # Serialized Plan
    completed_step_ids: list[str] = []
    total_iterations: int = 0
    status: Literal["in_progress", "completed", "failed"] = "in_progress"
```

### 8.2 ArtifactEntry

```python
class ArtifactEntry(BaseModel):
    path: str                           # Relative to run dir
    source: Literal["produced", "reference"]
    original_path: str = ""             # Workspace path for references
    tool_name: str = ""
    step_id: str = ""
    goal_id: str = ""
    size_bytes: int = 0
```

### 8.3 RunManifest

```python
class RunManifest(BaseModel):
    version: int = 1
    thread_id: str
    created_at: str
    updated_at: str
    query: str = ""
    mode: Literal["single_pass", "autonomous"] = "single_pass"
    status: Literal["in_progress", "completed", "failed"] = "in_progress"
    goals: list[str] = []
    artifacts: list[ArtifactEntry] = []
```

### 8.4 StepReport

```python
class StepReport(BaseModel):
    step_id: str
    description: str
    status: Literal["completed", "failed", "skipped"]
    result: str = ""
    duration_ms: int = 0
    depends_on: list[str] = []
```

### 8.5 GoalReport

```python
class GoalReport(BaseModel):
    goal_id: str
    description: str
    step_reports: list[StepReport] = []
    summary: str = ""
    status: Literal["completed", "failed"] = "completed"
    duration_ms: int = 0
    reflection_assessment: str = ""
    cross_validation_notes: str = ""
```

---

## 9. Recovery Flow

### 9.1 Thread Resume

```
Thread Resume (_pre_stream):
  1. resume_thread(thread_id)
  2. context.restore(thread_id)
  3. envelope = artifact_store.load_checkpoint()
  4. if envelope and envelope.status == "in_progress":
       goal_engine.restore_from_snapshot(envelope.goals)
       plan = Plan.model_validate(envelope.plan)
       mark completed steps from envelope.completed_step_ids
       emit soothe.recovery.resumed
  5. StepScheduler.ready_steps() skips completed steps
```

### 9.2 Recovery Scenarios

**Crash mid-step-loop:**
```
Before crash:
  Step 1: completed (checkpoint saved)
  Step 2: completed (checkpoint saved)
  Step 3: in_progress (not saved)
  Step 4: pending

After resume:
  Step 1-2: restored from checkpoint
  Step 3-4: re-executed
```

**Crash mid-goal-DAG:**
```
Before crash:
  Goal A: completed
  Goal B: in_progress, Step 1 done, Step 2 in_progress
  Goal C: pending (depends on A, B)

After resume:
  Goal A: restored, report on disk
  Goal B: active, Step 1 restored, Step 2+ pending
  Goal C: pending (deps not met)
```

---

## 10. Stream Events

| Type | Fields | Description |
|------|--------|-------------|
| `soothe.plan.step_started` | step_id, description, depends_on, batch_index | Step began |
| `soothe.plan.step_completed` | step_id, success, result_preview, duration_ms | Step finished |
| `soothe.plan.step_failed` | step_id, error, blocked_steps | Step failed |
| `soothe.plan.batch_started` | batch_index, step_ids, parallel_count | Parallel batch launched |
| `soothe.goal.batch_started` | goal_ids, parallel_count | Goal batch (autonomous) |
| `soothe.goal.report` | goal_id, step_count, completed, failed, summary | Goal report |
| `soothe.recovery.resumed` | thread_id, completed_steps, completed_goals, mode | Resumed from checkpoint |
| `soothe.checkpoint.saved` | thread_id, completed_steps, completed_goals | Checkpoint saved |

---

## 11. Configuration

```yaml
execution:
  concurrency:
    max_parallel_goals: 1        # 0 = unlimited
    max_parallel_steps: 1        # 0 = unlimited
    max_parallel_subagents: 1    # Reserved
    max_parallel_tools: 3        # Reserved
    global_max_llm_calls: 5      # Circuit breaker
    step_parallelism: dependency # sequential | dependency | max

  recovery:
    progressive_checkpoints: true
    auto_resume_on_start: false
```

**Unlimited mode** (limit=0): No semaphore created, pass-through execution.

---

## 12. Invariants and Constraints

### 12.1 Architectural Invariants

| Invariant | Meaning | Consequence of Violation |
|-----------|---------|-------------------------|
| Global LLM budget | Total concurrent calls ≤ `global_max_llm_calls` | API rate-limit exhaustion |
| Step dependency | Dependent steps wait for predecessors | Blocked steps marked failed transitively |
| Goal isolation | Parallel goals have isolated context | State corruption between goals |
| Checkpoint atomicity | Write to tmp, then rename | Partial checkpoint on crash |

### 12.2 Dependency Constraints

| Constraint | Rule |
|------------|------|
| LangGraph integration | Reuse `_stream_phase()` per step, no internal modifications |
| Thread branching | Parallel steps use parent thread_id (RFC-207); goals use `{tid}__goal_{gid}` |
| Storage separation | DurabilityProtocol = lifecycle; RunArtifactStore = artifacts |

---

## 13. Relationship to Other RFCs

* **`RFC-200-autonomous-goal-management.md` (Layer 3)**: GoalEngine and autonomous goal management
* **`RFC-201-agentloop-plan-execute-loop.md` (Layer 2)**: Agentic goal execution loop
* **RFC-100 (Layer 1)**: CoreAgent runtime
* **RFC-301 (Protocol Registry)**: PlannerProtocol interface
* **RFC-300 (Context & Memory)**: ContextProtocol for step result ingestion

---

## 14. Open Questions

1. Should `max_parallel_tools` and `max_parallel_subagents` be enforced via middleware?
2. Cross-validated synthesis: should confidence scoring be mandatory?
3. Daemon restart: auto-resume incomplete threads or prompt user?

---

## 15. Conclusion

This RFC unifies DAG-based execution and failure recovery into a coherent architecture:

- Concurrency hierarchy controls parallel execution at multiple levels
- Progressive persistence enables crash recovery with minimal re-execution
- Structured artifacts provide human-browsable run outputs
- Cross-validated reports synthesize findings from parallel paths

> **DAG enables parallelism; checkpoints enable resilience.**