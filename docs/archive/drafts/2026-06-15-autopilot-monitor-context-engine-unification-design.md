# Design Draft: AutopilotMonitor and ContextEngine Unification

**Date**: 2026-06-15
**Author**: Design session via Platonic Brainstorming
**Status**: Approved for RFC formalization

---

## Overview

This design unifies goal management under ContextEngine, deletes GoalEngine entirely, and introduces AutopilotMonitor as a proactive DAG monitoring submodule within AutopilotService. The result: CE as sole goal/step data source, with AutopilotMonitor handling verification, intake, and multi-mode dreaming.

---

## 1. Module Structure Relocation

**`soothe.context` → `soothe.foundation.context`**

Positions ContextEngine as foundational infrastructure alongside other foundation modules.

```
packages/soothe/src/soothe/foundation/context/
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
    ├── store.py             # EpisodicStore interface
    └── models.py            # EpisodeSummary model
```

Import path changes:
- `from soothe.context import ContextEngine` → `from soothe.foundation.context import ContextEngine`
- All existing imports updated via search/replace
- `soothe.context` namespace deprecated with warning

---

## 2. GoalEngine Deletion & Feature Migration

**Delete GoalEngine entirely (~1821 lines):**

| File | Action |
|------|--------|
| `foundation/autopilot/engine/engine.py` | Delete |
| `foundation/autopilot/engine/models.py` | Keep `Goal` temporarily → migrate fields to `GoalNode` |
| `foundation/autopilot/engine/backoff_reasoner.py` | Move to `foundation/autopilot/monitor/backoff_reasoner.py` |
| `foundation/autopilot/engine/file_lock_registry.py` | Delete (WorkspaceReservation suffices per RFC-222 Q1) |

**GoalNode enhancement (absorbs Goal fields):**

```python
class GoalNode(BaseModel):
    # Existing fields (RFC-624)
    id: str
    description: str
    status: GoalStatus
    priority: int = 50
    parent_id: str | None
    depends_on: list[str] = []
    informs: list[str] = []
    conflicts_with: list[str] = []
    steps: StepDAG
    generating_reasoning: str | None
    source: GoalSource
    total_tokens_used: int = 0
    thread_id: str | None
    assigned_loop_id: str | None

    # Migrated from Goal model
    retry_count: int = 0
    max_retries: int = 2
    max_send_backs: int = 3
    source_file: str | None = None
    workspace: str | None = None
    report: GoalReport | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    # NEW: Dreaming support
    topic: str | None = None
    findings: list[str] = []
    distilled: bool = False
```

**BackoffReasoner migration:**
- Move to `foundation/autopilot/monitor/backoff_reasoner.py`
- Input: `GoalNode` from CE DAG (instead of `Goal`)
- Output: `BackoffDecision` unchanged
- Called by AutopilotMonitor `on_goal_failed` event handler

---

## 3. AutopilotMonitor Architecture

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
foundation/autopilot/monitor/
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

## 4. GoalDAGVerifier (LLM-Based)

**GoalDAGVerifier responsibilities:**

1. **LLM-driven background health verification** — periodic check using LLM to analyze DAG health, detect stale goals, suggest restructuring
2. **LLM-driven post-completion verification** — triggered by `goal_completed` event, LLM analyzes decomposition opportunities and redundancy
3. **LLM-driven placement analysis** — for new goal intake, LLM suggests optimal priority, dependencies, and potential merging with existing goals

**Architecture:**

```
foundation/autopilot/monitor/
├── goal_dag_verifier.py      # GoalDAGVerifier coordinator
├── verifier_prompts.py       # LLM prompt templates for verification
└── verifier_reasoner.py      # DagVerificationReasoner (LLM caller)
```

**GoalDAGVerifier class:**

