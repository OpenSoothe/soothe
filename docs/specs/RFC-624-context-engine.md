# RFC-624: Context Engine

**RFC**: 624
**Title**: Context Engine — Unified Context Management for Goals, Steps, and Projection
**Status**: Draft
**Kind**: Architecture Design
**Created**: 2026-06-12
**Dependencies**: RFC-000 (System Conceptual Design), RFC-200 (Autonomous Goal Management), RFC-201 (AgentLoop Plan-Execute Loop), RFC-214 (Loop Message Surface), RFC-215 (Persistence Backend)
**Related**: RFC-217 (Goal Context Management), RFC-224 (Automatic Context Window Management), RFC-222 (Autopilot GoalEngine Architecture)

---

## Abstract

This RFC introduces `ContextEngine`, a unified interface for context management across Soothe's GoalEngine (goal-level) and AgentLoop (execution-level). ContextEngine consolidates scattered context handling — goal DAG, step DAG, message ledger, working memory, and project instructions — into a single module with clear ownership boundaries. It provides a unified Goal+Step DAG data structure with lineage tracking, a bounded projection mechanism that outputs structured data for prompt templates, and pluggable persistence. Phase 1 delivers ContextEngine as a standalone module in `soothe.context` with no changes to existing GoalEngine or AgentLoop; later phases wire it in as a replacement for their internal context storage.

---

## Problem Statement

### Current State

Soothe's context handling is scattered across multiple modules with overlapping responsibilities:

1. **GoalEngine** (`autopilot/engine/engine.py`) owns a flat `dict[str, Goal]` for goal DAG management — scheduling, status transitions, dependencies. Goals carry no lineage (why they were created) and no execution records.

2. **AgentLoop** maintains `PlanDAG` (step-level DAG), `LoopWorkingMemory` (step outcome summaries), and `loop_messages` (full message ledger). These are separate data structures with no unified model.

3. **Autopilot Context** has `GoalDispatchContextStore` + `ContextProjector` for parent goal contributions — a partial context projection mechanism limited to autopilot mode.

4. **No lineage tracking**: Neither goals nor steps record the reasoning that created them. After crash recovery, the "why" behind decisions is lost.

5. **No unified projection**: Context projection is ad-hoc — `plan_ledger_projection.py` handles ledger trimming, `GoalContextManager` handles goal context injection, `ContextProjector` handles parent contributions. Each operates on different data with different bounding strategies.

### Goals

1. **Unified data model**: A single Goal+Step DAG that replaces scattered goal storage, step DAG, and working memory.
2. **Lineage tracking**: Goals and steps record their generating reasoning, enabling context projection to show *why* decisions were made.
3. **Structured projection**: A single `ContextBundle` data model output by ContextEngine, rendered by existing prompt templates.
4. **Standalone development**: Phase 1 builds ContextEngine without modifying existing code.
5. **Migration path**: Clear phases for wiring ContextEngine into GoalEngine and AgentLoop as a replacement.

### Non-Goals

- ContextEngine is independent from `ContextProtocol` (RFC-000), which remains the orchestrator's cognitive knowledge ledger.
- Procedure memory (Skills, MCP tools) and episodic memory (distilled working history) are deferred.
- RAG / vector store integration is deferred.
- Postgres-backed persistence is deferred (in-memory and file backends in Phase 1).

---

## Solution

### Architecture Overview

```
┌──────────────────────────────────────────────────────────────┐
│ soothe.context (new standalone module)                        │
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │ ContextEngine                                             │ │
│  │  • GoalStepDAG: unified goal + nested step DAGs          │ │
│  │  • LedgerManager: loop message ledger                    │ │
│  │  • SemanticLoader: CLAUDE.md/AGENTS.md/MEMORY.md        │ │
│  │  • ProjectionEngine: builds ContextBundle                │ │
│  │  • PersistenceBackend: durability (pluggable)            │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                                │
│  Data Models:                                                  │
│  • GoalNode, StepNode, StepExecution                          │
│  • GoalStepDAG, StepDAG                                       │
│  • ContextBundle (projection output)                          │
│  • GoalStepDAGSnapshot (persistence format)                   │
└──────────────────────────────────────────────────────────────┘
          ↓ ContextBundle (structured data)
┌──────────────────────────────────────────────────────────────┐
│ Prompt Templates (existing, unchanged at this phase)          │
└──────────────────────────────────────────────────────────────┘
          ↓ Rendered messages
┌──────────────────────────────────────────────────────────────┐
│ CoreAgent (existing, unchanged at this phase)                 │
└──────────────────────────────────────────────────────────────┘
```

