# RFC-201: Layer 2 - Agentic Goal Execution Loop

**RFC**: 0008
**Title**: Layer 2: Agentic Goal Execution Loop
**Status**: Implemented
**Kind**: Architecture Design
**Created**: 2026-03-16
**Updated**: 2026-04-12
**Dependencies**: RFC-000, RFC-001, RFC-200, RFC-100

## Abstract

This RFC defines Layer 2 of Soothe's three-layer execution architecture: agentic goal execution for single-goal completion through iterative refinement. Layer 2 uses a **Plan → Execute** loop (Plan-and-Execute design pattern) where the LLM performs planning, progress assessment, and goal-distance estimation in a single structured response (PlanResult), then executes steps via Layer 1 CoreAgent (Execute phase). It serves as foundation for Layer 3's PERFORM stage and delegates execution to Layer 1.

## Architecture Position

### Three-Layer Model

```
Layer 3: Autonomous Goal Management (RFC-200) → Layer 2 (PERFORM stage)
Layer 2: Agentic Goal Execution (this RFC) → Layer 1 (Execute phase)
Layer 1: CoreAgent Runtime (RFC-100) → Tools/Subagents
```

**Layer 2 Responsibilities**: Single-goal focus, LLM-driven reasoning (PlanResult), evidence accumulation, goal-directed evaluation, adaptive execution, strategy reuse, context isolation, execution bounds, Layer 1 delegation.

### Layer Integration

**Layer 3 → Layer 2**: `judge_result = await agentic_loop.astream(goal_description, thread_id, max_iterations=8)`

**Layer 2 → Layer 3**: Return `JudgeResult`/`PlanResult` with status, evidence_summary, goal_progress, confidence, reasoning.

**Layer 2 → Layer 1**: `result = await core_agent.astream(input, config)` for step execution.

## Loop Model

### Plan → Execute Loop

```
Goal → while iteration < max_iterations:
  PLAN: Produce PlanResult (plan assessment + progress judgment + next steps)
  EXECUTE: Execute steps via Layer 1 CoreAgent, collect evidence
  Decision: "done" (return), "replan" (new plan), "continue" (reuse plan)
```

**Iteration Semantics**: Max ~8 iterations, decision reuse, goal-directed judgment (evaluate progress toward goal, not plan completion).

## Core Schemas

### AgentDecision

```python
class StepAction(BaseModel):
    description: str
    tools: list[str] | None = None
    subagent: str | None = None
    expected_output: str
    dependencies: list[str] | None = None

class AgentDecision(BaseModel):
    type: Literal["execute_steps", "final"]
    steps: list[StepAction]  # 1 or N steps (hybrid)
    execution_mode: Literal["parallel", "sequential", "dependency"]
    reasoning: str
```

**Properties**: Batch execution (LLM decides 1 or N steps), execution mode (parallel/sequential/dependency), hybrid flexibility.

### PlanResult

```python
class PlanResult(BaseModel):
    status: Literal["continue", "replan", "done"]
    goal_progress: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)
    reasoning: str
    evidence_summary: str  # Accumulated from step results
    user_summary: str      # Human-readable progress summary
    plan_action: Literal["keep", "new"]  # Reuse or replace plan
    decision: AgentDecision | None       # New plan when plan_action=="new"
    next_steps_hint: str   # Guidance for next Execute phase
```

**Planning Logic**: Combines planning, progress assessment, and goal-distance estimation in one LLM call. Decision criteria: done (goal achieved), continue (strategy valid, partial progress), replan (strategy failed).

## PLAN Phase

### Planning Decision

```python
# Reuse plan if plan phase says "continue" and has remaining steps
if previous_plan.status == "continue" and has_remaining_steps(previous_decision):
    return previous_decision
# Create new plan (initial or replan)
result = await planner.plan(goal, state, context, previous_plan)
```

**Adaptive Step Granularity**: LLM decides coarse steps (clear goals, semantic subtasks) vs fine steps (uncertain goals, atomic actions).

**Iteration-Scoped Planning**: PLAN inside loop (not before). Reuse plan on "continue", replan on "replan".

**Plan Metrics Enhancement**: Structured wave metrics inform Plan decisions (tool_call_count, subagent_task_count, cap_hit, output_length, error_count, context_window). Metrics-driven approach prevents premature `continue` after satisfactory output.

## EXECUTE Phase

### Hybrid Execution

```python
if execution_mode == "parallel":
    # RFC-209: All steps use parent thread_id (langgraph handles concurrency)
    results = await asyncio.gather([execute_step(step, thread_id=tid) for step in steps])
elif execution_mode == "sequential":
    combined_input = build_sequential_input(steps)
    results = await core_agent.astream(combined_input, thread_id)
elif execution_mode == "dependency":
    results = await execute_dag_steps(scheduler, core_agent, thread_id)
```

