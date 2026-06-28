# ContextEngine

Unified context management for goals, steps, ledger, and projection.

---

## Overview

ContextEngine (`soothe.foundation.context`) provides autonomous goal management for long-running complex workflows. It manages goal DAGs with dependencies, priorities, and dynamic restructuring capabilities. ContextEngine composes GoalStepDAG, LedgerManager, SemanticLoader, ProjectionEngine, and a pluggable persistence backend into a single interface.

**RFC**: [RFC-624](../../specs/RFC-624-context-engine.md) (Context Engine), [RFC-625](../../specs/RFC-625-autopilot-monitor-context-engine-unification.md) (Autopilot-Monitor-ContextEngine unification)

---

## Architecture

### Goal DAG Management

ContextEngine manages goals as a Directed Acyclic Graph (DAG):

```
ContextEngine Architecture
├─ GoalStepDAG
│  ├─ Goals with dependencies
│  ├─ Priority-based scheduling
│  └─ Dynamic restructuring
│
├─ Goal Lifecycle
│  ├─ pending → active → completed
│  ├─ Backoff reasoning
│  └─ Failure handling
│
├─ Goal Execution
│  ├─ PERFORM delegation (StrangeLoop)
│  ├─ REFLECT evaluation
│  └─ DAG update
│
├─ Step DAG
│  ├─ Steps per goal
│  ├─ Dependency satisfaction
│  └─ Completion tracking
│
├─ LedgerManager
│  ├─ Message history
│  └─ Phase filtering
│
├─ ProjectionEngine
│  ├─ Bounded context projection
│  └─ Prompt template injection
│
└─ Planning Submodule
   ├─ StepPlanningSubengine
   ├─ GoalPlanningSubengine
   └─ GoalScheduler
```

---

## Core Concepts

### GoalStepDAG

Goals organized as a directed acyclic graph with embedded step DAGs:

```python
class GoalStepDAG:
    """Unified Goal+Step DAG."""

    goals: dict[str, GoalNode]      # Goal registry

    def add_goal(self, goal: GoalNode): ...
    def get_goal(self, goal_id: str) -> GoalNode | None: ...
    def complete_goal(self, goal_id: str): ...
    def fail_goal(self, goal_id: str, error: str): ...
    def snapshot(self) -> GoalStepDAGSnapshot: ...
```

### GoalNode

Individual goal in the DAG:

```python
class GoalNode:
    """Single goal in the unified Goal+Step DAG."""

    # Core identity
    id: str                        # Goal identifier (auto-generated)
    description: str               # Goal description
    priority: int                  # Execution priority (0-100, default 50)
    status: GoalStatus             # pending, active, completed, failed, etc.

    # DAG relationships
    parent_id: str | None          # Parent goal ID
    depends_on: list[str]          # Hard dependency goal IDs
    informs: list[str]             # Informs relationships
    conflicts_with: list[str]      # Conflict relationships

    # Embedded step DAG
    steps: StepDAG                 # Steps for this goal

    # Lineage
    generating_reasoning: str | None
    source: str                    # user, directive, file_discovery, decomposition

    # Execution tracking
    iteration_count: int           # Current iteration number
    total_tokens_used: int
    total_duration_ms: int
    max_iterations: int            # 0 = no cap
    thread_id: str | None
    assigned_loop_id: str | None
    action_history: list[str]

    # Retry/backoff
    retry_count: int
    max_retries: int               # Default 2
    send_back_count: int
    max_send_backs: int            # Default 3
    attempts_after_crash: int

    # Workspace/source
    source_file: str | None        # GOAL.md path if file-sourced
    workspace: str | None          # Autopilot dispatch workspace

    # Completion state
    report: dict[str, Any] | None  # Serialized GoalReport on completion
    error: str | None              # Failure reason
    pending_clarification: dict[str, Any] | None  # RFC-622

    # Dreaming (RFC-625)
    topic: str | None              # Topic tag for cross-loop dreaming
    findings: list[str]            # Key findings from execution
```

### GoalStatus

Lifecycle states:

```python
GoalStatus = Literal[
    "pending",                    # Initial state
    "active",                     # Activated for execution
    "completed",                  # Successfully finished
    "failed",                     # Execution failed
    "suspended",                  # Temporarily suspended
    "blocked",                    # Blocked by dependency
    "validated",                  # Validated
    "awaiting_clarification",     # Awaiting user clarification (RFC-622)
    "cancelled",                  # Cancelled by user
]

TERMINAL_STATES = frozenset({"completed", "failed", "cancelled"})
BLOCKED_STATES = frozenset({"awaiting_clarification", "suspended"})
```

---

## Goal Lifecycle

### 1. Goal Creation

Create goals with dependencies:

```python
# Create simple goal
goal = await engine.create_goal(
    description="Analyze codebase structure",
    priority=50
)

# Create goal with dependencies
goal = await engine.create_goal(
    description="Implement feature",
    depends_on=["goal-123"],  # Wait for analysis
    priority=80
)
```

### 2. Goal Activation

Activate a pending goal:

```python
await engine.activate_goal(goal_id, loop_id="loop-abc")
# Transitions goal from "pending" to "active"
```

### 3. Goal Completion

Handle goal completion:

```python
await engine.complete_goal(goal_id)
# Transitions goal to "completed" terminal state
```

### 4. Goal Failure

Handle goal failure with retry support:

```python
await engine.fail_goal(
    goal_id,
    error="Tool execution timed out",
    evidence=evidence_bundle,
    allow_retry=True  # Allow retry if retries remain
)
```

### 5. Goal Suspension/Blocking

Suspend or block goals:

```python
await engine.suspend_goal(goal_id, reason="waiting for external API")
await engine.block_goal(goal_id)    # Block by dependency
await engine.unblock_goal(goal_id)  # Unblock back to pending
```

### 6. Goal Cancellation

Cancel a goal (terminal state):

```python
await engine.cancel_goal(goal_id, reason="user_cancelled")
```

---

## Event System

ContextEngine fires callbacks for lifecycle events:

```python
EngineEvent = Literal[
    "goal_created",
    "goal_activated",
    "goal_completed",
    "goal_failed",
    "goal_suspended",
    "goal_cancelled",
    "goal_blocked",
    "goal_unblocked",
    "step_completed",
    "step_failed",
    "step_skipped",
]

# Register callbacks
engine.on("goal_completed", lambda goal_id: print(f"Done: {goal_id}"))
engine.off("goal_completed", callback)
```

---

## Planning Submodule

ContextEngine exposes a planning facade:

```python
engine.planning.step    # StepPlanningSubengine
engine.planning.goal    # GoalPlanningSubengine
engine.planning.scheduler  # GoalScheduler
```

---

## Projection

Bounded context projection for prompt template injection:

```python
engine.ledger  # LedgerManager access

# Get DAG snapshot
snapshot = engine.get_dag_snapshot()

# Get step DAG for a goal
step_dag = engine.get_step_dag(goal_id)

# Get ledger entries (optionally filtered by phase)
entries = engine.get_ledger_entries(phases=["plan", "execute"])

# Get all goals
all_goals = engine.get_all_goals()

# Get goal lineage
lineage = engine.get_goal_lineage(goal_id)
```

---

## Configuration

### ContextEngine Settings

Projection limits are configured under `agent.loop.context_engine`:

```yaml
agent:
  loop:
    context_engine:  # Projection limits for prompt template context injection
      projection_max_goals: 5
      projection_max_steps_per_goal: 10
      projection_max_ledger_chars: 4000
      projection_max_ledger_messages: 20
      projection_max_lineage_chars: 2000
      projection_max_project_instructions_chars: 8000
```

The persistence backend follows `persistence.default_backend` — no separate configuration needed. When the global backend is `postgresql`, ContextEngine uses PgsqlContextPersistence with the same DSN. When `sqlite` (default), it uses SqliteContextPersistence.

---

## Related Documentation

- **[StrangeLoop](strangeloop.md)** - Goal execution integration
- **[SootheRunner](runner.md)** - Runner orchestration
- **[RFC-624](../../specs/RFC-624-context-engine.md)** - Context Engine specification
- **[RFC-625](../../specs/RFC-625-autopilot-monitor-context-engine-unification.md)** - Autopilot unification

---

## API Reference

### ContextEngine Class

```python
class ContextEngine:
    """Unified context management for goals, steps, ledger, and projection."""

    def __init__(
        self,
        persistence: Any | None = None,        # Defaults to in-memory SQLite
        projection_config: ProjectionConfig | None = None,
        soothe_home: Path | None = None,
        workspace: Path | None = None,
    ) -> None: ...

    # Callback mechanism
    def on(self, event: EngineEvent, callback: Callable) -> None: ...
    def off(self, event: EngineEvent, callback: Callable) -> None: ...

    # Public read API
    def get_dag_snapshot(self) -> GoalStepDAGSnapshot: ...
    def get_step_dag(self, goal_id: str) -> StepDAG | None: ...
    def get_ledger_entries(self, phases: list[str] | None = None) -> list[tuple[BaseMessage, str | None]]: ...
    def get_all_goals(self) -> list[GoalNode]: ...
    def get_goal_lineage(self, goal_id: str) -> list[str]: ...
    def get_goal_sync(self, goal_id: str) -> GoalNode | None: ...

    # Properties
    @property
    def ledger(self) -> LedgerManager: ...
    @property
    def planning(self) -> PlanningFacade: ...

    # Goal management
    async def create_goal(self, description: str, *, priority: int = 50, parent_id: str | None = None, depends_on: list[str] | None = None, ...) -> GoalNode: ...
    async def get_goal(self, goal_id: str) -> GoalNode | None: ...
    async def list_goals(self, status: str | None = None) -> list[GoalNode]: ...
    async def activate_goal(self, goal_id: str, loop_id: str | None = None) -> None: ...
    async def complete_goal(self, goal_id: str) -> None: ...
    async def fail_goal(self, goal_id: str, error: str | None = None, *, evidence: Any | None = None, allow_retry: bool = True) -> None: ...
    async def suspend_goal(self, goal_id: str, reason: str) -> None: ...
    async def cancel_goal(self, goal_id: str, *, reason: str = "user_cancelled") -> None: ...
    async def block_goal(self, goal_id: str) -> None: ...
    async def unblock_goal(self, goal_id: str) -> None: ...
    async def finalize_goal(self, goal_id: str, *, status: str = "completed") -> None: ...

    # Step/iteration tracking
    def record_action(self, goal_id: str, action: str) -> None: ...
    def increment_iteration(self, goal_id: str) -> int: ...
```

### GoalNode Class

```python
class GoalNode:
    """Single goal in the unified Goal+Step DAG."""
    id: str
    description: str
    priority: int
    status: GoalStatus
    parent_id: str | None
    depends_on: list[str]
    steps: StepDAG
    iteration_count: int
    max_iterations: int
    assigned_loop_id: str | None
    # ... (see source for full field list)
```

---

## See Also

- **[Autonomous Mode](../autonomous-mode.md)** - User guide
- **[Thread Management](../thread-management.md)** - Thread handling
- **[Daemon Architecture](../daemon-management.md)** - Daemon overview
