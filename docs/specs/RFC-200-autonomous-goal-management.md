# RFC-200: Layer 3 - Autonomous Goal Management Loop

**RFC**: 200
**Title**: Layer 3: Autonomous Goal Management Loop
**Status**: Implemented
**Kind**: Architecture Design
**Created**: 2026-03-15
**Updated**: 2026-04-17
**Dependencies**: RFC-000, RFC-001, RFC-500, RFC-201

## Abstract

This RFC defines Layer 3 of Soothe's three-layer execution architecture: autonomous goal management for long-running complex workflows. Layer 3 manages goal DAGs with dependencies, priorities, and dynamic restructuring capabilities. It delegates single-goal execution to Layer 2 (RFC-201) through explicit PERFORM → Layer 2 delegation, and receives PlanResult for Layer 3 reflection. This RFC merges and supersedes RFC-0011 (Dynamic Goal Management).

## Architecture Position

### Three-Layer Model

Soothe operates through a hierarchical execution model with three distinct layers:

```
Layer 3: Autonomous Goal Management (this RFC)
  ├─ Scope: Long-running complex workflows, multi-goal DAGs
  ├─ Loop: Goal/Goals → PLAN → PERFORM → REFLECT → Update → repeat
  └─ Delegation: PERFORM invokes Layer 2's full Plan → Execute loop

Layer 2: Agentic Goal Execution (RFC-201)
  ├─ Scope: Single-goal execution through iterative refinement
  ├─ Loop: Plan → Execute (max iterations: ~8)
  └─ Delegation: Execute invokes Layer 1 CoreAgent for step execution

Layer 1: CoreAgent Runtime (RFC-100)
  ├─ Foundation: create_soothe_agent() → CompiledStateGraph
  └─ Execution: Model → Tools → Model loop (LangGraph native)
```

### Layer 3 Responsibilities

Layer 3 operates at the highest abstraction level, focusing on goal lifecycle management rather than execution details:

- **Goal DAG orchestration**: Create, schedule, and manage goals with dependencies
- **Goal-level planning**: Decompose complex objectives into goal DAGs
- **Delegation to Layer 2**: PERFORM stage invokes Layer 2's complete loop
- **Goal DAG reflection**: Evaluate progress across multiple goals using Layer 2 PlanResult
- **Dynamic goal restructuring**: Mutate goal DAG based on execution learning
- **Large iteration budgets**: Support complex problem solving (10-50+ iterations)

### Integration with Layer 2

**AgentLoop Goal Pull Architecture** (Inverted Control Flow):

Layer 2 AgentLoop actively queries Layer 3 GoalEngine for goal assignment (pull-based). GoalEngine provides goal state service, never invokes AgentLoop.

```python
# AgentLoop initialization (run_with_progress)
async def run_with_progress(...):
    # PULL: AgentLoop queries GoalEngine for current goal
    goal_engine = config.resolve_goal_engine()
    current_goal = goal_engine.get_next_ready_goal()  # Pull-based assignment
    
    if not current_goal:
        logger.info("No goals ready for execution")
        return None
    
    # AgentLoop owns execution loop
    thread_id = f"{base_tid}__goal_{current_goal.id}"
    state = LoopState(
        current_goal_id=current_goal.id,
        goal_text=current_goal.description,
        thread_id=thread_id,
    )
    
    # Execute Layer 2 Plan → Execute loop (AgentLoop drives)
    plan_result = await self.run_iteration(state)
    
    # REPORT: AgentLoop reports completion to GoalEngine
    if plan_result.status == "done":
        goal_engine.complete_goal(
            goal_id=current_goal.id,
            plan_result=plan_result,
        )
    
    return plan_result
```

**Goal Pull Integration Contract**:

| Trigger | AgentLoop Action | GoalEngine Response |
|---------|------------------|---------------------|
| Goal assignment | `get_next_ready_goal()` | Return highest-priority DAG-satisfied goal |
| Goal completion | `complete_goal(goal_id, plan_result)` | Update goal status, store GoalReport |
| Goal failure | `fail_goal(goal_id, evidence)` | Apply BackoffReasoner, mutate DAG |

**Architectural Principle**: AgentLoop drives execution timing, GoalEngine provides goal state service. GoalEngine never invokes AgentLoop (inverted control flow).

## Loop Model

### Execution Flow