**Context Isolation** (simplified by RFC-209):
- **Subagent steps**: task tool creates isolated thread branches automatically (`{thread_id}__task_{uuid}` internally)
- **Tool-only steps**: Use parent thread context (langgraph handles concurrent execution safely)
- **No manual thread ID generation**: executor passes parent thread_id to CoreAgent for all executions
- **Thread safety**: langgraph's atomic state updates and message queue prevent conflicts

**Note**: RFC-209 simplifies thread isolation by removing manual thread ID generation and leveraging langgraph's built-in concurrency handling and task tool automatic isolation. This reduces implementation complexity while maintaining thread safety guarantees.

**Execution Bounds**: Two-layer constraint prevents runaway subagent loops. Soft constraint: schema/prompt defines "one delegation = one call; retry = explicit second step". Hard constraint: `max_subagent_tasks_per_wave` cap (default 2) stops stream early. Cap hit signals metrics to Reason for replan/continue decision.

**Layer 1 Integration**: `config = {"thread_id": tid, "soothe_step_tools": step.tools, "soothe_step_subagent": step.subagent, "soothe_step_expected_output": step.expected_output}`. Layer 1's `ExecutionHintsMiddleware` injects hints into system prompt (RFC-100).

**CoreAgent Responsibilities**: Execute tools/subagents, consider hints, apply middlewares, manage thread state, return streaming results.

**Layer 2 Controls**: What to execute, suggestions, timing, sequencing, thread isolation (automatic), execution bounds (soft + hard cap), metrics aggregation.

## Iteration Flow

### Decision Reuse

```
Iteration 1: REASON (create 4 steps) → ACT (execute 1-2) → "continue"
Iteration 2: [Skip REASON plan] → ACT (execute 3-4) → "replan"
Iteration 3: REASON (create 3 new steps) → ACT → "done"
Return PlanResult
```

**Logic**: REASON if iteration==0 or replan, else reuse. ACT. Return if done, increment if replan/continue.

## Components

### Agentic Loop Runner (`core/runner/_runner_agentic.py`)

```python
async def astream(goal_description, thread_id, max_iterations=8):
    """Execute single goal through Plan → Execute loop."""
```

### Planner Integration

```python
class LoopPlannerProtocol:
    async def plan(goal, state, context, previous_plan=None) -> PlanResult
```

### Planner Integration

```python
class PlannerProtocol:
    async def create_plan(goal, context) -> Plan
    async def revise_plan(plan, reflection) -> Plan
    async def reflect(plan, step_results, goal_context=None, layer2_reason=None) -> Reflection
```

## Stream Events

| Event | Description |
|-------|-------------|
| `soothe.agentic.loop.started` | Loop began |
| `soothe.agentic.iteration.started` | Iteration began |
| `soothe.cognition.agent_loop.plan` | Plan phase completed (PlanResult) |
| `soothe.agentic.execute.started` | EXECUTE phase began |
| `soothe.agentic.execute.step_completed` | Step completed |
| `soothe.agentic.loop.completed` | Loop completed |

## LoopState Metrics

### Wave Execution Metrics

```python
class LoopState(BaseModel):
    # Wave execution metrics (IG-130, this RFC)
    last_wave_tool_call_count: int = 0
    last_wave_subagent_task_count: int = 0
    last_wave_hit_subagent_cap: bool = False
    last_wave_output_length: int = 0
    last_wave_error_count: int = 0

    # Context window metrics
    total_tokens_used: int = 0
    context_percentage_consumed: float = 0.0
```

**Purpose**: Inform Plan decisions with structured evidence beyond truncated summary. Metrics aggregation occurs after each Execute wave, before Plan phase.

**Decision Impact**: Translation (8000 char output + 1 subagent call → `done`), Research (cap hit + partial output → `replan`), Multi-phase (2000 char output + cap not hit → `continue`).

## Configuration

```yaml
agentic:
  enabled: true
  max_iterations: 8

  # Thread isolation for sequential Act
  sequential_act_isolated_thread: true
  sequential_act_isolate_when_step_subagent_hint: true

  # Execution bounds
  max_subagent_tasks_per_wave: 2  # safety cap

  # Output contract
  layer2_output_contract_enabled: true

  planning:
    adaptive_granularity: true
  judgment:
    evidence_threshold: 0.7
```

## Contamination Prevention

### Cross-Wave Isolation

**Problem**: Wave 1 output contaminates Wave 2 delegation (e.g., research output causes translation language detection failure).

