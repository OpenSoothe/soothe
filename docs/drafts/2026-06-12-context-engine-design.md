# Context Engine Design

## 1. Purpose

ContextEngine provides a unified interface for context management across Soothe's GoalEngine (goal-level) and StrangeLoop (execution-level). It consolidates scattered context handling — goal DAG, step DAG, message ledger, working memory, project instructions — into a single module with clear ownership boundaries.

ContextEngine is independent from `ContextProtocol` (RFC-000). ContextProtocol remains the orchestrator's cognitive knowledge ledger; ContextEngine focuses on unifying the execution-level context that currently lives across `GoalEngine._goals`, `PlanDAG`, `LoopWorkingMemory`, and `loop_messages`.

## 2. Scope

### Phase 1 (this design)

- Working memory: goals, goal progress, step DAGs, message ledger
- Semantic memory: CLAUDE.md, AGENTS.md, MEMORY.md (static project instructions)
- Unified Goal+Step DAG with lineage tracking
- ContextBundle projection (structured data output for prompt templates)
- Standalone module in `soothe.context` — no changes to existing GoalEngine or StrangeLoop

### Deferred (future phases)

- Procedure memory: Skills, MCP tools integration
- Episodic memory: distilled working history
- RAG / vector store integration
- Wiring ContextEngine into GoalEngine (goal management delegation)
- Wiring ContextEngine into StrangeLoop (plan/ledger replacement)
- Postgres-backed persistence

## 3. Architecture

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
│  • plan_ledger_projection.py                                  │
│  • system_templates.py                                        │
│  • Render ContextBundle sections into messages                │
└──────────────────────────────────────────────────────────────┘
          ↓ Rendered messages
┌──────────────────────────────────────────────────────────────┐
│ CoreAgent (existing, unchanged at this phase)                 │
└──────────────────────────────────────────────────────────────┘
```

### Integration path

1. **Phase 1** (this design): Build `soothe.context` as standalone module with full functionality. Existing code unchanged.
2. **Phase 2**: Wire ContextEngine into GoalEngine — goal management reads/writes through ContextEngine instead of internal `._goals`.
3. **Phase 3**: Wire ContextEngine into StrangeLoop — PlanDAG, LoopWorkingMemory, and loop_messages replaced by ContextEngine.

## 4. Core Data Structures

### 4.0 Status types

```python
GoalStatus = Literal[
    "pending", "active", "completed", "failed",
    "suspended", "blocked", "validated",
    "awaiting_clarification", "cancelled",
]

StepStatus = Literal["pending", "completed", "failed"]
```

### 4.1 GoalNode

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

    # Soft dependencies (informs) and conflicts
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

Design decisions:

- **StepDAG embedded in GoalNode**: Steps are goal-scoped (no cross-goal step dependencies). Embedding makes GoalNode the atomic unit of persistence and matches the dependency model.
- **Lineage via `generating_reasoning`**: Stores the reasoning that produced this goal (e.g., the plan-assess LLM output, the directive text, the user's input). Enables context projection to show *why* a goal exists.
- **`source` field**: Tracks origin for observability and projection filtering.

### 4.2 StepNode and StepExecution

```python
class StepNode(BaseModel):
    """Single step within a goal's step DAG."""

    id: str  # composite like "goal-01"
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

    input_messages: list[dict] = Field(default_factory=list)  # serialized BaseMessage
    output_messages: list[dict] = Field(default_factory=list)  # serialized BaseMessage
    tokens_used: int = 0
    duration_ms: int = 0
    error: str | None = None
    thread_id: str | None = None
```

Design decisions:

- **`StepExecution.input_messages/output_messages` stored as serialized dicts** rather than `BaseMessage` objects, for persistence portability. At runtime, `LedgerManager` holds `BaseMessage` objects. When a step completes, `ContextEngine` serializes the relevant messages into `StepExecution` for durability. On recovery, these dicts are deserialized back to `BaseMessage` to rehydrate the `LedgerManager`.
- **`reasoning_trace`** captures the plan-assess or plan-generate reasoning that produced this step, enabling lineage projection.
- **Step dependencies strictly within same goal** — cross-goal coordination flows through goal-level `depends_on`.

### 4.3 StepDAG

```python
class StepDAG(BaseModel):
    """DAG of steps for a single goal."""

    nodes: dict[str, StepNode] = Field(default_factory=dict)

    def add_step(self, step: StepNode) -> None: ...

    def ready_steps(self) -> set[str]:
        """Pending steps whose dependencies are all satisfied."""
        ...

    def completed_steps(self) -> set[str]: ...
    def failed_steps(self) -> set[str]: ...
    def pending_steps(self) -> set[str]: ...

    def mark_completed(self, step_id: str, execution: StepExecution) -> None: ...
    def mark_failed(self, step_id: str, execution: StepExecution) -> None: ...

    @property
    def total_steps(self) -> int: ...
    @property
    def success_rate(self) -> float: ...
```

### 4.4 GoalStepDAG

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

    # Scheduling
    def ready_goals(self, limit: int = 1) -> list[GoalNode]:
        """Goals whose dependencies are satisfied, sorted by priority desc / created_at asc."""
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

## 5. Context Projection

### 5.1 ContextBundle

```python
class ContextBundle(BaseModel):
    """Structured output of ContextEngine.project() for prompt templates.

    This is not a rendered string — it is structured data that prompt
    templates render into appropriate message sections.
    """

    # Goal context
    active_goal: GoalNode | None = None
    goal_progress: str = ""  # rendered progress summary

    # Step context
    pending_steps: list[StepNode] = Field(default_factory=list)
    completed_steps: list[StepNode] = Field(default_factory=list)
    failed_steps: list[StepNode] = Field(default_factory=list)

    # Ledger context
    ledger_summary: str = ""  # condensed recent messages
    ledger_messages: list[dict] = Field(default_factory=list)  # recent raw messages

    # Semantic context
    project_instructions: str = ""  # CLAUDE.md content
    agent_instructions: str = ""  # AGENTS.md content
    memory_instructions: str = ""  # MEMORY.md content

    # Lineage context (for reasoning)
    goal_lineage: str = ""  # why current goal exists
    step_lineage: str = ""  # reasoning that led to pending steps

    # Observability metadata
    total_tokens_used: int = 0
    goal_dag_summary: str = ""  # compact DAG state overview