```text
User Input
    |
    v
GoalEngine.create_goal(user_input) → root goal
    |
    v
while total_iterations < max_iterations and not GoalEngine.is_complete():
    |
    v
    ready_goals = GoalEngine.ready_goals(limit=max_parallel_goals)
    |
    +-- if multiple ready goals:
    |      execute goals in parallel batches
    |
    +-- for each executing goal (PERFORM stage):
           |
           +-- Delegate to Layer 2's Plan → Execute loop
           |      Receive: PlanResult with evidence_summary, goal_progress
           |
           +-- REFLECT stage:
           |      PlannerProtocol.reflect(..., goal_context, layer2_judgment)
           |      Generate: Reflection + GoalDirective[]
           |
           +-- Apply GoalDirective if present:
           |      - Create new goals
           |      - Adjust priorities
           |      - Add dependencies
           |      - Decompose goals
           |      - Fail/complete goals
           |
           +-- DAG consistency check:
           |      If current goal dependencies no longer satisfied:
           |        - Reset goal to "pending"
           |        - Abort iteration early
           |        - Let scheduler pick up prerequisites
           |
           +-- Store IterationRecord in ContextProtocol
           |
           +-- if should_revise:
           |      PlannerProtocol.revise_plan()
           |      continue on next autonomous iteration
           |
           +-- else:
                  synthesize goal report
                  GoalEngine.complete_goal()
```

### Iteration Semantics

- **Max iterations**: Large budget (10-50+) for complex problem solving
- **Goal lifecycle**: Create → Activate → Execute (via Layer 2) → Reflect → Complete/Fail
- **DAG scheduling**: Goals execute when dependencies satisfied, parallel batches when independent
- **Evidence flow**: Layer 2 PlanResult → Layer 3 REFLECT → goal directives → DAG restructuring

## Components

### 1. GoalEngine (`cognition/goal_engine.py`)

Goal lifecycle manager driven synchronously by the runner.

**Goal Model**:
```python
class Goal(BaseModel):
    id: str  # 8-char hex identifier
    description: str  # Human-readable goal text
    status: Literal["pending", "active", "completed", "failed"]
    priority: int  # 0-100, higher = first
    parent_id: str | None  # Parent for hierarchical goals
    depends_on: list[str]  # Prerequisite goal IDs for DAG scheduling
    plan_count: int  # Counter for revised plan IDs
    retry_count: int
    max_retries: int
    report: GoalReport | None
    created_at: datetime
    updated_at: datetime
```

**GoalEngine Interface**:

**Core Operations**:
- `create_goal(description, priority, parent_id)` → Goal
- `next_goal()` → Goal | None (backward-compatible single-goal)
- `ready_goals(limit)` → list[Goal] (DAG-satisfied, activated goals)
- `complete_goal(goal_id, plan_result)` → None (mark completed with Layer 2 evidence)
- `fail_goal(goal_id, evidence, allow_retry)` → BackoffDecision | None (apply backoff reasoning)
- `list_goals(status)` → list[Goal]
- `get_goal(goal_id)` → Goal | None (query goal metadata)
- `snapshot()` → dict (checkpoint persistence)
- `restore_from_snapshot(snapshot)` → None

**Dependency Management**:
- `add_dependencies(goal_id, depends_on)` → None (cycle-safe)
- `validate_dependency(goal_id, depends_on)` → bool

**Service Provider Role**: GoalEngine never invokes AgentLoop (inverted control flow). AgentLoop queries GoalEngine via pull-based API.

**DAG Scheduling**:
- `ready_goals(limit)` returns goals whose `depends_on` are all completed
- Goals sorted by `(-priority, created_at)` (higher priority first)
- Returned goals activated (status: "pending" → "active")
- Parallel execution when `len(ready_goals) > 1`

**Integration with Layer 2**: GoalEngine provides goal state service. AgentLoop queries via `get_next_ready_goal()`, reports via `complete_goal()` / `fail_goal()` (§48-82).

### 2. GoalBackoffReasoner (`cognition/goal_engine/backoff_reasoner.py`)

**Canonical ownership note**: This RFC is the single source of truth for `GoalBackoffReasoner`, `BackoffDecision`, and goal-failure backoff semantics. Other RFCs reference these models for integration only and must not redefine authoritative schemas.

LLM-driven backoff reasoning for goal DAG restructuring. When goal execution fails, the reasoner analyzes full goal context and decides WHERE to backoff in the goal DAG, replacing hardcoded retry logic with reasoning-based decisions.