```python
class GoalDAGVerifier:
    """LLM-driven goal DAG verification and restructuring suggestions."""

    def __init__(self, ce: ContextEngine, config: SootheConfig):
        self._ce = ce
        self._config = config
        self._reasoner = DagVerificationReasoner(config)

    async def verify_dag_health(self) -> DagHealthReport:
        """LLM-driven periodic background verification.

        Process:
          1. Gather full DAG snapshot (goals, statuses, step progress)
          2. Call LLM with DAG_HEALTH_VERIFICATION_PROMPT
          3. Parse LLM response into structured DagHealthReport
          4. Report includes: reset, remove, merge, decompose suggestions

        LLM analyzes:
          - Goals stuck beyond deadline → suggest reset or remove
          - Goals with unmet dependencies for long time → suggest removal
          - Similar pending goals → suggest merge
          - Complex completed goals → suggest decomposition into sub-goals
          - Priority imbalances → suggest adjustments
        """
        # Gather DAG context for LLM
        dag_snapshot = self._build_dag_snapshot()

        # LLM verification
        llm_response = await self._reasoner.verify_health(dag_snapshot)

        # Parse into structured report
        report = DagHealthReport(
            suggest_reset=llm_response.reset_goals,
            suggest_remove=llm_response.remove_goals,
            suggest_merge=llm_response.merge_goals,  # NEW: merge suggestions
            suggest_decompose=llm_response.decompose_goals,  # NEW: decomposition
            suggest_priority_adjust=llm_response.priority_adjustments,
            reasoning=llm_response.reasoning,
        )

        return report

    async def verify_dag_post_completion(self, completed_goal_id: str) -> CompletionAnalysis:
        """LLM-driven analysis after goal completion.

        Process:
          1. Gather completed goal + its steps + outcomes
          2. Gather pending goals that may be affected
          3. Call LLM with POST_COMPLETION_VERIFICATION_PROMPT
          4. Parse into CompletionAnalysis

        LLM analyzes:
          - Should completed goal be decomposed into sub-goals?
          - Are pending goals now redundant given completion results?
          - Should new follow-up goals be created?
          - Can pending goals proceed now (dependencies satisfied)?
        """
        completed = await self._ce.get_goal(completed_goal_id)
        pending = self._ce.get_goals_by_status("pending")
        recent_ledger = self._ce.get_ledger_entries(phases=["execute_step", "plan"])

        # Build context for LLM
        completion_context = CompletionVerificationContext(
            completed_goal=completed,
            pending_goals=pending,
            ledger_summary=self._summarize_ledger(recent_ledger),
        )

        # LLM verification
        llm_response = await self._reasoner.verify_post_completion(completion_context)

        return CompletionAnalysis(
            suggest_create=llm_response.new_goals,
            suggest_remove=llm_response.redundant_goals,
            suggest_activate=llm_response.ready_goals,
            decomposition=llm_response.decomposition,
            reasoning=llm_response.reasoning,
        )

    async def analyze_placement(self, description: str) -> GoalPlacement:
        """LLM-driven placement analysis for new goal.

        Process:
          1. Gather current DAG state (active, pending, recently completed)
          2. Call LLM with GOAL_PLACEMENT_PROMPT
          3. Parse into GoalPlacement

        LLM analyzes:
          - Optimal priority given current DAG load and importance
          - Dependencies on existing goals (hard and soft)
          - Potential merging with similar pending goals
          - Estimated complexity and execution time
        """
        # Gather current DAG context
        active = self._ce.get_goals_by_status("active")
        pending = self._ce.get_goals_by_status("pending")
        completed_recent = [g for g in self._ce.get_goals_by_status("completed")][-5:]

        placement_context = GoalPlacementContext(
            new_goal_description=description,
            active_goals=active,
            pending_goals=pending,
            recent_completed=completed_recent,
        )

        # LLM placement analysis
        llm_response = await self._reasoner.analyze_placement(placement_context)

        return GoalPlacement(
            adjusted_priority=llm_response.priority,
            suggested_dependencies=llm_response.depends_on,
            suggested_informs=llm_response.informs,
            merge_with=llm_response.merge_with,  # NEW: suggest merging
            estimated_complexity=llm_response.complexity,
            reasoning=llm_response.reasoning,
        )
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
        prompt = POST_COMPLETION_VERIFICATION_PROMPT.format(
            completed_goal=context.completed_goal.description,
            completed_steps=context.completed_goal.steps.summary(),
            pending_goals=[g.description for g in context.pending_goals],
            ledger_summary=context.ledger_summary,
        )

        response = await self._model.ainvoke([SystemMessage(prompt)])
        return CompletionVerificationResponse.model_validate_json(response.content)

    async def analyze_placement(self, context: GoalPlacementContext) -> GoalPlacementResponse:
        """Call LLM for placement analysis."""
        prompt = GOAL_PLACEMENT_PROMPT.format(
            new_goal=context.new_goal_description,
            active_goals=[g.description for g in context.active_goals],
            pending_goals=[g.description for g in context.pending_goals],
            recent_completed=[g.description for g in context.recent_completed],
        )

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

**DagHealthReport model (updated):**

```python
@dataclass
class DagHealthReport:
    suggest_reset: list[str] = []
    suggest_remove: list[str] = []
    suggest_merge: list[MergeSuggestion] = []
    suggest_decompose: list[DecomposeSuggestion] = []
    suggest_priority_adjust: dict[str, int] = {}
    reasoning: str = ""
    errors: list[str] = []