**Solution**: Thread isolation for delegation steps. Subagent sees only explicit task input, no prior wave outputs or conversation history.

**Mechanism** (simplified by RFC-209): task tool automatically creates isolated thread branch (`{thread_id}__task_{uuid}` internally) for subagent delegations. Tool executions use parent thread_id with langgraph's concurrent safety.

### Output Duplication Prevention

**Problem**: Subagent output streamed to TUI, then main model repeats it verbatim.

**Solution**: Output contract suffix (anti-repetition instructions) + metrics-driven Reason prevents premature `continue`.

**Mechanism**: Layer 2 contract suffix in executor. Better Plan decisions (metrics-aware) reduce post-delegation summary tendency.

### Premature Continue Detection

**Problem**: Plan decides `continue` after satisfactory Execute output, triggering unnecessary iteration.

**Solution**: Structured metrics inform Plan of wave completion status. Output length, subagent count, cap hit signal done vs continue criteria.

**Mechanism**: `<SOOTHE_WAVE_METRICS>` section in Plan prompt. Model judges based on metrics pattern + goal text.

## Implementation Status

- ✅ Plan → Execute loop implemented (IG-115, renamed in IG-153)
- ✅ PlanResult schema (combines planning + judgment)
- ✅ LoopPlannerProtocol for planning
- ✅ Iteration-scoped planning, goal-directed evaluation
- ✅ EXECUTE → CoreAgent integration
- ✅ Thread isolation pattern (IG-131)
- ✅ Subagent task cap tracking (IG-130)
- ✅ Output contract suffix (IG-119)
- ✅ Prior conversation for Plan (IG-128)
- ✅ Metrics aggregation in executor (IG-130, IG-151)
- ✅ LoopState wave metrics schema (IG-130)
- ✅ Metrics-driven Plan prompts (IG-130)
- ✅ Token tracking with tiktoken fallback (IG-151)
- ✅ Evidence-driven Plan messages (IG-148)
- ⚠️ Automatic isolation trigger logic (deferred - manual control sufficient)

**Verification**: See `src/soothe/cognition/agent_loop/executor.py:_aggregate_wave_metrics()` and `schemas.py:LoopState` for metrics implementation.

## Changelog

### 2026-04-12
- Terminology refactoring: Renamed "ReAct" pattern to "Plan-and-Execute" (IG-153)
- Renamed "Reason → Act" loop to "Plan → Execute" loop
- Renamed "Reason phase" to "Plan phase", "Execute phase" to "Execute phase"
- Renamed `PlanResult` to `PlanResult`, `LoopPlannerProtocol` to `LoopPlannerProtocol`
- Updated all descriptive text, event names, and implementation status
- Added backward compatibility aliases for deprecated names

### 2026-04-07
- Added Context Isolation section (thread isolation for delegation steps)
- Added Execution Bounds section (soft + hard cap mechanism)
- Added LoopState Metrics section (wave execution and context window metrics)
- Added Contamination Prevention section (cross-wave, output duplication, premature continue)
- Updated Layer 2 Responsibilities to include context isolation and execution bounds
- Updated implementation status with IG-130, IG-131, IG-128, IG-119
- Configuration extended with isolation and cap settings

### 2026-04-05
- Migrated from PLAN → ACT → JUDGE to Reason → Act (IG-115)
- JudgeResult replaced by PlanResult (single LLM call per iteration)
- LoopState.previous_reason replaces previous_judgment
- JudgeEngine removed, replaced by LoopPlannerProtocol

### 2026-03-29
- Layer 2 foundation, PLAN → ACT → JUDGE loop
- AgentDecision (hybrid multi-step), JudgeResult (evidence accumulation)
- Iteration-scoped planning, goal-directed judgment, decision reuse
- ACT → Layer 1 integration, updated title

### 2026-03-16
- Initial design

## References

- RFC-000: System conceptual design
- RFC-001: Core modules architecture
- RFC-200: Layer 3 autonomous goal management
- RFC-100: Layer 1 CoreAgent runtime
- RFC-209: Executor thread isolation simplification (upcoming refactoring)
- RFC-203: Loop working memory
- IG-115: AgentLoop Plan-and-Execute migration (originally "ReAct", renamed in IG-153)
- IG-130: Subagent task cap tracking
- IG-131: Sequential Execute isolated thread
- IG-128: Prior conversation for Plan
- IG-119: Output contract and duplicate stdout
- IG-153: Terminology refactoring (ReAct → Plan-and-Execute)
- Design draft: `docs/drafts/2026-04-07-layer2-context-isolation-design.md`

---

*Layer 2 agentic execution through Plan → Execute loop with context isolation, execution bounds, metrics-driven planning, and goal-directed evaluation.*