**BackoffDecision Model**:

```python
class BackoffDecision(BaseModel):
    """LLM-driven backoff decision for goal DAG restructuring."""

    backoff_to_goal_id: str
    """Target goal to backoff to (where to resume in DAG)."""

    reason: str
    """Natural language reasoning for backoff decision."""

    new_directives: list[GoalDirective] = []
    """Additional directives to apply after backoff."""

    evidence_summary: str
    """Summary of why current goal path failed."""
```

### Shared Evidence Contract (Canonical)

Layer 2 and Layer 3 exchange failure and progress evidence through a shared contract to avoid schema drift across AgentLoop, GoalEngine, and context ingestion.

```python
class EvidenceBundle(BaseModel):
    """Canonical evidence payload exchanged across Layer 2 and Layer 3."""

    structured: dict[str, Any]
    """Machine-readable execution metrics/state for deterministic processing."""

    narrative: str
    """Natural language synthesis for LLM reasoning and operator visibility."""

    source: Literal["layer2_execute", "layer2_plan", "layer3_reflect"]
    """Evidence producer stage."""

    timestamp: datetime
    """Evidence emission time."""

class GoalSubDAGStatus(BaseModel):
    """Canonical DAG execution status for backoff and reflection."""

    execution_states: dict[str, Literal["pending", "running", "success", "failed", "backoff_pending"]]
    """Per-goal execution state."""

    backoff_points: list[str]
    """Goal IDs selected as backoff boundaries."""

    evidence_annotations: dict[str, EvidenceBundle]
    """Per-goal evidence mapping."""
```

**Contract mapping**:
- Layer 2 `PlanResult.evidence_summary` is translated into `EvidenceBundle.narrative`.
- Layer 2 wave/step metrics populate `EvidenceBundle.structured`.
- Layer 3 backoff/reflection updates `GoalSubDAGStatus` and appends evidence annotations.
- `ContextProtocol.ingest()` stores compact summaries with references to these canonical structures.

**GoalBackoffReasoner Interface**:

```python
class GoalBackoffReasoner:
    def __init__(self, config: SootheConfig) -> None:
        self._model = config.create_chat_model("reason")
        self._prompt_template = BACKOFF_REASONING_PROMPT

    async def reason_backoff(
        self,
        goal_id: str,
        goal_context: GoalContext,
        failed_evidence: str,
    ) -> BackoffDecision:
        """
        LLM analyzes full goal context and decides WHERE to backoff.

        Args:
            goal_id: Failed goal identifier
            goal_context: Snapshot of all goals (RFC-200 GoalContext)
            failed_evidence: Evidence from Layer 2 execution

        Returns:
            BackoffDecision with backoff point + reasoning + directives
        """
```

**GoalEngine API for Layer 2 Integration**:

```python
class GoalEngine:
    """Layer 3 Goal Lifecycle Manager (Service Provider).
    
    Provides goal state service for AgentLoop queries.
    Never invokes AgentLoop (inverted control flow).
    """
    
    def get_next_ready_goal(self) -> Goal | None:
        """Get next goal ready for execution (DAG-satisfied, highest priority).
        
        Called by: AgentLoop before starting Layer 2 loop.
        
        Returns:
            Goal with dependencies satisfied, or None if no goals ready.
        """
        ready_goals = self.ready_goals(limit=1)
        if not ready_goals:
            return None
        
        goal = ready_goals[0]
        goal.status = "active"  # Activate on assignment
        return goal
    
    def complete_goal(
        self,
        goal_id: str,
        plan_result: PlanResult,  # From Layer 2
    ) -> None:
        """Mark goal completed with Layer 2 execution evidence.
        
        Called by: AgentLoop after successful Plan → Execute loop.
        
        Args:
            goal_id: Completed goal identifier.
            plan_result: Layer 2 final result with evidence_summary.
        """
        goal = self._goals[goal_id]
        goal.status = "completed"
        goal.updated_at = datetime.now()
        
        goal.report = GoalReport(
            goal_id=goal_id,
            summary=plan_result.evidence_summary,
            iteration_count=...,  # Extract from execution context
            step_count=...,       # Extract from execution history
            final_plan_result=plan_result,
        )
        
        # Emit event for observability (optional)
        emit_event(GoalCompletedEvent(...))
    
    async def fail_goal(
        self,
        goal_id: str,
        evidence: EvidenceBundle,  # Layer 2 failure evidence (RFC-200 §14-22)
        allow_retry: bool = True,
    ) -> BackoffDecision | None:
        """Mark goal failed with evidence, apply backoff reasoning.
        
        Called by: AgentLoop when Layer 2 execution fails.
        
        Args:
            goal_id: Failed goal identifier.
            evidence: Layer 2 execution evidence (RFC-200 EvidenceBundle contract).
            allow_retry: Whether retry is allowed.
        
        Returns:
            BackoffDecision if backoff reasoning applied, None if no retry.
        
        Backoff reasoning (GoalEngine internal):
        - Call GoalBackoffReasoner with goal context + evidence
        - Apply BackoffDecision (DAG restructuring)
        - Reset backoff target goal to "pending"
        
        Encapsulation: AgentLoop never calls BackoffReasoner directly.
        """
        goal = self._goals[goal_id]
        goal.status = "failed"
        goal.error = evidence.narrative
        goal.retry_count += 1
        
        if allow_retry and goal.retry_count < goal.max_retries:
            # GoalEngine owns backoff reasoning (encapsulated)
            goal_context = self._build_goal_context(goal_id)
            decision = await self._backoff_reasoner.reason_backoff(
                goal_id=goal_id,
                goal_context=goal_context,
                failed_evidence=evidence,
            )
            
            # Apply backoff decision (GoalEngine internal)
            self._apply_backoff_decision(decision)
            return decision
        
        return None
```

