# RFC-0008: Layer 2 - Agentic Goal Execution Loop

**RFC**: 0008
**Title**: Layer 2: Agentic Goal Execution Loop
**Status**: Revised
**Kind**: Architecture Design
**Created**: 2026-03-16
**Updated**: 2026-03-29
**Dependencies**: RFC-0001, RFC-0002, RFC-0007, RFC-0023

## Abstract

This RFC defines Layer 2 of Soothe's three-layer execution architecture: agentic goal execution for single-goal completion through iterative refinement. Layer 2 uses a PLAN → ACT → JUDGE loop where the LLM decides what steps to execute (AgentDecision), executes them via Layer 1 CoreAgent (ACT phase), and evaluates progress toward goal completion (JUDGE phase). It serves as foundation for Layer 3's PERFORM stage and delegates execution to Layer 1.

## Architecture Position

### Three-Layer Model

```
Layer 3: Autonomous Goal Management (RFC-0007) → Layer 2 (PERFORM stage)
Layer 2: Agentic Goal Execution (this RFC) → Layer 1 (ACT phase)
Layer 1: CoreAgent Runtime (RFC-0023) → Tools/Subagents
```

**Layer 2 Responsibilities**: Single-goal focus, LLM-driven planning (AgentDecision), evidence accumulation, goal-directed evaluation, adaptive execution, strategy reuse, Layer 1 delegation.

### Layer Integration

**Layer 3 → Layer 2**: `judge_result = await agentic_loop.astream(goal_description, thread_id, max_iterations=8)`

**Layer 2 → Layer 3**: Return JudgeResult with status, evidence_summary, goal_progress, confidence, reasoning.

**Layer 2 → Layer 1**: `result = await core_agent.astream(input, config)` for step execution.

## Loop Model

### PLAN → ACT → JUDGE Loop

```
Goal → while iteration < max_iterations:
  PLAN: Create/reuse AgentDecision (steps to execute)
  ACT: Execute steps via Layer 1 CoreAgent, collect evidence
  JUDGE: Evaluate goal progress, return JudgeResult
  Decision: "done" (return), "replan" (new decision), "continue" (reuse decision)
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

### JudgeResult

```python
class JudgeResult(BaseModel):
    status: Literal["continue", "replan", "done"]
    evidence_summary: str  # Accumulated from step results
    goal_progress: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)
    reasoning: str
```

**Judgment Logic**: Goal-directed evaluation (goal completion, not plan completion), evidence quality → confidence, decision criteria: done (goal achieved), continue (strategy valid, partial progress), replan (strategy failed).

## PLAN Phase

### Planning Decision

```python
# Reuse if judgment says "continue" and has remaining steps
if previous_judgment.should_continue() and has_remaining_steps(previous_decision):
    return previous_decision
# Create new decision (initial or replan)
decision = await planner.decide_steps(goal, context, previous_judgment)
```

**Adaptive Step Granularity**: LLM decides coarse steps (clear goals, semantic subtasks) vs fine steps (uncertain goals, atomic actions).

**Iteration-Scoped Planning**: PLAN inside loop (not before). Reuse decision on "continue", replan on "replan".

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

**Layer 1 Integration**: `config = {"thread_id": tid, "soothe_step_tools": step.tools, "soothe_step_subagent": step.subagent, "soothe_step_expected_output": step.expected_output}`. Layer 1's `ExecutionHintsMiddleware` injects hints into system prompt (RFC-0023).

**CoreAgent Responsibilities**: Execute tools/subagents, consider hints, apply middlewares, manage thread state, return streaming results.

**Layer 2 Controls**: What to execute, suggestions, timing, sequencing, thread isolation.

## JUDGE Phase

### Evidence Accumulation

```python
evidence = accumulate_evidence(step_results)
judgment = await llm_evaluate_goal_progress(goal, evidence, steps_executed)
```

**Goal-Directed Judgment**: Focus on goal completion, not plan completion. Evaluate progress (0.0-1.0), goal achieved (done), strategy valid (continue vs replan), confidence.

**Examples**: done (goal_progress=1.0), continue (partial progress, strategy valid), replan (steps failed, approach incorrect).

## Iteration Flow

### Decision Reuse

```
Iteration 1: PLAN (create 4 steps) → ACT (execute 1-2) → JUDGE: "continue"
Iteration 2: [Skip PLAN] → ACT (execute 3-4) → JUDGE: "replan"
Iteration 3: PLAN (create 3 new steps) → ACT → JUDGE: "done"
Return JudgeResult
```

**Logic**: PLAN if iteration==0 or replan, else reuse. ACT, JUDGE. Return if done, increment if replan/continue.

## Components

### Agentic Loop Runner (`core/runner/_runner_agentic.py`)

```python
async def astream(goal_description, thread_id, max_iterations=8, return_judge_result=False):
    """Execute single goal through PLAN → ACT → JUDGE loop."""
```

### Planner Integration

```python
class PlannerProtocol:
    async def decide_steps(goal, context, previous_judgment=None) -> AgentDecision
    async def create_plan(goal, context) -> Plan
    async def revise_plan(plan, reflection) -> Plan
    async def reflect(plan, step_results, goal_context=None, layer2_judgment=None) -> Reflection
```

### Judge Engine

```python
class JudgeEngine:
    async def judge(goal, evidence, steps) -> JudgeResult
```

## Stream Events

| Event | Description |
|-------|-------------|
| `soothe.agentic.loop.started` | Loop began |
| `soothe.agentic.iteration.started` | Iteration began |
| `soothe.agentic.plan.decision` | AgentDecision created |
| `soothe.agentic.act.started` | ACT phase began |
| `soothe.agentic.act.step_completed` | Step completed |
| `soothe.agentic.judge.completed` | JUDGE phase completed |
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

- ❌ Current: observe → act → verify (not PLAN → ACT → JUDGE)
- ❌ AgentDecision: Single tool (not hybrid multi-step)
- ❌ Planning: Before loop (not iteration-scoped)
- ❌ Judgment: Heuristic (not structured goal-directed)
- ❌ Iteration flow: No decision reuse
- ❌ ACT phase: No Layer 1 integration
- **Action**: Complete redesign required

## Changelog

### 2026-03-29
- Layer 2 foundation, PLAN → ACT → JUDGE loop
- AgentDecision (hybrid multi-step), JudgeResult (evidence accumulation)
- Iteration-scoped planning, goal-directed judgment, decision reuse
- ACT → Layer 1 integration, updated title

### 2026-03-16
- Initial design

## References

- RFC-0001: System conceptual design
- RFC-0002: Core modules architecture
- RFC-0007: Layer 3 autonomous goal management
- RFC-0023: Layer 1 CoreAgent runtime

---

*Layer 2 agentic execution through PLAN → ACT → JUDGE loop with decision reuse and goal-directed evaluation.*