### Integration Path

| Phase | Scope | Existing code changes |
|-------|-------|-----------------------|
| 1 (this RFC) | Standalone `soothe.context` module | None |
| 2 | GoalEngine reads/writes through ContextEngine | GoalEngine internal storage replaced |
| 3 | AgentLoop uses ContextEngine for plan/ledger | PlanDAG, LoopWorkingMemory, loop_messages replaced |

---

## Specification

### §1 Status Types

```python
GoalStatus = Literal[
    "pending", "active", "completed", "failed",
    "suspended", "blocked", "validated",
    "awaiting_clarification", "cancelled",
]

TERMINAL_STATES = frozenset({"completed", "failed", "cancelled"})

StepStatus = Literal["pending", "completed", "failed", "skipped"]
```

`GoalStatus` aligns with existing `GoalEngine` status values (RFC-200, RFC-204). `TERMINAL_STATES` mirrors `autopilot/engine/models.py` — goals in these states satisfy dependency checks. Note that `failed` and `cancelled` are terminal: a goal whose dependency failed is considered "ready" (it will discover the failure during execution).

`StepStatus` includes `"skipped"` for steps that were bypassed during replanning, matching `PriorStepSummary.outcome` and `StepSummary.outcome` in `autopilot/engine/models.py`.

### §2 GoalNode

```python
class GoalNode(BaseModel):
    """Single goal in the unified Goal+Step DAG."""

    id: str
    description: str
    priority: int = 50
    status: GoalStatus = "pending"

    # Nesting: goal can be subgoal of another goal
    parent_id: str | None = None

    # Dependencies: goal-level DAG edges
    depends_on: list[str] = Field(default_factory=list)

    # Soft dependencies and conflicts (RFC-204)
    informs: list[str] = Field(default_factory=list)
    conflicts_with: list[str] = Field(default_factory=list)

    # Nested step DAG (embedded, goal-scoped)
    steps: StepDAG = Field(default_factory=StepDAG)

    # Lineage: why this goal exists
    generating_reasoning: str | None = None
    source: Literal["user", "directive", "file_discovery", "decomposition"] = "user"

    # Observability
    total_tokens_used: int = 0
    thread_id: str | None = None
    assigned_loop_id: str | None = None

    # Timestamps
    created_at: datetime
    updated_at: datetime
```

**Design decisions**:

- **StepDAG embedded in GoalNode**: Steps are goal-scoped — no cross-goal step dependencies. Embedding makes `GoalNode` the atomic unit of persistence and matches the dependency model. A global step index can be added later as an optimization.
- **Lineage via `generating_reasoning`**: Stores the reasoning that produced this goal (e.g., plan-assess LLM output, directive text, user input). Enables context projection to show *why* a goal exists.
- **`source` field**: Tracks origin for observability and projection filtering.

### §3 StepNode and StepExecution

```python
class StepNode(BaseModel):
    """Single step within a goal's step DAG."""

    id: str
    description: str
    status: StepStatus = "pending"

    # Step-level dependencies (within same goal only)
    dependencies: list[str] = Field(default_factory=list)

    # Lineage: reasoning that generated this step
    plan_iteration: int = 0
    reasoning_trace: str | None = None

    # Execution record (populated after CoreAgent runs)
    execution: StepExecution | None = None


class StepExecution(BaseModel):
    """Record of CoreAgent execution for a step."""

    input_messages: list[dict] = Field(default_factory=list)
    output_messages: list[dict] = Field(default_factory=list)
    tokens_used: int = 0
    duration_ms: int = 0
    error: str | None = None
    thread_id: str | None = None
```

**Design decisions**:

- **`StepExecution.input_messages/output_messages` stored as serialized dicts** rather than `BaseMessage` objects, for persistence portability. At runtime, `LedgerManager` holds `BaseMessage` objects. When a step completes, `ContextEngine` serializes relevant messages into `StepExecution` for durability. On recovery, these dicts are deserialized back to `BaseMessage` to rehydrate the `LedgerManager`.
- **Step dependencies strictly within same goal** — cross-goal coordination flows through goal-level `depends_on`. Steps can depend on goal completion (not specific steps in other goals) via the goal dependency boundary.
- **`reasoning_trace`** captures the plan-assess or plan-generate reasoning that produced this step, enabling lineage projection.

### §4 StepDAG

```python
class StepDAG(BaseModel):
    """DAG of steps for a single goal."""

    nodes: dict[str, StepNode] = Field(default_factory=dict)

    def add_step(self, step: StepNode) -> None: ...

    def ready_steps(self) -> set[str]:
        """Pending steps whose dependencies are all satisfied.

        Uses dependency token expansion (mirrors
        ``expand_dependency_satisfaction_ids`` from
        ``loop/planning/dependency_tokens.py``) to resolve composite
        step IDs and their local numeric aliases.
        """
        ...

    def completed_steps(self) -> set[str]: ...
    def failed_steps(self) -> set[str]: ...
    def pending_steps(self) -> set[str]: ...

    def mark_completed(self, step_id: str, execution: StepExecution) -> None: ...
    def mark_failed(self, step_id: str, execution: StepExecution) -> None: ...
    def mark_skipped(self, step_id: str) -> None: ...

    @property
    def total_steps(self) -> int: ...
    @property
    def success_rate(self) -> float: ...
```

### §5 GoalStepDAG

```python
class GoalStepDAG(BaseModel):
    """Top-level DAG of goals, each containing nested step DAGs."""

    goals: dict[str, GoalNode] = Field(default_factory=dict)

    # Goal lifecycle
    def add_goal(self, goal: GoalNode) -> None: ...
    def get_goal(self, goal_id: str) -> GoalNode | None: ...
    def complete_goal(self, goal_id: str) -> None: ...
    def fail_goal(self, goal_id: str, error: str) -> None: ...
    def suspend_goal(self, goal_id: str, reason: str) -> None: ...

    # Scheduling (same logic as GoalEngine._filter_ready_candidates)
    def ready_goals(self, limit: int = 1) -> list[GoalNode]:
        """Goals whose deps are satisfied, sorted by priority desc / created_at asc."""
        ...

    def active_goals(self) -> list[GoalNode]: ...

    # Lineage
    def goal_lineage(self, goal_id: str) -> list[str]:
        """Return chain of goal descriptions from root to this goal."""
        ...

    # Snapshot for persistence
    def snapshot(self) -> GoalStepDAGSnapshot: ...
    def restore_from_snapshot(self, snapshot: GoalStepDAGSnapshot) -> None: ...

    # Recovery
    def recover_active_goals(self) -> list[str]:
        """Reset goals stuck in 'active' to 'pending' (crash recovery)."""
        ...
```

**Scheduling semantics**: `ready_goals()` mirrors `GoalEngine._filter_ready_candidates()` — filters by `status == "pending"` (goals in `suspended`, `awaiting_clarification`, or other non-pending states are excluded), checks hard dependencies (`depends_on` all in `TERMINAL_STATES`), checks conflicts (`conflicts_with` no active goal), sorts by `(-priority, created_at)`.

### §6 Context Projection

#### ContextBundle

```python
class ContextBundle(BaseModel):
    """Structured output of ContextEngine.project() for prompt templates.

    This is not a rendered string — it is structured data that prompt
    templates render into appropriate message sections.
    """

    # Goal context
    active_goal: GoalNode | None = None
    goal_progress: str = ""

    # Step context
    pending_steps: list[StepNode] = Field(default_factory=list)
    completed_steps: list[StepNode] = Field(default_factory=list)
    failed_steps: list[StepNode] = Field(default_factory=list)

    # Ledger context
    ledger_summary: str = ""
    ledger_messages: list[dict] = Field(default_factory=list)

    # Semantic context
    project_instructions: str = ""
    agent_instructions: str = ""
    memory_instructions: str = ""

    # Lineage context (for reasoning)
    goal_lineage: str = ""
    step_lineage: str = ""

    # Observability metadata
    total_tokens_used: int = 0
    goal_dag_summary: str = ""
```