```

**Prompt Templates:**

```python
# verifier_prompts.py

DAG_HEALTH_VERIFICATION_PROMPT = """
You are a Goal DAG Health Verifier. Analyze the current goal DAG and suggest restructuring.

Current DAG Summary:
{dag_summary}

Goals Detail:
{goals_detail}

Step Progress:
{step_progress}

Analyze and respond with JSON containing:
- reset_goals: IDs of goals stuck beyond deadline that should be reset to pending
- remove_goals: IDs of goals that are stale/orphaned and should be removed
- merge_goals: List of {goals: [ids], merged_description: "..."} for similar goals to merge
- decompose_goals: List of {goal_id: "...", subgoals: [{description: "..."}]} for complex goals to decompose
- priority_adjustments: {goal_id: new_priority} for priority rebalancing
- reasoning: Brief explanation of your analysis

Constraints:
- Only suggest removing goals with no dependents
- Merge goals that are semantically similar and pending
- Decompose complex completed goals with >10 steps or high token usage
"""

POST_COMPLETION_VERIFICATION_PROMPT = """
You are a Goal Completion Analyzer. Analyze the completed goal and suggest DAG updates.

Completed Goal: {completed_goal}
Steps Executed: {completed_steps}

Pending Goals: {pending_goals}

Recent Ledger: {ledger_summary}

Analyze and respond with JSON containing:
- new_goals: List of {description, priority, depends_on} for follow-up goals
- redundant_goals: IDs of pending goals now unnecessary due to completion
- ready_goals: IDs of pending goals now ready to execute (deps satisfied)
- decomposition: {parent_id, subgoals: [{description}]} if goal should spawn sub-goals
- reasoning: Brief explanation

Constraints:
- New goals should have clear dependency on completed goal
- Only mark redundant if completion directly obviates the pending goal
- Decompose if outcome reveals additional work needed
"""

GOAL_PLACEMENT_PROMPT = """
You are a Goal Placement Analyzer. Analyze optimal placement for a new goal.

New Goal: {new_goal}

Active Goals: {active_goals}
Pending Goals: {pending_goals}
Recently Completed: {recent_completed}

Analyze and respond with JSON containing:
- priority: Integer 0-100 (higher = more urgent)
- depends_on: Goal IDs this goal must wait for (hard deps)
- informs: Goal IDs this goal provides context to (soft deps)
- merge_with: Goal ID to merge with if similar existing goal exists
- complexity: "simple" | "moderate" | "complex"
- reasoning: Brief explanation

Constraints:
- depends_on only on completed or active goals
- merge_with only if semantically overlapping with pending goal
- Consider current DAG load for priority (high load → lower priority to queue)
"""
```

---

## 5. GoalIntakeHandler

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

## 6. DreamingCoordinator (LLM-Based Distillation)

**DreamingCoordinator responsibilities:**

Coordinate 4 LLM-driven memory distillation modes, triggered by DAG completion OR time interval. Each mode uses LLM to analyze execution history and extract distilled knowledge.

**Architecture:**

```
foundation/autopilot/monitor/
├── dreaming_coordinator.py   # DreamingCoordinator orchestrator
├── dreaming_reasoner.py      # DreamingDistillationReasoner (LLM caller)
├── dreaming_prompts.py       # LLM prompt templates for each mode
└── dreaming_handlers/        # Per-mode handler implementations
    ├── __init__.py
    ├── episodic_handler.py   # Episodic memory distillation
    ├── procedure_handler.py  # Skill/procedure extraction
    ├── semantic_handler.py   # Project MEMORY.md update
    └── profile_handler.py    # User profile extraction
