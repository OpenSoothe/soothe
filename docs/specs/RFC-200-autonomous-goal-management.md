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

**PERFORM → Layer 2 (Full Delegation)**:

Layer 3's PERFORM stage invokes Layer 2's **complete Plan → Execute loop** for single-goal execution:

```python
# Layer 3 PERFORM stage
async def perform_goal(goal: Goal) -> PlanResult:
    # Delegate to Layer 2's full loop
    plan_result = await agentic_loop.astream(
        goal_description=goal.description,
        thread_id=f"{parent_tid}__goal_{goal.id}",
        max_iterations=8  # Layer 2 iteration budget
    )
    return plan_result  # Layer 2 returns final result
```

**REFLECT Stage Integration**:

Layer 3's REFLECT stage receives Layer 2's PlanResult and uses evidence_summary for goal DAG evaluation:

```python
# Layer 3 REFLECT stage
reflection = await planner.reflect(
    plan=goal_plan,
    step_results=goal_step_results,
    goal_context=goal_context,
    layer2_plan=plan_result  # Layer 2 evaluation
)
# reflection includes:
# - should_revise: whether goal plan needs revision
# - goal_directives: DAG restructuring actions
```

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
```python
class GoalEngine:
    def create_goal(description, priority, parent_id) -> Goal
    def next_goal() -> Goal | None  # Backward-compatible single-goal
    def ready_goals(limit) -> list[Goal]  # DAG-satisfied, activated
    def complete_goal(goal_id) -> None
    def fail_goal(goal_id, error, allow_retry) -> None
    def list_goals(status) -> list[Goal]
    def get_goal(goal_id) -> Goal | None
    def snapshot() -> dict  # Checkpoint persistence
    def restore_from_snapshot(snapshot) -> None
    def add_dependencies(goal_id, depends_on) -> None  # Safe with cycle check
    def validate_dependency(goal_id, depends_on) -> bool
```

**DAG Scheduling**:
- `ready_goals(limit)` returns goals whose `depends_on` are all completed
- Goals sorted by `(-priority, created_at)`
- Returned goals activated (status: "pending" → "active")
- Parallel execution when `len(ready_goals) > 1`

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

**Integration with GoalEngine**:

```python
class GoalEngine:
    def __init__(self, config: SootheConfig) -> None:
        self._goals: dict[str, Goal] = {}
        self._backoff_reasoner = GoalBackoffReasoner(config)

    async def fail_goal(
        self,
        goal_id: str,
        error: str,
        allow_retry: bool = True,
    ) -> None:
        """Mark goal failed with backoff reasoning."""
        goal = self._goals[goal_id]
        goal.status = "failed"
        goal.error = error

        if allow_retry and goal.retry_count < goal.max_retries:
            # Call backoff reasoner instead of simple retry
            goal_context = self._build_goal_context(goal_id)
            decision = await self._backoff_reasoner.reason_backoff(
                goal_id=goal_id,
                goal_context=goal_context,
                failed_evidence=error,
            )

            # Apply backoff decision
            self._apply_backoff_decision(decision)

        goal.retry_count += 1
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

### 3. Dynamic Goal Management

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

### 3.1 Experimental Adaptive Decomposition Mode

The system supports an optional experimental mode for decomposition strategy selection when problem structure is uncertain.

**Design intent**:
- Well-scoped goals: favor hierarchical DAG decomposition.
- Ill-scoped goals: allow temporary fluid decomposition before DAG stabilization.
- Mixed goals: allow staged crystallization from fluid hypotheses to explicit DAG nodes.

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
| `soothe.output.autonomous.final_report` | `goal_id`, `description`, `status`, `summary` | Final root goal report |

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
- ⚠️ Missing: Explicit Layer 2 delegation (PERFORM → Layer 2 loop integration)

## Related Documents

- [RFC-000](./RFC-000-system-conceptual-design.md) - System Conceptual Design
- [RFC-001](./RFC-001-core-modules-architecture.md) - Core Modules Architecture
- [RFC-201](./RFC-201-agentloop-plan-execute-loop.md) - Layer 2: AgentLoop Plan-Execute Loop
- [RFC-202](./RFC-202-dag-execution.md) - DAG Execution & Failure Recovery

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