#### ProjectionConfig

```python
class ProjectionConfig(BaseModel):
    """Limits for bounded projection."""

    max_goals: int = 5
    max_steps_per_goal: int = 10
    max_ledger_chars: int = 4000
    max_ledger_messages: int = 20
    max_lineage_chars: int = 2000
    max_project_instructions_chars: int = 8000
```

#### ProjectionEngine

```python
class ProjectionEngine:
    """Builds a ContextBundle from ContextEngine state, bounded by ProjectionConfig."""

    def __init__(self, config: ProjectionConfig | None = None) -> None: ...

    async def project(
        self,
        dag: GoalStepDAG,
        ledger: list[BaseMessage],
        goal_id: str | None = None,
    ) -> ContextBundle:
        """Build ContextBundle for a specific goal (or the active goal).

        Args:
            dag: Current GoalStepDAG state.
            ledger: Current loop message ledger.
            goal_id: Target goal. If None, uses the active goal.

        Returns:
            Bounded ContextBundle for prompt template rendering.
        """
        ...
```

**Bounding strategy per section**:

| Section | Source | Bounding strategy |
|---------|--------|-------------------|
| `active_goal` | GoalStepDAG | Single goal |
| `goal_progress` | StepDAG stats | Rendered summary, max 500 chars |
| `pending_steps` | StepDAG | Top-N by dependency order |
| `completed_steps` | StepDAG | Recent N, truncated descriptions |
| `ledger_summary` | LedgerManager | Condensed text, max `max_ledger_chars` |
| `project_instructions` | SemanticLoader | Raw content, max `max_project_instructions_chars` |
| `goal_lineage` | GoalStepDAG.goal_lineage() | Chain of descriptions, max `max_lineage_chars` |
| `step_lineage` | StepNode.reasoning_trace | Recent reasoning, max `max_lineage_chars` |

### §7 LedgerManager

Replaces `LoopWorkingMemory` and the `loop_messages` list in AgentLoop state.

```python
class LedgerManager:
    """Manages the loop message ledger with compaction support."""

    def __init__(self, max_inline_chars: int = 4000) -> None: ...

    def record_message(self, message: BaseMessage, phase: str) -> None:
        """Append a message to the ledger with phase metadata."""
        ...

    def get_messages(self, phases: list[str] | None = None) -> list[BaseMessage]:
        """Return messages, optionally filtered by phase."""
        ...

    def project_for_plan(self, config: ProjectionConfig | None = None) -> list[BaseMessage]:
        """Return ledger messages for plan prompts (all phases)."""
        ...

    def project_for_core_agent(self) -> list[BaseMessage]:
        """Return only execute_step phase messages for CoreAgent.

        Also includes non-loop plain HumanMessage/AIMessage objects
        (phase=None) for compatibility with early ledger entries.
        """
        ...

    def compact(self) -> None:
        """Compact old messages (summarize or spill to disk)."""
        ...

    def record_step_result(
        self,
        step_id: str,
        description: str,
        output: str | None,
        error: str | None,
        success: bool,
    ) -> None:
        """Record step outcome (replaces LoopWorkingMemory.record_step_result)."""
        ...
```

**Relationship between LedgerManager and DAG**: LedgerManager is the runtime fast path for message recording and phase-filtered retrieval. The DAG-based recovery is the persistence/durability path — after crash recovery, `StepExecution` data is deserialized back into `BaseMessage` objects and the LedgerManager is rehydrated. At runtime, LedgerManager and StepExecution are kept in sync by `ContextEngine`: recording a step completion writes to both.

### §8 SemanticLoader

```python
class SemanticLoader:
    """Loads static project instruction files for semantic context."""

    def __init__(self, soothe_home: Path | None = None) -> None: ...

    def load_project_instructions(self) -> str:
        """Load CLAUDE.md content."""
        ...

    def load_agent_instructions(self) -> str:
        """Load AGENTS.md content."""
        ...

    def load_memory(self) -> str:
        """Load MEMORY.md content."""
        ...
```

### §9 Persistence

#### ContextPersistenceProtocol