```

**DreamingCoordinator class:**

```python
class DreamingCoordinator:
    """LLM-driven multi-mode memory distillation."""

    def __init__(self, ce: ContextEngine, config: SootheConfig, bus: InternalEventBus):
        self._ce = ce
        self._config = config
        self._bus = bus
        self._reasoner = DreamingDistillationReasoner(config)
        self._mode_handlers = {
            "episodic": EpisodicDistillationHandler(ce, config, self._reasoner),
            "procedure": ProcedureDistillationHandler(ce, config, self._reasoner),
            "semantic": SemanticDistillationHandler(ce, config, self._reasoner),
            "profile": ProfileDistillationHandler(ce, config, self._reasoner),
        }
        self._dreaming_state: DreamingState = "idle"

    async def enter_dreaming_mode(
        self,
        modes: list[DreamingMode] | None = None,
        scope: DreamingScope = "loop",
    ) -> None:
        """Enter dreaming mode and run LLM-driven distillation."""
        if self._dreaming_state == "active":
            return

        self._dreaming_state = "active"
        await self._bus.emit(DreamingModeEnteredEvent())

        enabled_modes = modes or self._config.dreaming.enabled_modes
        context = await self._gather_dreaming_context(scope)

        for mode in enabled_modes:
            handler = self._mode_handlers[mode]
            result = await handler.distill(context)
            await self._apply_distillation_result(mode, result)

        self._dreaming_state = "idle"
        await self._bus.emit(DreamingModeExitedEvent())

    async def _gather_dreaming_context(self, scope: DreamingScope) -> DreamingContext:
        """Gather goals and ledger based on scope."""
        if scope == "loop":
            goals = self._ce.get_all_goals()
            ledger = self._ce.get_ledger_entries()
            return DreamingContext(goals=goals, ledger=ledger, scope_id=self._ce.loop_id)
        elif scope == "workspace":
            aggregated = await self._aggregate_ce_by_workspace(workspace)
            return DreamingContext(goals=aggregated.goals, ledger=aggregated.ledger, scope_id=workspace)
        elif scope == "topic":
            # Topic-tagged goals across loops
            ...
```

**DreamingDistillationReasoner (LLM caller):**

```python
class DreamingDistillationReasoner:
    """LLM-based reasoning for memory distillation."""

    def __init__(self, config: SootheConfig):
        self._model = config.create_chat_model("reason")

    async def distill_episodic(self, context: EpisodicDistillationContext) -> EpisodicDistillationResponse:
        """LLM distills goals into episodic memory summaries."""
        prompt = EPISODIC_DISTILLATION_PROMPT.format(
            goals_summary=context.goals_summary,
            key_interactions=context.key_interactions,
            outcomes=context.outcomes,
        )
        response = await self._model.ainvoke([SystemMessage(prompt)])
        return EpisodicDistillationResponse.model_validate_json(response.content)

    async def distill_procedure(self, context: ProcedureDistillationContext) -> ProcedureDistillationResponse:
        """LLM extracts reusable procedures (Skills) from successful sequences."""
        prompt = PROCEDURE_DISTILLATION_PROMPT.format(
            successful_goals=context.successful_goals,
            step_sequences=context.step_sequences,
            tool_patterns=context.tool_patterns,
        )
        response = await self._model.ainvoke([SystemMessage(prompt)])
        return ProcedureDistillationResponse.model_validate_json(response.content)

    async def distill_semantic(self, context: SemanticDistillationContext) -> SemanticDistillationResponse:
        """LLM generates project MEMORY.md updates."""
        prompt = SEMANTIC_DISTILLATION_PROMPT.format(
            findings=context.findings,
            decisions=context.decisions,
            patterns=context.patterns,
            current_memory_md=context.current_memory_md,
        )
        response = await self._model.ainvoke([SystemMessage(prompt)])
        return SemanticDistillationResponse.model_validate_json(response.content)

    async def distill_profile(self, context: ProfileDistillationContext) -> ProfileDistillationResponse:
        """LLM extracts user preferences and communication patterns."""
        prompt = PROFILE_DISTILLATION_PROMPT.format(
            user_messages=context.user_messages,
            feedback_patterns=context.feedback_patterns,
            goal_preferences=context.goal_preferences,
        )
        response = await self._model.ainvoke([SystemMessage(prompt)])
        return ProfileDistillationResponse.model_validate_json(response.content)