**Backoff Reasoning Logic**:
- LLM considers full goal DAG context (all goals + dependencies + execution evidence)
- Decides optimal backoff point (where to resume after failure)
- Generates GoalDirective for dynamic restructuring
- Replaces hardcoded retry with reasoning-based recovery

**Configuration**:

```yaml
autonomous:
  goal_backoff:
    enabled: true
    llm_role: reason  # Use reasoning model for backoff decisions
    max_backoff_depth: 3  # Limit backoff chain depth
```

### 2.1 GoalBackoffReasoner Integration Pattern

**Purpose**: Replace hardcoded exponential backoff with LLM-driven reasoning that analyzes full goal DAG context and decides optimal backoff strategy.

**Ownership Boundary**:
- **Layer 2 (RFC-201)**: Produces execution evidence and failure context via `EvidenceBundle`
- **Layer 3 (RFC-200)**: Defines and executes GoalBackoffReasoner policy and BackoffDecision
- **Shared contract**: EvidenceBundle (RFC-200 §14-22) with structured + narrative fields
- **Encapsulation**: AgentLoop never calls BackoffReasoner directly; GoalEngine owns backoff reasoning

**Integration Pattern** (Layer 2 → Layer 3 handoff):

```python
# AgentLoop.Executor failure detection
async def execute(self, decision: AgentDecision, state: LoopState):
    try:
        results = await self.core_agent.astream(...)
        
        if execution_failed(results):
            # BUILD: AgentLoop constructs EvidenceBundle
            evidence = EvidenceBundleBuilder().build_from_plan_result(
                plan_result=state.last_plan_result,
                wave_metrics=state.last_wave_metrics,  # RFC-201 §236-245
                iteration=state.iteration,
            )
            
            # HANDOFF: AgentLoop → GoalEngine with evidence
            goal_engine = self.config.resolve_goal_engine()
            backoff_decision = await goal_engine.fail_goal(
                goal_id=state.current_goal_id,
                evidence=evidence,
                allow_retry=True,
            )
            
            # REACT: Log decision (GoalEngine already applied internally)
            if backoff_decision:
                logger.info(
                    "Goal %s backoff: %s → %s",
                    state.current_goal_id,
                    backoff_decision.reason,
                    backoff_decision.backoff_to_goal_id,
                )
            
            return FailureResult(backoff_decision=backoff_decision)
```

**EvidenceBundle Contract** (RFC-200 §14-22 canonical structure):

```python
class EvidenceBundle(BaseModel):
    """Canonical evidence payload for Layer 2 → Layer 3 handoff."""
    
    structured: dict[str, Any]
    """Machine-readable execution metrics from RFC-201 LoopState §236-245.
    
    Examples:
    - iteration: int
    - wave_tool_calls: int (last_wave_tool_call_count)
    - wave_errors: int (last_wave_error_count)
    - goal_progress: float
    - confidence: float
    """
    
    narrative: str
    """Natural language synthesis for LLM reasoning.
    
    Synthesized from:
    - PlanResult.reasoning
    - PlanResult.evidence_summary
    - PlanResult.user_summary
    - Wave metrics pattern analysis
    """
    
    source: Literal["layer2_execute", "layer2_plan", "layer3_reflect"]
    """Evidence producer stage."""
    
    timestamp: datetime
    """Evidence emission time."""
```