```python
class ContextPersistenceProtocol(Protocol):
    """Backend for GoalStepDAG and ledger durability."""

    async def save_dag(self, dag: GoalStepDAG) -> None: ...
    async def load_dag(self) -> GoalStepDAG | None: ...
    async def save_ledger(self, messages: list[dict]) -> None: ...
    async def load_ledger(self) -> list[dict]: ...
    async def clear(self) -> None: ...
```

#### Implementations

| Backend | Use case | Phase |
|---------|----------|-------|
| `InMemoryContextPersistence` | Testing, ephemeral runs | 1 |
| `FileContextPersistence` | Single-process durability | 1 |
| `PostgresContextPersistence` | Multi-process, crash recovery | Future |

`FileContextPersistence` stores JSON under `SOOTHE_HOME/data/context_engine/{thread_id}/`:
- `goal_step_dag.json` — serialized GoalStepDAG
- `ledger.json` — serialized message ledger

### §10 ContextEngine Interface

```python
class ContextEngine:
    """Unified context management for goals, steps, ledger, and projection."""

    def __init__(
        self,
        persistence: ContextPersistenceProtocol | None = None,
        projection_config: ProjectionConfig | None = None,
        soothe_home: Path | None = None,
    ) -> None:
        self._dag = GoalStepDAG()
        self._ledger = LedgerManager()
        self._semantic = SemanticLoader(soothe_home)
        self._projection = ProjectionEngine(projection_config)
        self._persistence = persistence or InMemoryContextPersistence()

    # ── Goal management ──────────────────────────────────────

    async def create_goal(
        self,
        description: str,
        *,
        priority: int = 50,
        parent_id: str | None = None,
        depends_on: list[str] | None = None,
        generating_reasoning: str | None = None,
        source: str = "user",
        **kwargs,
    ) -> GoalNode: ...

    async def get_goal(self, goal_id: str) -> GoalNode | None: ...
    async def list_goals(self, status: str | None = None) -> list[GoalNode]: ...
    async def complete_goal(self, goal_id: str) -> None: ...
    async def fail_goal(self, goal_id: str, error: str) -> None: ...
    async def suspend_goal(self, goal_id: str, reason: str) -> None: ...

    # ── Step management ──────────────────────────────────────

    async def add_step(self, goal_id: str, step: StepNode) -> None: ...

    async def add_steps(
        self, goal_id: str, steps: list[StepNode], plan_iteration: int = 0
    ) -> None: ...

    async def complete_step(
        self, goal_id: str, step_id: str, execution: StepExecution
    ) -> None: ...

    async def fail_step(
        self, goal_id: str, step_id: str, execution: StepExecution
    ) -> None: ...

    # ── Ledger management ────────────────────────────────────

    async def record_message(self, message: BaseMessage, phase: str) -> None: ...
    async def get_ledger(self, phases: list[str] | None = None) -> list[BaseMessage]: ...

    # ── Projection ───────────────────────────────────────────

    async def project(self, goal_id: str | None = None) -> ContextBundle: ...

    # ── Persistence ──────────────────────────────────────────

    async def save(self) -> None: ...
    async def load(self) -> bool: ...

    # ── Recovery ─────────────────────────────────────────────

    async def recover(self) -> list[str]:
        """Reset goals stuck in 'active' to 'pending' after crash."""
        ...
```

---

## Data Flow

### Goal creation → Step execution → Completion

```
User Goal
  │
  ▼
ContextEngine.create_goal(description, generating_reasoning=...)
  │  → GoalNode added to GoalStepDAG
  │
  ▼
ContextEngine.project() → ContextBundle
  │  → Prompt templates render bundle into system/user messages
  │  → CoreAgent receives rendered messages
  │
  ▼
CoreAgent executes → output messages
  │
  ▼
ContextEngine.add_steps(goal_id, [StepNode(...)], plan_iteration=N)
  │  → Steps added to goal's StepDAG
  │
  ▼
ContextEngine.complete_step(goal_id, step_id, StepExecution(...))
  │  → StepNode.status = "completed", execution recorded
  │  → LedgerManager records step result
  │
  ▼
ContextEngine.project() → updated ContextBundle
  │  → Next iteration sees completed steps, pending steps, lineage
  │
  ▼
... all steps complete ...
  │
  ▼
ContextEngine.complete_goal(goal_id)
  → GoalNode.status = "completed"
```

### Ledger recovery from GoalStepDAG