```

### 5.2 ProjectionConfig

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

### 5.3 ProjectionEngine

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

Projection logic per section:

| Section | Source | Bounding strategy |
|---------|--------|-------------------|
| active_goal | GoalStepDAG | Single goal |
| goal_progress | StepDAG stats | Rendered summary, max 500 chars |
| pending_steps | StepDAG | Top-N by dependency order |
| completed_steps | StepDAG | Recent N, truncated descriptions |
| ledger_summary | LedgerManager | Condensed text, max `max_ledger_chars` |
| project_instructions | SemanticLoader | Raw content, max `max_project_instructions_chars` |
| goal_lineage | GoalStepDAG.goal_lineage() | Chain of descriptions, max `max_lineage_chars` |
| step_lineage | StepNode.reasoning_trace | Recent reasoning, max `max_lineage_chars` |

## 6. LedgerManager

Replaces `LoopWorkingMemory` and the `loop_messages` list in StrangeLoop state.

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
        """Return only execute_step phase messages for CoreAgent."""
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

## 7. SemanticLoader

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

## 8. Persistence

### 8.1 Protocol

```python
class ContextPersistenceProtocol(Protocol):
    """Backend for GoalStepDAG and ledger durability."""

    async def save_dag(self, dag: GoalStepDAG) -> None: ...
    async def load_dag(self) -> GoalStepDAG | None: ...
    async def save_ledger(self, messages: list[dict]) -> None: ...
    async def load_ledger(self) -> list[dict]: ...
    async def clear(self) -> None: ...
```

### 8.2 Implementations

| Backend | Use case | Status |
|---------|----------|--------|
| `InMemoryContextPersistence` | Testing, ephemeral runs | Phase 1 |
| `FileContextPersistence` | Single-process durability | Phase 1 |
| `PostgresContextPersistence` | Multi-process, crash recovery | Future |

FileContextPersistence stores JSON under `SOOTHE_HOME/data/context_engine/{thread_id}/`:
- `goal_step_dag.json` — serialized GoalStepDAG
- `ledger.json` — serialized message ledger

## 9. ContextEngine Interface

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

    async def add_step(
        self, goal_id: str, step: StepNode
    ) -> None: ...

    async def add_steps(
        self, goal_id: str, steps: list[StepNode], plan_iteration: int = 0
    ) -> None:
        """Batch-add steps from a plan result."""
        ...

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

## 10. Data Flow

### 10.1 Goal creation → Step execution → Completion

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

### 10.2 Ledger recovery from GoalStepDAG

The draft notes: "the current agentloop's loop message ledger could be recovered from the DAG."

This works because each `StepExecution` stores the full CoreAgent input/output messages. Given a `GoalStepDAG`, the ledger can be reconstructed by:

1. Collecting all `StepExecution.input_messages` and `StepExecution.output_messages` across all steps, ordered by step execution sequence
2. Including `GoalNode.generating_reasoning` as plan-phase messages

This ensures the ledger is always derivable from the DAG, making it a view rather than a separate source of truth.

**Relationship between LedgerManager and DAG**: LedgerManager is the runtime fast path for message recording and phase-filtered retrieval (e.g., `project_for_core_agent()` returns only `execute_step` messages). The DAG-based recovery is the persistence/durability path — after crash recovery, `StepExecution` data is deserialized back into `BaseMessage` objects and the LedgerManager is rehydrated. At runtime, LedgerManager and StepExecution are kept in sync by `ContextEngine`: recording a step completion writes to both.

## 11. Error Handling

| Scenario | Behavior |
|----------|----------|
| Step execution failure | `StepNode.status = "failed"`, `execution.error` set. Goal remains active. StrangeLoop decides replan vs fail-goal. |
| Goal failure | `GoalNode.status = "failed"`. Dependent goals remain blocked (dependencies not met). |
| Persistence failure | In-memory fallback with warning log. Query and projection continue; durability degraded. |
| Crash recovery | On `load()`, `recover()` resets active goals to pending. Steps with no execution reset to pending. |
| Invalid DAG operation | Cycle detection on `add_dependency`. Depth limit on goal nesting (max 5). |

## 12. Testing Strategy

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

## 13. Module Structure

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

## 14. Migration Path (Future Phases)

### Phase 2: GoalEngine integration

- GoalEngine reads/writes goals through ContextEngine instead of internal `_goals` dict
- `GoalEngine.create_goal()` becomes a thin wrapper delegating to `ContextEngine.create_goal()`
- ContextProjector reads from ContextEngine instead of GoalDispatchContextStore
- Backward-compatible: GoalEngine's public API unchanged, internal storage replaced

### Phase 3: StrangeLoop integration

- StrangeLoop's `PlanDAG` replaced by `GoalNode.steps` (StepDAG)
- `LoopWorkingMemory` replaced by `LedgerManager`
- `loop_messages` replaced by `LedgerManager` with phase tagging
- `plan_ledger_projection.py` renders from `ContextBundle` instead of raw `loop_messages`
- StrangeLoop orchestrator nodes call ContextEngine methods instead of direct state mutation
