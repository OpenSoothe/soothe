# RFC-625: AutopilotMonitor and ContextEngine Unification

**RFC**: 625
**Title**: AutopilotMonitor as ContextEngine Monitor Submodule — GoalEngine Deletion
**Status**: Implemented
**Kind**: Architecture Design
**Created**: 2026-06-15
**Updated**: 2026-08-04
**Dependencies**: RFC-624 (Context Engine), RFC-222 (Autopilot and Goal Engine Architecture), RFC-200 (Autonomous Goal Management)
**Related**: RFC-204 (Autopilot Mode — user-facing surface: CLI, HTTP endpoints, consensus semantics; RFC-625 defines runtime implementation: AutopilotMonitor, ContextEngine integration, proactive DAG monitoring), RFC-217 (Goal Context Management), RFC-626 (Entity Model and State Management Consolidation — LoopState Elimination), [IG-678](../impl/IG-678-autopilot-ce-rails-production-readiness.md), [IG-680](../impl/IG-680-autopilot-dag-health-evidence-deps.md)
**Supersedes**: RFC-200 (Goal Management) — GoalEngine deleted, features migrated to ContextEngine
**Implements**: RFC-303 (MemoryProtocol) — CE's EpisodicSubmodule implements MemoryProtocol API for persistent episodic memory

---

## Abstract

This RFC unifies goal management under ContextEngine, deletes GoalEngine entirely (~1821 lines), and introduces AutopilotMonitor as a proactive DAG monitoring submodule within AutopilotService. ContextEngine becomes the sole source of truth for goal/step/ledger state, with AutopilotMonitor handling LLM-driven verification, proactive goal intake, and multi-mode memory distillation. The design enables live mode switching between solo and autopilot modes while preserving the CE DAG across goals in both modes.

---

## Problem Statement

### Current State

1. **GoalEngine and ContextEngine overlap**: Both manage goals and goal-level scheduling. GoalEngine owns a flat `dict[str, Goal]` with retry/backoff semantics; ContextEngine owns a unified `GoalStepDAG` with lineage tracking. The split creates two sources of truth for goal state.

2. **Autopilot lacks proactive monitoring**: Current AutopilotService dispatches goals and handles retries but does not proactively monitor the goal DAG for restructuring opportunities, stale goal cleanup, or multi-loop dreaming.

3. **Solo mode has no goal lineage**: When autopilot is disabled, StrangeLoop runs single goals without tracking goal lineage or cross-goal ledger, losing context continuity.

4. **Goal intake is queue-based**: In solo mode, new goals queue until current goal completes. In autopilot mode, new goals could be immediately incorporated into the DAG for parallel execution or dependency resolution.

5. **No dreaming memory distillation**: Goals and ledger accumulate without systematic distillation into episodic memory, reusable procedures, semantic knowledge, or user profiles.

### Goals

1. **Single source of truth**: ContextEngine owns all goal/step/ledger state; GoalEngine deleted.
2. **Proactive DAG monitoring**: AutopilotMonitor verifies DAG health, suggests restructuring, and triggers dreaming.
3. **LLM-driven verification**: Goal DAG verification uses LLM reasoning for placement analysis, health checks, and post-completion decomposition.
4. **LLM-driven distillation**: Dreaming uses LLM to extract episodic summaries, procedures, semantic updates, and user profiles.
5. **Solo mode lineage**: CE DAG persists across goals in both modes; solo builds linear chain, autopilot builds full DAG.
6. **Live mode switching**: Toggle autopilot on/off without losing CE DAG state.
7. **Immediate goal intake**: In autopilot mode, new goals update DAG immediately (not queued).

### Non-Goals