```

**LLM-Based Handler Implementations:**

```python
# Episodic: LLM summarizes goal execution into narrative episodes
class EpisodicDistillationHandler:
    def __init__(self, ce: ContextEngine, config: SootheConfig, reasoner: DreamingDistillationReasoner):
        self._ce = ce
        self._reasoner = reasoner

    async def distill(self, context: DreamingContext) -> DistillationResult:
        completed = [g for g in context.goals if g.status == "completed" and not g.distilled]

        # Build context for LLM
        episodic_context = EpisodicDistillationContext(
            goals_summary=[self._summarize_goal(g) for g in completed[-10:]],
            key_interactions=self._extract_key_interactions(context.ledger),
            outcomes=[g.report.completion_text if g.report else "" for g in completed],
        )

        # LLM distillation
        llm_response = await self._reasoner.distill_episodic(episodic_context)

        # Build episodes from LLM response
        episodes = []
        for ep in llm_response.episodes:
            episodes.append(EpisodeSummary(
                goal_id=ep.goal_id,
                description=ep.description,
                outcome_summary=ep.outcome_summary,
                key_steps=ep.key_steps,
                lessons_learned=ep.lessons_learned,
            ))

        return DistillationResult(mode="episodic", summaries=episodes, reasoning=llm_response.reasoning)

# Procedure: LLM extracts reusable Skills from successful patterns
class ProcedureDistillationHandler:
    def __init__(self, ce: ContextEngine, config: SootheConfig, reasoner: DreamingDistillationReasoner):
        self._ce = ce
        self._reasoner = reasoner

    async def distill(self, context: DreamingContext) -> DistillationResult:
        successful = [g for g in context.goals
                      if g.status == "completed"
                      and g.steps.success_rate > 0.8
                      and not g.distilled]

        # Build context for LLM
        procedure_context = ProcedureDistillationContext(
            successful_goals=[self._summarize_goal(g) for g in successful],
            step_sequences=[self._extract_step_sequence(g) for g in successful],
            tool_patterns=self._analyze_tool_patterns(successful),
        )

        # LLM distillation
        llm_response = await self._reasoner.distill_procedure(procedure_context)

        # Build Skill specs from LLM response
        procedures = []
        for proc in llm_response.procedures:
            procedures.append(SkillSpec(
                name=proc.name,
                description=proc.description,
                trigger_conditions=proc.trigger_conditions,
                steps=proc.steps,
                tools_used=proc.tools_used,
            ))

        return DistillationResult(mode="procedure", procedures=procedures, reasoning=llm_response.reasoning)

# Semantic: LLM updates project MEMORY.md
class SemanticDistillationHandler:
    def __init__(self, ce: ContextEngine, config: SootheConfig, reasoner: DreamingDistillationReasoner):
        self._ce = ce
        self._reasoner = reasoner

    async def distill(self, context: DreamingContext) -> DistillationResult:
        completed = [g for g in context.goals if g.status == "completed" and not g.distilled]

        # Gather findings, decisions, patterns from goals
        semantic_context = SemanticDistillationContext(
            findings=[f for g in completed for f in g.findings],
            decisions=self._extract_decisions(context.ledger),
            patterns=self._extract_patterns(completed),
            current_memory_md=self._load_current_memory_md(),
        )

        # LLM distillation
        llm_response = await self._reasoner.distill_semantic(semantic_context)

        # Build MEMORY.md update
        semantic_update = MemoryMdUpdate(
            additions=llm_response.additions,
            modifications=llm_response.modifications,
            sections_to_update=llm_response.sections_to_update,
        )

        return DistillationResult(mode="semantic", semantic_updates=[semantic_update], reasoning=llm_response.reasoning)