The loop message ledger is always derivable from the GoalStepDAG. Given a `GoalStepDAG`, the ledger is reconstructed by:

1. Collecting all `StepExecution.input_messages` and `StepExecution.output_messages` across all steps, ordered by step execution sequence
2. Including `GoalNode.generating_reasoning` as plan-phase messages

This makes the ledger a view of the DAG rather than a separate source of truth.

---

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Step execution failure | `StepNode.status = "failed"`, `execution.error` set. Goal remains active. AgentLoop decides replan vs fail-goal. |
| Goal failure | `GoalNode.status = "failed"`. Dependent goals remain blocked (dependencies not met). |
| Persistence failure | In-memory fallback with warning log. Query and projection continue; durability degraded. |
| Crash recovery | On `load()`, `recover()` resets active goals to pending. Steps with no execution reset to pending. |
| Invalid DAG operation | Cycle detection on `add_dependency`. Depth limit on goal nesting (max 5). |

---

## Module Structure

```
packages/soothe/src/soothe/context/
├── __init__.py              # Public API: ContextEngine, ContextBundle, GoalNode, StepNode
├── models.py                # GoalNode, StepNode, StepExecution, StepDAG, GoalStepDAG, GoalStepDAGSnapshot
├── engine.py                # ContextEngine (main orchestrator)
├── projection.py            # ProjectionEngine, ContextBundle, ProjectionConfig
├── ledger.py                # LedgerManager
├── semantic.py              # SemanticLoader
├── persistence/
│   ├── __init__.py          # ContextPersistenceProtocol
│   ├── base.py              # Protocol definition
│   ├── in_memory.py         # InMemoryContextPersistence
│   └── file_backend.py      # FileContextPersistence
```

---

## Testing Strategy

### Unit tests (`packages/soothe/tests/unit/context/`)

| Test file | Coverage |
|-----------|----------|
| `test_goal_step_dag.py` | DAG scheduling, dependency resolution, cycle detection, depth limits |
| `test_step_dag.py` | Step readiness, completion, failure, dependency satisfaction |
| `test_projection.py` | ContextBundle building, limit enforcement, section bounding |
| `test_ledger_manager.py` | Message recording, phase filtering, compaction, spill |
| `test_semantic_loader.py` | File loading, missing files, content truncation |
| `test_persistence.py` | Save/load/clear cycle, snapshot/restore |

### Integration tests (`packages/soothe/tests/integration/context/`)

| Test file | Coverage |
|-----------|----------|
| `test_context_engine_lifecycle.py` | Full goal creation → step execution → completion flow |
| `test_recovery.py` | Crash simulation, reload, active goal reset |
| `test_ledger_recovery_from_dag.py` | Reconstruct ledger from GoalStepDAG step executions |

---

## Migration Path (Future Phases)

### Phase 2: GoalEngine integration

- GoalEngine reads/writes goals through ContextEngine instead of internal `_goals` dict
- `GoalEngine.create_goal()` becomes a thin wrapper delegating to `ContextEngine.create_goal()`
- ContextProjector reads from ContextEngine instead of GoalDispatchContextStore
- Backward-compatible: GoalEngine's public API unchanged, internal storage replaced

### Phase 3: AgentLoop integration

- AgentLoop's `PlanDAG` replaced by `GoalNode.steps` (StepDAG)
- `LoopWorkingMemory` replaced by `LedgerManager`
- `loop_messages` replaced by `LedgerManager` with phase tagging
- `plan_ledger_projection.py` renders from `ContextBundle` instead of raw `loop_messages`
- AgentLoop orchestrator nodes call ContextEngine methods instead of direct state mutation

---

## Invariants

1. `GoalStepDAG` is the single source of truth for goal and step data within `soothe.context`.
2. Step dependencies are strictly within the same goal — cross-goal coordination uses goal-level `depends_on`.
3. `ContextBundle` is a read-only projection; mutation happens through `ContextEngine` methods only.
4. The message ledger is derivable from the GoalStepDAG (via `StepExecution` records).
5. `ContextPersistenceProtocol` implementations must support atomic save/load (no partial writes).
6. `ContextEngine` does not depend on `GoalEngine`, `AgentLoop`, or `CoreAgent` — it is standalone.
