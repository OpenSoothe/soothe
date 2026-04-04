# RFC-201: Layer 2 - Agentic Goal Execution Loop

**RFC**: 0008
**Title**: Layer 2: Agentic Goal Execution Loop
**Status**: Revised
**Kind**: Architecture Design
**Created**: 2026-03-16
**Updated**: 2026-04-05
**Dependencies**: RFC-000, RFC-001, RFC-200, RFC-100

## Abstract

This RFC defines Layer 2 of Soothe's three-layer execution architecture: agentic goal execution for single-goal completion through iterative refinement. Layer 2 uses a **Reason → Act** loop where the LLM reasons about planning, progress assessment, and goal-distance estimation in a single structured response (ReasonResult), then executes steps via Layer 1 CoreAgent (Act phase). It serves as foundation for Layer 3's PERFORM stage and delegates execution to Layer 1.

## Architecture Position

### Three-Layer Model

```
Layer 3: Autonomous Goal Management (RFC-200) → Layer 2 (PERFORM stage)
Layer 2: Agentic Goal Execution (this RFC) → Layer 1 (Act phase)
Layer 1: CoreAgent Runtime (RFC-100) → Tools/Subagents
```

**Layer 2 Responsibilities**: Single-goal focus, LLM-driven reasoning (ReasonResult), evidence accumulation, goal-directed evaluation, adaptive execution, strategy reuse, Layer 1 delegation.

### Layer Integration

**Layer 3 → Layer 2**: `judge_result = await agentic_loop.astream(goal_description, thread_id, max_iterations=8)`

**Layer 2 → Layer 3**: Return `JudgeResult`/`ReasonResult` with status, evidence_summary, goal_progress, confidence, reasoning.

**Layer 2 → Layer 1**: `result = await core_agent.astream(input, config)` for step execution.

## Loop Model

### Reason → Act Loop

```
Goal → while iteration < max_iterations:
  REASON: Produce ReasonResult (plan assessment + progress judgment + next steps)
  ACT: Execute steps via Layer 1 CoreAgent, collect evidence
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

### ReasonResult

```python
class ReasonResult(BaseModel):
    status: Literal["continue", "replan", "done"]
    goal_progress: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)
    reasoning: str
    evidence_summary: str  # Accumulated from step results
    user_summary: str      # Human-readable progress summary
    plan_action: Literal["keep", "new"]  # Reuse or replace plan
    decision: AgentDecision | None       # New plan when plan_action=="new"
    next_steps_hint: str   # Guidance for next Act phase
```

**Reasoning Logic**: Combines planning, progress assessment, and goal-distance estimation in one LLM call. Decision criteria: done (goal achieved), continue (strategy valid, partial progress), replan (strategy failed).

## REASON Phase

### Reasoning Decision

```python
# Reuse plan if reason says "continue" and has remaining steps
if previous_reason.status == "continue" and has_remaining_steps(previous_decision):
    return previous_decision
# Create new plan (initial or replan)
result = await reasoner.reason(goal, state, context, previous_reason)
```

**Adaptive Step Granularity**: LLM decides coarse steps (clear goals, semantic subtasks) vs fine steps (uncertain goals, atomic actions).

**Iteration-Scoped Reasoning**: REASON inside loop (not before). Reuse plan on "continue", replan on "replan".

## ACT Phase

### Hybrid Execution

```python
if execution_mode == "parallel":
    results = await asyncio.gather([execute_step(step, thread_id=f"{tid}__step_{i}")])
elif execution_mode == "sequential":
    combined_input = build_sequential_input(steps)
    results = await core_agent.astream(combined_input, thread_id)
elif execution_mode == "dependency":
    results = await execute_dag_steps(scheduler, core_agent, thread_id)
```

**Layer 1 Integration**: `config = {"thread_id": tid, "soothe_step_tools": step.tools, "soothe_step_subagent": step.subagent, "soothe_step_expected_output": step.expected_output}`. Layer 1's `ExecutionHintsMiddleware` injects hints into system prompt (RFC-100).

**CoreAgent Responsibilities**: Execute tools/subagents, consider hints, apply middlewares, manage thread state, return streaming results.

**Layer 2 Controls**: What to execute, suggestions, timing, sequencing, thread isolation.

## Iteration Flow

### Decision Reuse

```
Iteration 1: REASON (create 4 steps) → ACT (execute 1-2) → "continue"
Iteration 2: [Skip REASON plan] → ACT (execute 3-4) → "replan"
Iteration 3: REASON (create 3 new steps) → ACT → "done"
Return ReasonResult
```

**Logic**: REASON if iteration==0 or replan, else reuse. ACT. Return if done, increment if replan/continue.

## Components

### Agentic Loop Runner (`core/runner/_runner_agentic.py`)

```python
async def astream(goal_description, thread_id, max_iterations=8):
    """Execute single goal through Reason → Act loop."""
```

### Reasoner Integration

```python
class LoopReasonerProtocol:
    async def reason(goal, state, context, previous_reason=None) -> ReasonResult
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
| `soothe.cognition.loop_agent.reason` | Reason phase completed (ReasonResult) |
| `soothe.agentic.act.started` | ACT phase began |
| `soothe.agentic.act.step_completed` | Step completed |
| `soothe.agentic.loop.completed` | Loop completed |

## Configuration

```yaml
agentic:
  enabled: true
  max_iterations: 8
  planning:
    adaptive_granularity: true
  judgment:
    evidence_threshold: 0.7
```

## Implementation Status

- ✅ Reason → Act loop implemented (IG-115)
- ✅ ReasonResult schema (combines planning + judgment)
- ✅ LoopReasonerProtocol for reasoning
- ✅ Iteration-scoped reasoning, goal-directed evaluation
- ✅ ACT → Layer 1 integration

## Changelog

### 2026-04-05
- Migrated from PLAN → ACT → JUDGE to Reason → Act (IG-115)
- JudgeResult replaced by ReasonResult (single LLM call per iteration)
- LoopState.previous_reason replaces previous_judgment
- JudgeEngine removed, replaced by LoopReasonerProtocol

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
- IG-115: LoopAgent ReAct (Reason + Act) migration

---

*Layer 2 agentic execution through Reason → Act loop with decision reuse and goal-directed evaluation.*