# Profile: LLM extracts user preferences
class ProfileDistillationHandler:
    def __init__(self, ce: ContextEngine, config: SootheConfig, reasoner: DreamingDistillationReasoner):
        self._ce = ce
        self._reasoner = reasoner

    async def distill(self, context: DreamingContext) -> DistillationResult:
        # Extract user interactions
        user_messages = [m.content for m, _ in context.ledger if isinstance(m, HumanMessage)]

        # Build context for LLM
        profile_context = ProfileDistillationContext(
            user_messages=user_messages[-50:],  # Recent user inputs
            feedback_patterns=self._extract_feedback_patterns(context.ledger),
            goal_preferences=self._analyze_goal_preferences(context.goals),
        )

        # LLM distillation
        llm_response = await self._reasoner.distill_profile(profile_context)

        # Build profile update
        profile_update = UserProfileUpdate(
            communication_style=llm_response.communication_style,
            preferences=llm_response.preferences,
            recurring_goals=llm_response.recurring_goals,
            expertise_level=llm_response.expertise_level,
        )

        return DistillationResult(mode="profile", profile_updates=[profile_update], reasoning=llm_response.reasoning)
```

**LLM Response Models (structured output):**

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
    additions: list[str]  # New sections to add
    modifications: dict[str, str]  # Section → updated content
    sections_to_update: list[str]
    reasoning: str

class ProfileDistillationResponse(BaseModel):
    communication_style: str
    preferences: list[str]
    recurring_goals: list[str]
    expertise_level: Literal["beginner", "intermediate", "advanced", "expert"]
    reasoning: str
```

**Prompt Templates:**

```python
# dreaming_prompts.py

EPISODIC_DISTILLATION_PROMPT = """
You are an Episodic Memory Distiller. Transform goal execution history into memorable episodes.

Goals Summary:
{goals_summary}

Key Interactions:
{key_interactions}

Outcomes:
{outcomes}

Analyze and respond with JSON containing:
- episodes: List of {goal_id, description, outcome_summary, key_steps, lessons_learned}
- reasoning: Brief explanation of what patterns you identified

Each episode should:
- Be a concise narrative (not a log)
- Capture the essential problem and solution
- Include lessons learned for future reference
- Focus on decisions that mattered
"""

PROCEDURE_DISTILLATION_PROMPT = """
You are a Procedure Extractor. Identify reusable Skills from successful goal executions.

Successful Goals:
{successful_goals}

Step Sequences:
{step_sequences}

Tool Patterns:
{tool_patterns}

Analyze and respond with JSON containing:
- procedures: List of {name, description, trigger_conditions, steps, tools_used}
- reasoning: Brief explanation of what makes these procedures reusable

Each procedure should:
- Have clear trigger conditions (when to apply)
- Be abstract enough for reuse but specific enough to execute
- Include the minimal tool set needed
- Avoid capturing one-time specifics
"""

SEMANTIC_DISTILLATION_PROMPT = """
You are a Semantic Memory Updater. Generate updates for project MEMORY.md.

Findings from Goals:
{findings}

Decisions Made:
{decisions}

Patterns Discovered:
{patterns}

Current MEMORY.md:
{current_memory_md}

Analyze and respond with JSON containing:
- additions: New sections to add (full content)
- modifications: {section_name: updated_content} for existing sections
- sections_to_update: List of section names needing update
- reasoning: Brief explanation of what knowledge should be preserved

Updates should:
- Capture architectural decisions and their rationale
- Document patterns that worked well
- Avoid duplicating existing content
- Be concise but informative
"""

PROFILE_DISTILLATION_PROMPT = """
You are a User Profile Analyzer. Extract preferences and patterns from user interactions.

User Messages:
{user_messages}

Feedback Patterns:
{feedback_patterns}

Goal Preferences:
{goal_preferences}

Analyze and respond with JSON containing:
- communication_style: Brief description of user's communication preferences
- preferences: List of identified preferences (formatting, detail level, etc.)
- recurring_goals: List of goal types user frequently requests
- expertise_level: "beginner" | "intermediate" | "advanced" | "expert"
- reasoning: Brief explanation of your analysis

Profile should capture:
- How the user prefers information presented
- Common themes in their requests
- Their apparent domain expertise
- Feedback patterns (what they correct/approve)
"""
```