- Multi-process goal orchestration (deferred to future RFC).
- RAG/vector store integration for dreaming memory (deferred).
- Cross-workspace dreaming (topic-based dreaming scope only).
- Deletion of MemoryProtocol (MemoryProtocol is retained as protocol interface for external memory integration; CE's EpisodicSubmodule implements MemoryProtocol API).

---

## Solution

### §1 Module Relocation: soothe.context → soothe.context

Positions ContextEngine as foundational infrastructure alongside other foundation modules.

```
packages/soothe/src/soothe/context/
├── __init__.py              # Public API exports
├── models.py                # GoalNode, StepNode, StepExecution, StepDAG, GoalStepDAG
├── engine.py                # ContextEngine
├── projection.py            # ProjectionEngine, ContextBundle, ProjectionConfig
├── ledger.py                # LedgerManager
├── semantic.py              # SemanticLoader
├── persistence/
│   ├── __init__.py
│   ├── base.py              # ContextPersistenceProtocol
│   ├── file_backend.py      # FileContextPersistence
│   ├── sqlite_backend.py    # SqliteContextPersistence
│   └── pgsql_backend.py     # PgsqlContextPersistence
├── planning/
│   ├── __init__.py          # PlanningFacade
│   ├── models.py            # DagPlanningContext, CompletionStrategy
│   ├── completion.py        # Heuristic functions
│   ├── step_planner.py      # StepPlanningSubengine + StepPlanManagerAdapter
│   ├── goal_planner.py      # GoalPlanningSubengine
│   └── scheduling.py        # GoalScheduler
└── episodic/
    ├── __init__.py
    ├── store.py             # EpisodicStore interface (implements MemoryProtocol API)
    └── models.py            # EpisodeSummary model
```

Import path changes:
- `from soothe.context import ContextEngine` → `from soothe.context import ContextEngine`
- All existing imports updated via search/replace
- `soothe.context` namespace deprecated with warning

---

### §2 GoalEngine Deletion & Feature Migration

**Delete GoalEngine entirely (~1821 lines):**

| File | Action |
|------|--------|
| `foundation/autopilot/engine.py` | Delete |
| `foundation/autopilot/models.py` | Keep `Goal` temporarily → migrate fields to `GoalNode` |
| `foundation/autopilot/backoff_reasoner.py` | Move to `foundation/autopilot/backoff_reasoner.py` |
| `foundation/autopilot/file_lock_registry.py` | Delete (WorkspaceReservation suffices per RFC-222) |

**WorkerPool disposition**: Not affected by GoalEngine deletion. `WorkerPool` remains in `AutopilotService` (unchanged per RFC-222) — manages subprocess workers independently of goal state management. AutopilotMonitor does not own WorkerPool; it only monitors DAG state and triggers events. Worker dispatch continues via `AutopilotService.dispatch_loop()`.

**GoalNode enhancement (absorbs Goal fields from `autopilot/models.py`):**

Existing GoalNode fields (RFC-624, `context/models.py`):

Existing GoalNode fields (RFC-624, `context/models.py`):
- `id`, `description`, `status`, `priority`
- `parent_id`, `depends_on`, `informs`, `conflicts_with`
- `steps: StepDAG`
- `generating_reasoning`, `source`
- `total_tokens_used`, `total_duration_ms`, `max_iterations`
- `thread_id`, `assigned_loop_id`
- `previous_plan`, `action_history`
- `created_at`, `updated_at`

Fields migrated from Goal model (`autopilot/models.py:Goal`):

| Field | Default | Notes |
|-------|---------|-------|
| `retry_count` | `0` | Retries attempted |
| `max_retries` | `2` | Retry budget |
| `send_back_count` | `0` | Consensus send-backs (RFC-204) |
| `max_send_backs` | `3` | Send-back budget (RFC-204) |
| `source_file` | `None` | GOAL.md path if file-sourced |
| `workspace` | `None` | Autopilot dispatch workspace (RFC-222) |
| `report` | `None` | `GoalReport` on completion |
| `attempts_after_crash` | `0` | Crash recovery count (RFC-222) |
| `pending_clarification` | `None` | RFC-622 clarification state |
| `guidance_accumulated` | `[]` | RFC-228 operator guidance |

Fields deferred (not migrated):
- `lock_status`, `locked_files`, `lock_acquired_at` — fine-grained locking (RFC-222 Q1, deferred)

**New dreaming fields:**

| Field | Default | Purpose |
|-------|---------|---------|
| `topic` | `None` | Topic tag for cross-loop dreaming |
| `findings` | `[]` | Key findings from goal execution |
| `distilled` | `False` | Whether goal has been distilled |

**Final GoalNode model (after migration):**

```python
class GoalNode(BaseModel):
    # Core identity
    id: str
    description: str
    status: GoalStatus
    priority: int = 50

    # DAG relationships
    parent_id: str | None = None
    depends_on: list[str] = []
    informs: list[str] = []
    conflicts_with: list[str] = []

    # Embedded step DAG
    steps: StepDAG

    # Lineage
    generating_reasoning: str | None = None
    source: Literal["user", "directive", "file_discovery", "decomposition"] = "user"

    # Execution tracking
    total_tokens_used: int = 0
    total_duration_ms: int = 0
    max_iterations: int = 0
    thread_id: str | None = None
    assigned_loop_id: str | None = None
    previous_plan: dict[str, Any] | None = None
    action_history: list[str] = []

    # Retry/backoff (from Goal)
    retry_count: int = 0
    max_retries: int = 2
    send_back_count: int = 0  # RFC-204 consensus
    max_send_backs: int = 3
    attempts_after_crash: int = 0  # RFC-222

    # Workspace/source (from Goal)
    source_file: str | None = None
    workspace: str | None = None
    report: GoalReport | None = None
    pending_clarification: dict[str, Any] | None = None  # RFC-622
    guidance_accumulated: list[dict[str, Any]] = []  # RFC-228

    # Dreaming (NEW)
    topic: str | None = None
    findings: list[str] = []
    distilled: bool = False

    # Timestamps
    created_at: datetime
    updated_at: datetime
```

**BackoffReasoner migration:**
- Move to `foundation/autopilot/backoff_reasoner.py`
- Input: `GoalNode` from CE DAG (instead of `Goal`)
- Output: `BackoffDecision` unchanged
- Called by AutopilotMonitor `on_goal_failed` event handler

---

### §3 AutopilotMonitor Architecture

**AutopilotMonitor as AutopilotService submodule:**

```python
class AutopilotService:
    """Daemon-owned singleton for 24/7 autonomous goal orchestration."""

    def __init__(self, daemon_cfg, agent_cfg, runner_factory, durability):
        self._ce = ContextEngine(...)          # daemon-scoped CE
        self._monitor = AutopilotMonitor(
            ce=self._ce,
            bus=self._internal_bus,
            config=agent_cfg,
        )
        self._worker_pool = WorkerPool(...)
        self._workspace_reservation = WorkspaceReservation()
```

**AutopilotMonitor internal structure:**

```
foundation/autopilot/
├── __init__.py
├── monitor.py               # AutopilotMonitor class (~400 lines)
├── goal_dag_verifier.py     # LLM-driven DAG verification coordinator
├── verifier_reasoner.py     # DagVerificationReasoner (LLM caller)
├── verifier_prompts.py      # LLM prompt templates for verification
├── goal_intake_handler.py   # New goal intake → CE calls
├── dreaming_coordinator.py  # LLM-driven multi-mode distillation orchestrator
├── dreaming_reasoner.py     # DreamingDistillationReasoner (LLM caller)
├── dreaming_prompts.py      # LLM prompt templates for distillation
├── dreaming_handlers/       # Per-mode handler implementations
│   ├── __init__.py
│   ├── episodic_handler.py  # Episodic memory distillation (LLM)
│   ├── procedure_handler.py # Skill/procedure extraction (LLM)
│   ├── semantic_handler.py  # Project MEMORY.md update (LLM)
│   └── profile_handler.py   # User profile extraction (LLM)
├── backoff_reasoner.py      # Migrated from GoalEngine
└── models.py                # Monitor-specific models (responses, suggestions)
```

**AutopilotMonitor class:**

```python
class AutopilotMonitor:
    """Proactive goal DAG monitor within AutopilotService.

    Responsibilities:
      - Goal intake: receive new goals, call CE APIs
      - DAG verification: background loop + event triggers
      - Backoff reasoning: on goal_failed events
      - Dreaming coordination: multi-mode memory distillation

    All mutations go through ContextEngine public APIs.
    """

    def __init__(self, ce: ContextEngine, bus: InternalEventBus, config: SootheConfig):
        self._ce = ce
        self._bus = bus
        self._verifier = GoalDAGVerifier(ce, config)
        self._intake = GoalIntakeHandler(ce, verifier, workspace_reservation)
        self._dreaming = DreamingCoordinator(ce, config)
        self._backoff_reasoner = GoalBackoffReasoner(config)

        # Subscribe to events
        self._bus.subscribe("goal_completed", self._on_goal_completed)
        self._bus.subscribe("goal_failed", self._on_goal_failed)

    async def start(self) -> None:
        self._verify_task = asyncio.create_task(self._verification_loop())
        self._dreaming_task = asyncio.create_task(self._dreaming_timer_loop())

    async def intake_goal(self, description: str, **kwargs) -> GoalNode:
        """Receive new goal, call CE.create_goal(), return created node."""
        placement = self._verifier.analyze_placement(description)
        goal = await self._ce.create_goal(description, ...)
        await self._bus.emit(GoalCreatedEvent(goal_id=goal.id))
        return goal

    async def _on_goal_completed(self, event) -> None:
        await self._verifier.verify_dag_post_completion(event.goal_id)
        if await self._ce.is_dag_complete():
            await self._dreaming.enter_dreaming_mode()

    async def _on_goal_failed(self, event) -> None:
        decision = await self._backoff_reasoner.reason_backoff(...)
        await self._apply_backoff_decision(decision)

    async def _verification_loop(self) -> None:
        while not self._shutdown_event.is_set():
            await asyncio.sleep(self._config.verify_interval)
            await self._verifier.verify_dag_health()

    async def _dreaming_timer_loop(self) -> None:
        while not self._shutdown_event.is_set():
            await asyncio.sleep(self._config.dreaming_interval)
            if await self._ce.is_dag_complete():
                await self._dreaming.enter_dreaming_mode()
```

---

### §4 GoalDAGVerifier (LLM-Based)

**GoalDAGVerifier responsibilities:**

1. **LLM-driven background health verification** — periodic check using LLM to analyze DAG health, detect stale goals, suggest restructuring
2. **LLM-driven post-completion verification** — triggered by `goal_completed` event, LLM analyzes decomposition opportunities and redundancy
3. **LLM-driven placement analysis** — for new goal intake, LLM suggests optimal priority, dependencies, and potential merging

**Architecture:**

```
foundation/autopilot/
├── goal_dag_verifier.py      # GoalDAGVerifier coordinator
├── verifier_prompts.py       # LLM prompt templates for verification
└── verifier_reasoner.py      # DagVerificationReasoner (LLM caller)
```

**DagVerificationReasoner (LLM caller):**

```python
class DagVerificationReasoner:
    """LLM-based reasoning for DAG verification."""

    def __init__(self, config: SootheConfig):
        self._model = config.create_chat_model("reason")

    async def verify_health(self, snapshot: DagSnapshot) -> DagHealthResponse:
        """Call LLM for health verification."""
        prompt = DAG_HEALTH_VERIFICATION_PROMPT.format(
            dag_summary=snapshot.summary,
            goals_detail=snapshot.goals_detail,
            step_progress=snapshot.step_progress,
        )
        response = await self._model.ainvoke([SystemMessage(prompt)])
        return DagHealthResponse.model_validate_json(response.content)

    async def verify_post_completion(self, context: CompletionVerificationContext) -> CompletionVerificationResponse:
        """Call LLM for post-completion analysis."""
        prompt = POST_COMPLETION_VERIFICATION_PROMPT.format(...)
        response = await self._model.ainvoke([SystemMessage(prompt)])
        return CompletionVerificationResponse.model_validate_json(response.content)

    async def analyze_placement(self, context: GoalPlacementContext) -> GoalPlacementResponse:
        """Call LLM for placement analysis."""
        prompt = GOAL_PLACEMENT_PROMPT.format(...)
        response = await self._model.ainvoke([SystemMessage(prompt)])
        return GoalPlacementResponse.model_validate_json(response.content)
```

**LLM Response Models (structured output):**

```python
class DagHealthResponse(BaseModel):
    reset_goals: list[str] = []
    remove_goals: list[str] = []
    merge_goals: list[MergeSuggestion] = []  # [{goals: [...], merged_description: "..."}]
    decompose_goals: list[DecomposeSuggestion] = []
    priority_adjustments: dict[str, int] = {}
    reasoning: str

class CompletionVerificationResponse(BaseModel):
    new_goals: list[NewGoalSuggestion] = []
    redundant_goals: list[str] = []
    ready_goals: list[str] = []
    decomposition: DecomposeSuggestion | None = None
    reasoning: str

class GoalPlacementResponse(BaseModel):
    priority: int
    depends_on: list[str] = []
    informs: list[str] = []
    merge_with: str | None = None  # Goal ID to merge with
    complexity: Literal["simple", "moderate", "complex"]
    reasoning: str
```

---

### §5 GoalIntakeHandler

**GoalIntakeHandler responsibilities:**

Receive new goals from HTTP/CLI/Scheduler and route through CE with optimal placement.

```python
class GoalIntakeHandler:

    async def submit_goal(
        self,
        description: str,
        *,
        priority: int = 50,
        workspace: str | None = None,
        depends_on: list[str] | None = None,
        source: GoalSource = "user",
    ) -> GoalIntakeResult:
        """Submit a new goal to the DAG."""

        # Workspace conflict check
        if workspace:
            conflict = self._reservation.conflicts_with_active(workspace)
            if conflict:
                return GoalIntakeResult(status="rejected", reason=f"Workspace conflicts with {conflict}")

        # Placement analysis
        placement = self._verifier.analyze_placement(description)
        final_deps = list(set(depends_on or []) | set(placement.suggested_dependencies))

        # Create via CE
        goal = await self._ce.create_goal(description, priority=placement.adjusted_priority, depends_on=final_deps, ...)

        return GoalIntakeResult(status="accepted", goal_id=goal.id)

    async def submit_goals_batch(self, goals: list[GoalSpec]) -> list[GoalIntakeResult]:
        """Submit multiple goals with dependency resolution."""
        ordered = self._order_by_dependencies(goals)
        results = []
        for spec in ordered:
            result = await self.submit_goal(spec.description, ...)
            results.append(result)
            if result.status == "rejected":
                self._mark_dependents_skipped(spec.id, goals, results)
        return results

    async def cancel_goal(self, goal_id: str) -> bool:
        """Cancel a pending/active goal via CE."""
        goal = await self._ce.get_goal(goal_id)
        if goal is None or goal.status in TERMINAL_STATES:
            return False
        await self._ce.cancel_goal(goal_id)
        self._reservation.release(goal_id)
        return True
```

**GoalIntakeResult model:**

```python
class GoalIntakeResult(BaseModel):
    status: Literal["accepted", "rejected", "skipped"]
    goal_id: str | None = None
    reason: str | None = None
    adjusted_priority: int | None = None
    suggested_dependencies: list[str] = []
```

---

### §6 DreamingCoordinator (LLM-Based Distillation)

**DreamingCoordinator responsibilities:**

Coordinate 4 LLM-driven memory distillation modes, triggered by DAG completion OR time interval. Each mode uses LLM to analyze execution history and extract distilled knowledge.

**DreamingDistillationReasoner (LLM caller):**

```python
class DreamingDistillationReasoner:
    """LLM-based reasoning for memory distillation."""

    def __init__(self, config: SootheConfig):
        self._model = config.create_chat_model("reason")

    async def distill_episodic(self, context: EpisodicDistillationContext) -> EpisodicDistillationResponse:
        """LLM distills goals into episodic memory summaries."""
        prompt = EPISODIC_DISTILLATION_PROMPT.format(...)
        response = await self._model.ainvoke([SystemMessage(prompt)])
        return EpisodicDistillationResponse.model_validate_json(response.content)

    async def distill_procedure(self, context: ProcedureDistillationContext) -> ProcedureDistillationResponse:
        """LLM extracts reusable procedures (Skills) from successful sequences."""
        prompt = PROCEDURE_DISTILLATION_PROMPT.format(...)
        response = await self._model.ainvoke([SystemMessage(prompt)])
        return ProcedureDistillationResponse.model_validate_json(response.content)

    async def distill_semantic(self, context: SemanticDistillationContext) -> SemanticDistillationResponse:
        """LLM generates project MEMORY.md updates."""
        prompt = SEMANTIC_DISTILLATION_PROMPT.format(...)
        response = await self._model.ainvoke([SystemMessage(prompt)])
        return SemanticDistillationResponse.model_validate_json(response.content)

    async def distill_profile(self, context: ProfileDistillationContext) -> ProfileDistillationResponse:
        """LLM extracts user preferences and communication patterns."""
        prompt = PROFILE_DISTILLATION_PROMPT.format(...)
        response = await self._model.ainvoke([SystemMessage(prompt)])
        return ProfileDistillationResponse.model_validate_json(response.content)
```

**LLM Response Models:**

```python
class EpisodicDistillationResponse(BaseModel):
    episodes: list[EpisodeSpec]
    reasoning: str

class EpisodeSpec(BaseModel):
    goal_id: str
    description: str
    outcome_summary: str
    key_steps: list[str]
    lessons_learned: str

class ProcedureDistillationResponse(BaseModel):
    procedures: list[ProcedureSpec]
    reasoning: str

class ProcedureSpec(BaseModel):
    name: str
    description: str
    trigger_conditions: list[str]
    steps: list[str]
    tools_used: list[str]

class SemanticDistillationResponse(BaseModel):
    additions: list[str]
    modifications: dict[str, str]
    sections_to_update: list[str]
    reasoning: str

class ProfileDistillationResponse(BaseModel):
    communication_style: str
    preferences: list[str]
    recurring_goals: list[str]
    expertise_level: Literal["beginner", "intermediate", "advanced", "expert"]
    reasoning: str
```

**DreamingScope:**

```python
DreamingScope = Literal["loop", "workspace", "topic"]
DreamingMode = Literal["episodic", "procedure", "semantic", "profile"]

@dataclass
class DreamingContext:
    goals: list[GoalNode]
    ledger: list[tuple[BaseMessage, str | None]]
    scope_id: str  # loop_id, workspace path, or topic name
```

---

### §7 ContextEngine API Additions

**New CE methods required for AutopilotMonitor:**

```python
class ContextEngine:

    # === NEW: Monitor-required methods ===

    async def remove_goal(self, goal_id: str) -> bool:
        """Remove a goal from the DAG. Validates no dependents."""

    async def merge_goals(self, goal_ids: list[str], merged_description: str) -> GoalNode:
        """Merge multiple goals into a single consolidated goal."""

    def is_dag_complete(self) -> bool:
        """Check if all goals in DAG are in terminal states."""

    def get_goals_by_status(self, status: GoalStatus) -> list[GoalNode]:
        """Filter goals by status."""

    def get_goal_dependents(self, goal_id: str) -> list[str]:
        """Get all goal IDs that depend on this goal."""

    async def update_dependencies(self, goal_id: str, depends_on: list[str]) -> None:
        """Update goal dependencies (for mode switch flattening)."""

    async def record_episodic_memory(self, episodes: list[EpisodeSummary]) -> None:
        """Store distilled episodic memory."""

    def get_episodic_memory(self, limit: int = 10) -> list[EpisodeSummary]:
        """Retrieve recent episodic memories."""
```

---

### §8 Interactive Loops vs Daemon Autopilot Jobs (2026-07-01)

**Supersedes** the earlier per-loop Solo/Autopilot toggle design (`/autopilot-toggle`,
`loop_autopilot_mode` metadata, `AutopilotMode` enum on StrangeLoop).

**Current model:**

| Surface | Behavior |
|---------|----------|
| **Interactive loop** (TUI chat, `loop_input`) | Always solo StrangeLoop — one conversational turn stream per `loop_id` |
| **Autopilot job** (`/autopilot <task>`, `job_create`, CLI `soothe autopilot run`, cron) | Daemon-owned `AutopilotService` — cross-loop goal DAG, worker pool, monitor intake |
| **`agent.autonomous.enabled`** | Starts the daemon 24/7 scheduling loop (master switch) |

Wire field `autopilot_mode` on `loop_new` / `loop_subscribe` responses is **deprecated**:
always `"solo"`. Clients must not interpret it as a runtime mode switch.

**Deferred (not implemented):** RFC-625 originally described in-loop CE goal chaining
that differed by per-loop mode (linear chain vs full DAG). That path was never wired
into `QueryEngine` / `LoopRunRequest`. If revived, it would be a separate RFC — not
conflated with daemon job orchestration.

---

### §9 TUI Goal DAG Card

**Solo mode TUI: PendingGoalQueue (existing, unchanged)**

**Autopilot mode TUI: GoalDAGCard (new)**

```python
class GoalDAGCard:
    """TUI card displaying DAG updates (delta view)."""

    def __init__(self, ce: ContextEngine, bus: InternalEventBus):
        self._ce = ce
        self._updates: list[DagUpdateEntry] = []
        self._expanded = False

        bus.subscribe("goal_created", self._on_goal_created)
        bus.subscribe("goal_completed", self._on_goal_completed)
        bus.subscribe("goal_failed", self._on_goal_failed)
        bus.subscribe("goal_removed", self._on_goal_removed)
        bus.subscribe("goal_decomposed", self._on_goal_decomposed)

    def render(self) -> Panel:
        if self._expanded:
            return self._render_expanded()  # Mini-DAG tree
        return self._render_compact()  # Recent updates list
```

**Compact view:**

```
┌──────────────────────────────────────────────┐
│ Goal DAG Updates                    [Expand] │
├──────────────────────────────────────────────┤
│ ✓ Goal-7a4f completed          2s ago        │
│ → spawned Goal-9b2c (decomposed)             │
│ ○ Goal-5c8d pending → active    now          │
│ ✗ Goal-2f9a removed            5s ago        │
└──────────────────────────────────────────────┘
```

**Expanded view:**

```
┌──────────────────────────────────────────────┐
│ Goal DAG                              [Collapse] │
├──────────────────────────────────────────────┤
│ Goal-1 (root) ✓                              │
│   └─ Goal-7a4f ✓                             │
│      ├─ Goal-9b2c ○ (active)                 │
│      └─ Goal-3d1e ○ (pending)                │
│   └─ Goal-5c8d ○ (active)                    │
└──────────────────────────────────────────────┘
```

---

### §10 Live Autopilot Mode Switching

**Toggle API:**

```python
class AutopilotService:
    async def toggle_autopilot(self, loop_id: str, enable: bool) -> ModeSwitchResult:
        if enable:
            return await self._enable_autopilot(loop_id)
        else:
            return await self._disable_autopilot(loop_id)

    async def _enable_autopilot(self, loop_id: str) -> ModeSwitchResult:
        ce = self._get_ce_for_loop(loop_id)
        self._monitor.start_for_loop(loop_id)

        # Analyze existing linear chain for restructuring
        goals = ce.get_all_goals()
        linear_chain = [g for g in goals if g.status in ("pending", "active")]
        if len(linear_chain) > 1:
            await self._monitor.analyze_restructuring(linear_chain)

        await self._bus.emit(AutopilotModeSwitchedEvent(loop_id=loop_id, enabled=True))
        return ModeSwitchResult(loop_id=loop_id, enabled=True)

    async def _disable_autopilot(self, loop_id: str) -> ModeSwitchResult:
        ce = self._get_ce_for_loop(loop_id)
        self._monitor.stop_for_loop(loop_id)

        # Flatten pending goals to linear chain
        pending = ce.get_goals_by_status("pending")
        active = ce.get_goals_by_status("active")
        sorted_pending = sorted(pending, key=lambda g: g.created_at)

        prev_id = active[0].id if active else None
        for goal in sorted_pending:
            await ce.update_dependencies(goal.id, depends_on=[prev_id] if prev_id else [])
            prev_id = goal.id

        await self._bus.emit(AutopilotModeSwitchedEvent(loop_id=loop_id, enabled=False))
        return ModeSwitchResult(loop_id=loop_id, enabled=False)
```

**Unified goal intake routing:**

```python
class AutopilotService:
    async def intake_goal(self, description: str, loop_id: str, **kwargs) -> GoalIntakeResult:
        mode = self._get_mode_for_loop(loop_id)

        if mode == AutopilotMode.SOLO:
            self._pending_queues[loop_id].append(description)
            return GoalIntakeResult(status="queued", message="Queued (solo mode)")

        else:
            return await self._monitor.intake_goal(description, **kwargs)
```

---

### §11 RFC-626 Entity Model Refinements

> **Note**: RFC-626 (Entity Model and State Management Consolidation) refines the entity model architecture established in this RFC. The following refinements apply to AutopilotMonitor's interaction with ContextEngine:

#### Refined Entity Identity

Per RFC-626 §2, all entity identity is consolidated under ContextEngine:

- **GoalNode**: Sole goal entity (no dual `Goal` / `GoalNode` + `goal_history` entry)
- **StepNode**: Sole step entity (no intermediate `PlanStep` or `StepAction`)
- **LedgerEntry**: Unified message entity (no separate `ContextEntry` vs `LedgerMessage`)

**AutopilotMonitor Impact**:
- `monitor.intake_goal()` creates `GoalNode` via `ce.create_goal()` (unchanged)
- `monitor.on_goal_completed()` reads `GoalNode.status` directly (no checkpoint fallback)
- `verifier.analyze_placement()` queries CE DAG, not `goal_engine.goals` (already aligned)

#### State Management Simplification

Per RFC-626 §3, LoopState deleted and metrics consolidated:

**Wave Metrics Migration**:
```python
# Before (LoopState):
state.last_wave_tool_call_count = executor.tool_calls
state.last_wave_subagent_task_count = executor.subagent_tasks

# After (RFC-626):
await ce.record_wave_metrics(WaveMetrics(
    goal_id=goal.id,
    iteration=state.iteration,
    tool_call_count=executor.tool_calls,
    subagent_task_count=executor.subagent_tasks,
))
```

**AutopilotMonitor Impact**:
- Completion chunk reads `ce.wave_metrics` for goal stats
- No `LoopState.previous_plan` — stored in `GoalNode.previous_plan` field
- No `LoopState.iteration` counter — CE tracks per-goal iteration

#### Unified Ledger Integration

Per RFC-626 Decision 1, ContextProtocol → CE CognitiveSubmodule:

**AutopilotMonitor Changes**:
- Goal intake ingests user input via `ce.ingest_cognitive(message, phase="intake")`
- Completion handler ingests assistant output via `ce.ingest_cognitive(message, phase="completion")`
- Dreaming coordinator reads unified ledger via `ce.ledger.entries(phases=["execute", "reflect"])`

#### Episodic Memory Alignment

Per RFC-626 Decision 2, MemoryProtocol retained as protocol interface, CE EpisodicSubmodule implements MemoryProtocol API:

**AutopilotMonitor Impact**:
- Dreaming handlers write episodes via `ce.episodic.remember_episode(summary)` (MemoryProtocol API)
- Goal intake recalls relevant episodes via `ce.episodic.recall(query)` (MemoryProtocol API)
- External memory systems (MemUMemory, Mem0) integrate via MemoryProtocol interface
- CE's EpisodicSubmodule provides default implementation for persistent episodic memory

#### Job Abstraction Alignment (RFC-222 §147-178)

Per RFC-222 refined job abstraction:

**AutopilotMonitor Impact on Dispatch**:
- `GoalDispatchContextBundle` built from CE `CognitiveSubmodule.projection()`
- No separate `GoalDispatchContextStore` — CE persistence backend handles storage
- `GoalCompletionChunk.context_contribution` written to CE `GoalNode` and `EpisodicSubmodule`

**Implementation Changes**:
```python
# Before (dual storage):
await goal_dispatch_store.put(goal_id, contribution)
await memory.remember(MemoryItem(...))

# After (RFC-626 unified):
await ce.update_goal_contribution(goal_id, contribution)
await ce.episodic.remember_episode(EpisodeSummary(...))
```

#### Verification Phase Metrics

All verification and dreaming phases operate on CE unified entity model:

```python
# DagVerificationReasoner context:
snapshot = ce.get_dag_snapshot()  # Single source, no aggregation
health_response = await verifier.verify_health(snapshot)

# DreamingDistillationReasoner context:
episodes = await ce.episodic.get_episodes_for_topic(topic)
ledger_entries = ce.ledger.entries(phases=["execute", "reflect"])
distill_response = await dreamer.distill_episodic(
    goals=[ce.get_goal(gid) for gid in completed_goals],
    ledger=ledger_entries,
    episodes=episodes,
)
```

---

### §12 Data Flow Summary

**Solo mode:**

```
User Input → PendingGoalQueue → StrangeLoop.run_with_progress()
  → CE.load() → find prev_goal → CE.create_goal(depends_on=[prev])
  → execute graph → CE.finalize_goal() → CE.save()
  → Linear DAG: Goal-1 → Goal-2 → Goal-3 (chain)
  → ContextBundle includes prior_goals, cross_goal_ledger, goal_lineage
```

**Autopilot mode:**

```
User Input → AutopilotMonitor.intake_goal()
  → GoalDAGVerifier.analyze_placement() → CE.create_goal()
  → EventBus.emit(GoalCreatedEvent) → GoalDAGCard updates

AutopilotService.dispatch_loop()
  → CE.get_goals_by_status("pending") → dispatch ready goals
  → StrangeLoop worker → GoalCompletionChunk
  → CE.complete_goal()/fail_goal() → EventBus.emit
  → AutopilotMonitor.on_goal_completed() → verify DAG
  → Background loops: verification + dreaming timer
  → DreamingCoordinator: 4 modes → apply results
```

---

### §12 Implementation Phases

| Phase | Scope | Estimated Effort |
|-------|-------|------------------|
| 1 | Relocate `soothe.context` → `soothe.context` | 2 days |
| 2 | Enhance GoalNode with Goal fields, add CE API methods | 2 days |
| 3 | Delete GoalEngine, migrate BackoffReasoner | 3 days |
| 4 | Implement AutopilotMonitor (Verifier, Intake, Dreaming) | 5 days |
| 5 | Implement TUI GoalDAGCard, mode switch logic | 3 days |
| 6 | Integration tests, verify_finally.sh | 2 days |

**Total: ~17 days**

---

### §13 Config Additions

```yaml
agent:
  autonomous:
    enabled_by_default: false

    # AutopilotMonitor settings
    verify_interval: 30          # Background verification loop (seconds)
    dreaming_interval: 300       # Time-based dreaming trigger (seconds)

    # Dreaming modes (all enabled by default)
    dreaming_modes:
      episodic:
        enabled: true
        max_episodes: 10
      procedure:
        enabled: true
        min_success_rate: 0.8
      semantic:
        enabled: true
      profile:
        enabled: true

    # Cross-loop dreaming scope
    dreaming_scope: "workspace"  # loop | workspace | topic
```

---

### §14 Invariants

1. ContextEngine is the sole source of truth for goal/step data.
2. AutopilotMonitor calls CE public APIs for all DAG mutations.
3. CE DAG persists across goals in both solo and autopilot modes.
4. Solo mode builds linear chain; autopilot mode builds full DAG.
5. Mode switching preserves CE DAG (completed goals remain).
6. All events flow through InternalEventBus for TUI/subscriber updates.
7. DreamingCoordinator runs only when DAG complete OR timer trigger.
8. BackoffReasoner migrates to monitor, called on goal_failed events.
9. LLM responses use structured output (Pydantic model validation).
10. Prompt templates enforce constraints on LLM suggestions.

---

## Error Handling

| Scenario | Behavior |
|----------|----------|
| LLM verification timeout | Skip verification cycle, log warning, continue |
| LLM distillation failure | Skip that mode, continue with other modes |
| GoalEngine deletion migration | All existing Goal fields preserved in GoalNode |
| Mode switch during active goal | Complete current goal, then apply mode switch |
| CE persistence failure | In-memory fallback, log warning |

---

## Testing

**Unit tests:**

- GoalNode enhancement: all migrated fields, new dreaming fields
- GoalDAGVerifier: LLM response parsing, health report generation
- GoalIntakeHandler: placement, conflict check, batch submission
- DreamingCoordinator: 4 mode handlers, LLM response parsing
- AutopilotMonitor: event handlers, background loops
- Mode switching: solo→autopilot, autopilot→solo, DAG preservation

**Integration tests:**

- Solo mode linear chain: 3 sequential goals, verify lineage
- Autopilot mode DAG: parallel goals, decomposition, merging
- Mode switching: live toggle, verify DAG state preserved
- Dreaming: triggered after DAG completion, all 4 modes

---

## RFC-222 Relationship: GoalEngine Replacement

This RFC modifies RFC-222 by replacing GoalEngine with ContextEngine + AutopilotMonitor:

| RFC-222 Component | After RFC-625 |
|-------------------|---------------|
| `GoalEngine` | **Deleted** — scheduling logic moves to `ContextEngine.planning.scheduling` |
| `GoalEngine._goals` dict | `ContextEngine._dag.goals` |
| `GoalEngine.peek_ready_goals()` | `GoalScheduler.ready_goals()` |
| `GoalEngine.claim_goal()` | `GoalScheduler.claim_goal()` |
| `GoalEngine.fail_goal()` + BackoffReasoner | `AutopilotMonitor.on_goal_failed()` + `_backoff_reasoner` |
| `BackoffReasoner` (in GoalEngine) | Migrated to `autopilot/backoff_reasoner.py` |
| `GoalDispatchContextBundle` | Unchanged — still built by `ContextProjector` from CE DAG |
| `GoalDispatchContextStore` | Unchanged — durability backed by CE persistence |
| `WorkspaceReservation` | Unchanged — still used by AutopilotService at dispatch |
| `WorkerPool` | Unchanged — still manages subprocess workers |
| `InternalEventBus` | Unchanged — event routing unchanged |

**AutopilotService composition (before vs after):**

Before (RFC-222):
```python
class AutopilotService:
    _goal_engine: GoalEngine
    _worker_pool: WorkerPool
    _workspace_reservation: WorkspaceReservation
    _context_projector: ContextProjector
    _dispatch_store: GoalDispatchContextStore
```

After (RFC-625):
```python
class AutopilotService:
    _ce: ContextEngine              # daemon-scoped CE (replaces _goal_engine)
    _monitor: AutopilotMonitor      # proactive DAG monitor
    _worker_pool: WorkerPool        # unchanged
    _workspace_reservation: WorkspaceReservation  # unchanged
    _context_projector: ContextProjector          # unchanged (reads from CE)
    _dispatch_store: GoalDispatchContextStore    # unchanged
```

**Key invariant preserved:** StrangeLoop remains the pure execution unit. It hydrates from `GoalDispatchContextBundle` and emits `GoalCompletionChunk`. AutopilotMonitor handles all DAG-level concerns in the daemon process.

---

## Implementation Status

**Status**: Implemented (2026-06-16)

### Completed Sections

| Section | Status | Notes |
|---------|--------|-------|
| §1 Module relocation | ✅ Complete | `soothe.context` → `soothe.context` |
| §2 GoalNode enhancement | ✅ Complete | All Goal fields migrated, dreaming fields added |
| §3 GoalEngine deletion | ✅ Complete | `soothe.core.goal_engine/` empty, BackoffReasoner migrated |
| §4 LLM Verification Reasoner | ✅ Complete | `verifier_reasoner.py`, `verifier_prompts.py` implemented |
| §4 LLM Dreaming Reasoner | ✅ Complete | `dreaming_reasoner.py`, `dreaming_prompts.py` implemented |
| §5 AutopilotMonitor | ✅ Complete | Core monitor with event handlers implemented |
| §6 DreamingCoordinator | ✅ Complete | 4-mode distillation coordinator implemented |
| §7 ContextEngine API additions | ✅ Complete | `remove_goal`, `merge_goals`, `is_dag_complete`, etc. |
| §8 Interactive loops vs daemon jobs | ✅ Revised (2026-07-01) | Per-loop toggle removed; loops always solo, jobs via AutopilotService |
| §9 TUI GoalDAGCard | ✅ Complete | Widget for autopilot DAG visualization |
| §10 Live mode switching | ❌ Removed | `/autopilot-toggle` and `loop_autopilot_mode` deleted |
| §11-§12 Data flow & phases | ✅ Complete | Implementation phases completed |
| §13 Config additions | ✅ Complete | All configuration fields added |
| §14 Event definitions | ✅ Complete | GoalRemoved, GoalDecomposed, AutopilotModeSwitched events added |

### Implementation Notes

All LLM-driven verification and distillation reasoners are fully implemented:

- `GoalDAGVerifier.verify_dag_health()` — LLM-based health verification
- `GoalDAGVerifier.analyze_placement()` — LLM-based placement analysis
- `DreamingCoordinator._run_mode()` — all 4 distillation modes operational
- `AutopilotMonitor._analyze_placement()` — LLM integration complete
- Event definitions complete: `GoalCreatedEvent`, `GoalCompletedEvent`, `GoalFailedEvent`, `GoalRemovedEvent`, `GoalDecomposedEvent`, `AutopilotModeSwitchedEvent`

The `BackoffReasoner` (migrated from GoalEngine) has full LLM integration and serves as the pattern for all reasoners.

### Errata / known runtime gaps (2026-08-04) — closed by IG-680

Long-running eval (`IG-680`) showed design-vs-runtime drift. **Implemented** in
IG-680 (unit regression in `test_ig680_health_evidence_deps.py`):

| Spec claim | Resolution | Tracking |
|------------|------------|----------|
| §7 `remove_goal` validates no dependents | Health `may_auto_remove` + cascade cancel binding | IG-680 AH-1 ✅ |
| §7 `update_dependencies` for restructuring | `wire_dependencies` on health report + apply | IG-680 AH-3 ✅ |
| §4 / §5 decompose produces ordered DAG | Sequential `depends_on` chain when LLM omits deps | IG-680 AH-3 ✅ |
| GoalNode.workspace on dispatch children | `create_subgoals` / directives inherit `parent.workspace` | IG-680 AH-2 ✅ |
| Post-completion follow-ups once | Cooldown + description dedupe + deliverable probe skip | IG-680 AH-4 ✅ |
| §7 `merge_goals` | Merge suggestions still logged only (intentional) | deferred |

**Normative addenda (enforced after IG-680):**

1. **Health remove policy** — Auto-apply of `remove_goals` is limited to terminal
   clutter with zero live dependents/descendants. Non-terminal goals are never
   health-cancelled. Cascade cancels use `AutopilotService.cancel_goal` when wired.
2. **Workspace inheritance** — `GoalPlanningSubengine.create_subgoals` /
   `apply_llm_subgoals` copy `parent.workspace`.
3. **Dependency wiring** — Health reports may include `wire_dependencies` applied
   via `ContextEngine.update_dependencies`. Pipeline decompose falls back to a
   sequential chain when LLM omits deps.
4. **Decompose budget** — One health/post-completion decompose wave per parent
   per cooldown window; duplicate descriptions under the same parent are rejected.

### Completion Tracking

See `docs/impl/IG-494-rfc625-completion.md` for historical completion work, and
[IG-680](../impl/IG-680-autopilot-dag-health-evidence-deps.md) for health /
evidence / deps production fixes.

---

## References

- RFC-624: Context Engine — GoalNode, StepDAG, LedgerManager, ProjectionEngine
- RFC-222: Autopilot and Goal Engine Architecture — AutopilotService, WorkerPool, WorkspaceReservation (GoalEngine deleted per this RFC)
- RFC-200: Autonomous Goal Management (superseded) — BackoffReasoner migrated to monitor
- RFC-204: Autopilot Mode — job submit via daemon AutopilotService; interactive loops remain solo
- RFC-217: Goal Context Management — GoalContextManager reads from CE DAG