**GoalEngine Internal Backoff Application**:

```python
# GoalEngine internal (encapsulated, not called by AgentLoop)
def _apply_backoff_decision(self, decision: BackoffDecision) -> None:
    """Apply backoff decision to Goal DAG (GoalEngine internal).
    
    Args:
        decision: LLM reasoning result with:
        - backoff_to_goal_id: WHERE to backoff in DAG
        - reason: Natural language reasoning
        - new_directives: GoalDirective[] for restructuring
    """
    backoff_goal = self._goals[decision.backoff_to_goal_id]
    backoff_goal.status = "pending"  # Reset for re-execution
    backoff_goal.retry_count = 0
    
    # Apply new directives
    for directive in decision.new_directives:
        self.apply_directive(directive)
    
    logger.info(
        "Goal backoff applied: goal %s → backoff to %s",
        decision.backoff_to_goal_id,
        decision.reason,
    )
    
    # Persist DAG mutation
    self._persist_goal_state()
```

**LLM Prompt Structure**:
- Input: Failed goal ID, full goal DAG snapshot (all goals + dependencies + statuses), EvidenceBundle
- Output: Structured BackoffDecision JSON
- Reasoning dimensions:
  1. Retry appropriateness (transient vs permanent failure)
  2. Backoff target selection (which goal to resume from)
  3. New directive generation (guidance for retry)

**Configuration Schema**:
```yaml
autonomous:
  goal_backoff:
    enabled: true
    llm_role: reason  # Use reasoning-optimized model
    max_backoff_depth: 3  # Limit backoff chain depth
```

**Design Principle**: GoalEngine backoff is reasoning process (LLM) not rule process - fundamentally different from traditional DAG rollback algorithms. LLM considers entire execution history to decide optimal recovery strategy.

### 3. GoalContext Construction for Plan Phase

**Dependency-Driven Retrieval Architecture**:

AgentLoop Plan phase requires dependency-aware context synthesized from GoalEngine goal metadata and ContextProtocol retrieval.

**Synthesis Strategy**:
1. **GoalEngine.get_goal()** → current goal metadata (priority, dependencies)
2. **Dependency retrieval**: For each dependency goal, retrieve execution history from ContextProtocol
3. **Current goal retrieval**: Goal-centric context for current problem
4. **Previous goal summaries**: Execution patterns from GoalContextManager

**Entry Limits** (fixed, no token budget):
- Dependency context: 5 entries per dependency goal
- Current goal context: 10 entries
- Previous goals: 5 summaries

**PlanContext Data Model**:

```python
class PlanContext(BaseModel):
    """Dependency-aware context for AgentLoop Plan phase."""
    
    entries: list[ContextEntry]
    """Combined entries: dependency + current + previous goals.
    
    Entry metadata:
    - goal_id: Source goal identifier
    - goal_text: Goal description
    - goal_priority: GoalEngine priority (0-100)
    - dependency_relation: "prerequisite" | "current" | "previous_goal"
    """
    
    metadata: dict[str, Any]
    """Synthesis metadata: goal_id, priority, dependencies, entry counts."""
```