**DreamingScope and context:**

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

## 7. ContextEngine API Additions

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

## 8. Solo Mode vs Autopilot Mode Behavior

**Core principle: CE DAG persists across goals in both modes.**

| Feature | Solo | Autopilot |
|---------|------|-----------|
| CE DAG | Yes (linear chain) | Yes (full DAG) |
| Goal lineage | Yes (sequential) | Yes (complex) |
| Cross-goal ledger | Yes | Yes |
| ContextBundle prior_goals | Yes | Yes |
| Background verification | No | Yes |
| Proactive restructuring | No | Yes |
| Dreaming | No | Yes |
| New input handling | Queue until completion | Immediate CE update |
| Parallel execution | No | Yes |
| TUI display | PendingGoalQueue | GoalDAGCard |

**Solo mode goal chaining:**

```python
class StrangeLoop:
    async def run_with_progress(self, user_input: str, loop_id: str, autopilot_mode: AutopilotMode):
        await self._ce.load()

        if autopilot_mode == AutopilotMode.SOLO:
            # Create linear-chain goal
            completed_goals = self._ce.get_goals_by_status("completed")
            prev_id = completed_goals[-1].id if completed_goals else None

            goal = await self._ce.create_goal(
                user_input,
                depends_on=[prev_id] if prev_id else [],
                source="user",
            )
            await self._ce.activate_goal(goal.id, loop_id)

        elif autopilot_mode == AutopilotMode.AUTOPILOT_ACTIVE:
            # Goal already created by Monitor
            goal = await self._ce.get_goal(self._pending_goal_id)
            await self._ce.activate_goal(goal.id, loop_id)

        elif autopilot_mode == AutopilotMode.AUTOPILOT_PENDING:
            # Queue to Monitor, don't create goal here
            await self._monitor.intake_goal(user_input)
            return PlanResult(status="queued")

        # Execute graph (same for solo and autopilot_active)
        state.bind_ce(self._ce, goal.id)
        result = await self._run_graph(state)
        await self._ce.finalize_goal(goal.id, status=result.status)
        await self._ce.save()
        return result
```

**AutopilotMode enum:**

```python
class AutopilotMode(StrEnum):
    SOLO = "solo"
    AUTOPILOT_ACTIVE = "autopilot_active"
    AUTOPILOT_PENDING = "autopilot_pending"
```

---

## 9. TUI Goal DAG Card

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

## 10. Live Autopilot Mode Switching

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

## 11. Data Flow Summary

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

## 12. Implementation Phases

| Phase | Scope |
|-------|-------|
| 1 | Relocate `soothe.context` → `soothe.foundation.context` |
| 2 | Enhance GoalNode with Goal fields, add CE API methods |
| 3 | Delete GoalEngine, migrate BackoffReasoner |
| 4 | Implement AutopilotMonitor (Verifier, Intake, Dreaming) |
| 5 | Implement TUI GoalDAGCard, mode switch logic |
| 6 | Integration tests, verify_finally.sh |

---

## 13. Config Additions

```yaml
agent:
  autonomous:
    enabled_by_default: false

    # AutopilotMonitor settings
    verify_interval: 30          # Background verification loop
    dreaming_interval: 300       # Time-based dreaming trigger

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

## 14. Invariants

1. ContextEngine is the sole source of truth for goal/step data.
2. AutopilotMonitor calls CE public APIs for all DAG mutations.
3. CE DAG persists across goals in both solo and autopilot modes.
4. Solo mode builds linear chain; autopilot mode builds full DAG.
5. Mode switching preserves CE DAG (completed goals remain).
6. All events flow through InternalEventBus for TUI/subscriber updates.
7. DreamingCoordinator runs only when DAG complete OR timer trigger.
8. BackoffReasoner migrates to monitor, called on goal_failed events.

---

## References

- RFC-624: Context Engine
- RFC-222: Autopilot and Goal Engine Architecture
- RFC-200: Autonomous Goal Management (GoalEngine specification - to be superseded)
- RFC-221: Loop Runner Protocol