**Integration Point**: AgentLoop calls `GoalContextConstructor.construct_plan_context(goal_id)` before Plan phase (PULL #1 integration). GoalEngine dependencies drive ContextProtocol retrieval.

**Architectural Principle**: Prerequisite goal execution history provides critical constraints and learned patterns for planning. Goal dependencies define relevant context scope.

### 4. Dynamic Goal Management

Layer 3's reflection can dynamically restructure the goal DAG through structured directives (merged from RFC-0011).

**GoalDirective Model**:

```python
class GoalDirective(BaseModel):
    """Structured action for goal DAG management."""

    action: Literal["create", "adjust_priority", "add_dependency", "decompose", "fail", "complete"]
    goal_id: str | None  # Target goal for directive
    description: str | None  # For create/decompose actions
    priority: int | None  # For adjust_priority
    depends_on: list[str] | None  # For add_dependency
    reason: str  # Why this directive was generated
```

**GoalContext Model**:

```python
class GoalContext(BaseModel):
    """Snapshot of all goals for reflection."""

    current_goal_id: str
    all_goals: list[GoalSnapshot]
    completed_goals: list[str]  # Goal IDs
    failed_goals: list[str]
    ready_goals: list[str]  # Dependency-satisfied
    max_parallel_goals: int
```

**Enhanced Reflection**:

`PlannerProtocol.reflect()` signature extended:

```python
async def reflect(
    self,
    plan: Plan,
    step_results: list[StepResult],
    goal_context: GoalContext | None = None,
    layer2_reason: PlanResult | None = None  # From Layer 2
) -> Reflection:
    """
    Returns:
        Reflection with:
        - assessment: evaluation of overall progress
        - should_revise: whether plan needs revision
        - feedback: guidance for revision
        - goal_directives: DAG restructuring actions
    """
```

### 3.0 Goal evolution (design stance, non-normative)

Product and research language sometimes describe complex goals as **unknowable upfront** or **continually becoming** through evidence. RFCs specify **mechanisms** (directives, backoff, reflection, adaptive mode below) rather than a formal goal ontology. Implementations MUST still enforce DAG safety, cycle checks, and **stable goal IDs for committed nodes** regardless of narrative framing.

### 3.1 Experimental Adaptive Decomposition Mode

The system supports an optional experimental mode for decomposition strategy selection when problem structure is uncertain.

**Design intent**:
- Well-scoped goals: favor hierarchical DAG decomposition.
- Ill-scoped goals: allow temporary fluid decomposition before DAG stabilization.
- Mixed goals: allow staged crystallization from fluid hypotheses to explicit DAG nodes.

**Informative signals (implementation-defined)**:
- How the engine classifies a problem as well-scoped versus ill-scoped (for example planner ambiguity scores, breadth of initial `GoalDirective` set, or explicit operator flags) is **not** fixed by this RFC.
- **Crystallization** from fluid hypotheses to explicit DAG nodes is expected to follow **accumulating execution evidence**; the exact heuristics and telemetry are implementation-defined, subject to the safety constraints below.

**Safety constraints**:
- Disabled by default.
- Must preserve goal ID stability once a node is committed.
- Must pass existing DAG cycle and depth validation before activation.
- Must emit explicit restructuring rationale for observability.

**Configuration**:

```yaml
autonomous:
  adaptive_decomposition:
    enabled: false
    mode: conservative  # conservative | balanced | exploratory
    max_fluid_rounds: 2
```

### 4. Safety Mechanisms

**Cycle Detection**:
- DFS-based validation before adding dependencies
- `_would_create_cycle(goal_id, depends_on)` check
- Prevents infinite loops in dependency graphs

**Depth Validation**:
- `_calculate_goal_depth(goal_id)` for hierarchy depth
- Maximum depth limit (default: 5 levels)
- Prevents unbounded nesting

**Total Goals Limit**:
- Maximum goals allowed (default: 50)
- Prevents runaway goal creation
- Configurable via `autonomous.max_total_goals`

**Validation Before Application**:
- All directives validated before modifying state
- Rejected directives logged with reasons
- Atomic checkpoint after successful application

### 5. DAG Consistency Handling

**Critical Scenario**: When reflection adds a dependency to an active goal, the goal may no longer be executable because its newly added dependencies aren't satisfied yet.

**Solution**:
1. After processing directives, check if current goal's dependencies are still met
2. If not:
   - Reset goal to "pending" status
   - Abort current iteration early
   - Let scheduler pick up higher-priority prerequisite goals on next loop iteration
   - Original goal waits until dependencies complete

**Example Flow**:
```
Goal A (active) executing:
  Reflection adds dependency: A depends_on B (new prerequisite)
  Check: Is B completed? No
  Action:
    - Reset A to "pending"
    - Abort iteration
    - Scheduler picks up B (higher priority)
    - B executes, completes
    - A becomes ready again
```

### 6. IterationRecord

After each iteration, a structured record is stored via `ContextProtocol.ingest()`:

```python
class IterationRecord(BaseModel):
    iteration: int
    goal_id: str
    plan_summary: str
    actions_summary: str
    reflection_assessment: str
    outcome: Literal["continue", "goal_complete", "failed"]
```

Stored with tag `"iteration_record"` and importance 0.9.

### 7. Goal Management Tools

Exposed as langchain tools for explicit agent control:
- `create_goal`: Create new goal
- `list_goals`: List goals by status
- `complete_goal`: Mark goal completed
- `fail_goal`: Mark goal failed

## Stream Events

| Type | Fields | Description |
|------|--------|-------------|
| `soothe.lifecycle.iteration.started` | `iteration`, `goal_id`, `goal_description`, `parallel_goals` | Autonomous iteration began |
| `soothe.lifecycle.iteration.completed` | `iteration`, `goal_id`, `outcome`, `duration_ms` | Iteration finished |
| `soothe.cognition.goal.created` | `goal_id`, `description`, `priority` | Goal created |
| `soothe.cognition.goal.batch_started` | `goal_ids`, `parallel_count` | Parallel batch began |
| `soothe.cognition.goal.completed` | `goal_id` | Goal completed |
| `soothe.cognition.goal.failed` | `goal_id`, `error`, `retry_count` | Goal failed |
| `soothe.cognition.goal.directives_applied` | `goal_id`, `directives_count`, `changes` | Directives mutated DAG |
| `soothe.cognition.goal.deferred` | `goal_id`, `reason`, `plan_preserved` | Goal deferred after DAG changes |
| `soothe.cognition.goal.report` | `goal_id`, `step_count`, `completed`, `failed`, `summary` | Goal report emitted |
| `mode="messages"` + `phase="autonomous_goal"` (loop-tagged AI) | AI message `content` | Final autonomous summary text (IG-317; replaces legacy `soothe.output.autonomous.*` answer payloads) |

## Configuration

```yaml
autonomous:
  enabled_by_default: false
  max_iterations: 10
  max_retries: 2
  max_total_goals: 50
  max_goal_depth: 5
  enable_dynamic_goals: true
```

## Autopilot Working Directory

### Directory Layout

Autopilot owns `SOOTHE_HOME/autopilot/` as its dedicated working directory:

```
SOOTHE_HOME/
└── autopilot/
    ├── GOAL.md              # Single goal definition (autopilot root)
    ├── GOALS.md             # Multiple goals definition (autopilot root)
    └── goals/               # Per-goal subdirectories
        ├── data-pipeline/
        │   ├── GOAL.md      # Goal definition
        │   └── *.md         # Supporting context files
        └── report-generation/
            └── GOAL.md
```

### Goal File Discovery

When autopilot starts, it scans for goals in this order:

1. **Autopilot `GOAL.md`**: Single goal definition at `autopilot/GOAL.md`
2. **Autopilot `GOALS.md`**: Multiple goals at `autopilot/GOALS.md`
3. **Subdirectory `GOAL.md`**: Each `autopilot/goals/*/GOAL.md` defines a goal

**Discovery Algorithm**:
```python
def discover_goals(autopilot_dir: Path) -> list[GoalDefinition]:
    goals = []

    # Priority 1: Autopilot GOAL.md (single goal mode)
    if (autopilot_dir / "GOAL.md").exists():
        goals.append(parse_goal_file(autopilot_dir / "GOAL.md"))
        return goals  # Single goal mode, skip other discovery

    # Priority 2: Autopilot GOALS.md (batch mode)
    if (autopilot_dir / "GOALS.md").exists():
        goals.extend(parse_goals_batch(autopilot_dir / "GOALS.md"))

    # Priority 3: goals/ subdirectory GOAL.md files
    goals_subdir = autopilot_dir / "goals"
    if goals_subdir.exists():
        for subdir in sorted(goals_subdir.iterdir()):
            if subdir.is_dir() and (subdir / "GOAL.md").exists():
                goals.append(parse_goal_file(subdir / "GOAL.md"))

    return goals
```

### Goal File Format

**`GOAL.md` format**:
```markdown
---
id: data-pipeline
priority: 80
depends_on: []
---

# Feature: Data Processing Pipeline

Implement a robust data processing pipeline with validation and error handling.

## Success Criteria
- Data is validated before processing
- Errors are properly handled and logged
- Pipeline produces correct output files
```

**`GOALS.md` format** (multiple goals):
```markdown
# Project Goals

## Goal: Data Pipeline
- id: pipeline
- priority: 90
- depends_on: []

Implement the data processing pipeline.

## Goal: Report Generation
- id: report
- priority: 70
- depends_on: [pipeline]

Build the report generation from processed data.
```

### Goal Status Tracking

Autopilot updates goal status back to the source markdown files:

**Status field in frontmatter**:
```yaml
---
id: data-pipeline
priority: 80
status: active  # pending | active | completed | failed
error: null     # Set if failed
---
```

**Progress tracking**:
```markdown
## Progress

- [x] Design pipeline architecture
- [x] Implement data validation
- [ ] Add error handling
- [ ] Write tests

Last updated: 2026-04-03T14:30:00Z
```

**Update behavior**:
1. Status changes (`pending` → `active` → `completed`/`failed`) are written to frontmatter
2. Progress section is appended/updated as sub-goals complete
3. Failed goals include error message in frontmatter
4. All updates preserve original file structure and comments

### Autopilot Initialization

```python
async def initialize_autopilot(soothe_home: Path) -> GoalEngine:
    autopilot_dir = soothe_home / "autopilot"
    goals_dir = autopilot_dir / "goals"

    # Ensure directory structure exists
    goals_dir.mkdir(parents=True, exist_ok=True)

    # Discover and load goals
    goal_definitions = discover_goals(autopilot_dir)

    # Create GoalEngine with discovered goals
    engine = GoalEngine()
    for goal_def in goal_definitions:
        engine.create_goal(
            description=goal_def.description,
            priority=goal_def.priority,
            goal_id=goal_def.id,
            depends_on=goal_def.depends_on
        )

    return engine
```

### File Watching (Optional)

For long-running autopilot sessions, optional file watching can detect external goal changes:

```python
class GoalFileWatcher:
    """Watch for changes to goal files and sync with GoalEngine."""

    async def on_goal_file_changed(self, path: Path):
        goal_def = parse_goal_file(path)
        existing = self.engine.get_goal(goal_def.id)

        if not existing:
            self.engine.create_goal(**goal_def.model_dump())
        else:
            # Update existing goal
            self.engine.update_goal(goal_def.id, **goal_def.model_dump())
```

## CLI Integration

- `soothe autopilot run <prompt>` - Start autopilot with prompt or discover from `SOOTHE_HOME/autopilot/goals/`
- `soothe autopilot run --goal-file path/to/GOAL.md` - Start with specific goal file
- `--max-iterations` on autopilot command
- `--no-watch` - Disable file watching for long-running sessions
- TUI `/autopilot` command for autonomous execution

## Constraints

- No modifications to deepagents internals or LangGraph graph
- GoalEngine is a plain class, not a protocol
- All persistence uses existing DurabilityProtocol and ContextProtocol
- Backward compatible -- `autonomous=False` preserves behavior

## Implementation Status

- ✅ GoalEngine with DAG scheduling (RFC-200)
- ✅ Dynamic goal management (merged into this RFC)
- ✅ Reflection with goal directives
- ✅ Safety mechanisms and validation
- ✅ GoalBackoffReasoner design documented (RFC-200 §2.1 - brainstorming refinement)
- ⚠️ Missing: Explicit Layer 2 delegation (PERFORM → Layer 2 loop integration)
- ⚠️ Missing: GoalBackoffReasoner implementation (code not yet implemented)

## Related Documents

- [RFC-000](./RFC-000-system-conceptual-design.md) - System Conceptual Design
- [RFC-001](./RFC-001-core-modules-architecture.md) - Core Modules Architecture
- [RFC-201](./RFC-201-agentloop-plan-execute-loop.md) - Layer 2: AgentLoop Plan-Execute Loop
- [RFC-201](./RFC-201-agentloop-plan-execute-loop.md) - Unified AgentLoop Plan-Execute Loop

## Changelog

### 2026-04-03
- Added §"Autopilot Working Directory" specification
- Defined `SOOTHE_HOME/autopilot/` as autopilot's working directory
- Added `goals/` subdirectory structure for goal file storage
- Defined goal file discovery algorithm (GOAL.md, GOALS.md, subdirectory scanning)
- Added goal file format specifications (frontmatter + markdown)
- Defined goal status tracking with file updates
- Added optional file watching for long-running sessions
- Extended CLI integration with `--goal-file` and `--no-watch` options

### 2026-03-29
- Established as Layer 3 foundation in three-layer architecture
- Merged dynamic goal management content
- Added §2 "Architecture Position" with three-layer model
- Defined PERFORM → Layer 2 delegation model (full delegation)
- Defined REFLECT integration with Layer 2 JudgeResult
- Updated title to "Layer 3: Autonomous Goal Management Loop"

### 2026-03-15
- Initial autonomous iteration loop design