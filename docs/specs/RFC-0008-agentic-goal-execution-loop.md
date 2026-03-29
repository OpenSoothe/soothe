# RFC-0008: Layer 2 - Agentic Goal Execution Loop

**RFC**: 0008
**Title**: Layer 2: Agentic Goal Execution Loop
**Status**: Revised
**Kind**: Architecture Design
**Created**: 2026-03-16
**Updated**: 2026-03-29
**Dependencies**: RFC-0001, RFC-0002, RFC-0007, RFC-0023

## Abstract

This RFC defines Layer 2 of Soothe's three-layer execution architecture: agentic goal execution for single-goal completion through iterative refinement. Layer 2 uses a PLAN → ACT → JUDGE loop where the LLM decides what steps to execute (AgentDecision), executes them via Layer 1 CoreAgent (ACT phase), and evaluates progress toward goal completion (JUDGE phase). It serves as the foundation for Layer 3's PERFORM stage and delegates execution to Layer 1.

## Architecture Position

### Three-Layer Model

```
Layer 3: Autonomous Goal Management (RFC-0007)
  └─ Delegates to Layer 2 (PERFORM stage) for single-goal execution

Layer 2: Agentic Goal Execution (this RFC)
  ├─ Scope: Single-goal execution through iterative refinement
  ├─ Loop: PLAN → ACT → JUDGE (max iterations: ~8)
  ├─ Delegates to Layer 1 (ACT phase) for step execution
  └─ Returns: JudgeResult to Layer 3

Layer 1: CoreAgent Runtime (RFC-0023)
  └─ Executes tools/subagents via LangGraph runtime
```

### Layer 2 Responsibilities

Layer 2 executes individual goals through iterative refinement:

- **Single-goal focus**: Execute one goal to completion
- **LLM-driven planning**: Decide what steps to execute (AgentDecision)
- **Evidence accumulation**: Collect step results for judgment
- **Goal-directed evaluation**: Judge progress toward goal completion
- **Adaptive execution**: Choose step granularity and execution mode
- **Strategy reuse**: Continue executing strategy until evaluation indicates revision
- **Delegation to Layer 1**: Use CoreAgent for tool/subagent execution

### Integration with Layer 3

**Layer 3 → Layer 2 (Full Delegation)**:

Layer 3's PERFORM stage invokes Layer 2's complete PLAN → ACT → JUDGE loop:

```python
# Layer 3 calls Layer 2
judge_result = await agentic_loop.astream(
    goal_description=goal.description,
    thread_id=f"{parent_tid}__goal_{goal.id}",
    max_iterations=8
)
# Layer 2 returns JudgeResult
```

**Layer 2 → Layer 3 (JudgeResult Return)**:

Layer 2 returns JudgeResult to Layer 3's REFLECT stage:

```python
class JudgeResult(BaseModel):
    status: Literal["continue", "replan", "done"]
    evidence_summary: str
    goal_progress: float  # 0.0-1.0
    confidence: float  # 0.0-1.0
    reasoning: str
```

### Integration with Layer 1

**ACT → Layer 1 (Hybrid Execution)**:

Layer 2's ACT phase invokes Layer 1 CoreAgent for step execution:

```python
# Sequential execution
result = await core_agent.astream(
    input=build_input_from_steps(steps),
    config={"thread_id": tid}
)

# Parallel execution
results = await asyncio.gather(*[
    core_agent.astream(
        input=f"Execute: {step.description}",
        config={"thread_id": f"{tid}__step_{i}"}
    )
    for i, step in enumerate(steps)
])
```

## Loop Model

### PLAN → ACT → JUDGE Loop

```text
Goal Input (from Layer 3)
    |
    v
while iteration < max_iterations:
    |
    +-- PLAN Phase:
    |      If no existing AgentDecision OR replan needed:
    |         Create AgentDecision (steps to execute)
    |      Else:
    |         Reuse existing AgentDecision
    |
    +-- ACT Phase:
    |      Execute steps via Layer 1 CoreAgent
    |      Collect evidence (step results)
    |
    +-- JUDGE Phase:
    |      Evaluate goal progress (evidence accumulation)
    |      Return JudgeResult
    |
    +-- Decision:
           ├─ "done": Goal achieved, return to Layer 3
           ├─ "replan": Create new AgentDecision, next iteration
           └─ "continue": Reuse AgentDecision, execute remaining steps
```

### Iteration Semantics

- **Max iterations**: Moderate budget (~8) for goal completion
- **Decision reuse**: Continue executing existing strategy until evaluation indicates revision
- **Goal-directed judgment**: Evaluate progress toward goal completion, not just plan execution

## Core Schemas

### AgentDecision (Hybrid Multi-Step Model)

AgentDecision specifies steps to execute, supporting both single-step and batch execution:

```python
class StepAction(BaseModel):
    """Single step in execution strategy."""

    description: str  # What this step does
    tools: list[str] | None = None  # Tools to use (optional)
    subagent: str | None = None  # Subagent to invoke (optional)
    expected_output: str  # Expected result for evidence accumulation
    dependencies: list[str] | None = None  # Step IDs this depends on

class AgentDecision(BaseModel):
    """LLM's decision on next action for goal execution."""

    type: Literal["execute_steps", "final"]
    steps: list[StepAction]  # Can be 1 step or N steps (hybrid)
    execution_mode: Literal["parallel", "sequential", "dependency"]
    reasoning: str  # Why these steps advance toward goal

    @model_validator(mode="after")
    def validate_decision(self) -> AgentDecision:
        if self.type == "execute_steps" and not self.steps:
            raise ValueError("execute_steps requires at least one step")
        return self
```

**Decision Properties**:
- **Batch execution**: LLM decides how many steps to execute per iteration (1 or N)
- **Execution mode**: Parallel (isolated threads), sequential (shared context), dependency (DAG)
- **Hybrid flexibility**: Choose single step for focused execution, batch for efficiency

### JudgeResult (Evidence Accumulation Model)

JUDGE evaluates goal progress by accumulating evidence from all executed step results:

```python
class JudgeResult(BaseModel):
    """LLM's judgment after evaluating goal progress."""

    status: Literal["continue", "replan", "done"]
    evidence_summary: str  # Accumulated from all step results
    goal_progress: float = Field(ge=0.0, le=1.0)  # Progress toward goal
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)
    reasoning: str  # Why this judgment was made

    def should_continue(self) -> bool:
        return self.status == "continue"

    def should_replan(self) -> bool:
        return self.status == "replan"

    def is_done(self) -> bool:
        return self.status == "done"
```

**Judgment Logic**:
- JUDGE looks at all step results and evaluates: "Given this evidence, how much progress toward final goal?"
- **Goal-directed evaluation**: Focus on goal completion, not plan completion
- **Evidence quality**: Strong evidence → confident judgment; weak evidence → lower confidence
- **Decision criteria**:
  - `done`: Goal achieved, sufficient evidence, no further work needed
  - `continue`: Strategy valid, remaining steps to execute, progress partial
  - `replan`: Strategy failed, evidence reveals wrong approach, need new strategy

## PLAN Phase

### Planning Decision

PLAN phase creates or reuses execution strategy:

```python
async def plan_phase(
    goal: str,
    context: PlanContext,
    previous_decision: AgentDecision | None = None,
    previous_judgment: JudgeResult | None = None
) -> AgentDecision:

    # Reuse existing decision if judgment says "continue"
    if previous_judgment and previous_judgment.should_continue():
        if previous_decision and has_remaining_steps(previous_decision):
            return previous_decision  # Reuse strategy

    # Create new decision (initial or replan)
    decision = await planner.decide_steps(
        goal=goal,
        context=context,
        previous_judgment=previous_judgment
    )

    return decision
```

### Adaptive Step Granularity

LLM decides step granularity based on goal characteristics:

- **Clear goals** with well-known procedures → **coarse steps** (semantic subtasks)
  - Example: "analyze requirements", "design solution", "implement", "verify"
  - Broader scope, fewer steps, faster iteration

- **Uncertain goals** requiring exploration → **fine steps** (atomic actions)
  - Example: "check file exists", "read config", "call API", "parse response"
  - Narrow scope, more steps, granular evidence for judgment

- **Granularity as planning decision**: Not fixed policy, but LLM-driven strategy choice

### Iteration-Scoped Planning

PLAN happens inside loop iterations, not before:

```
Iteration 1: PLAN (create initial strategy) → ACT → JUDGE
Iteration 2: [skip PLAN, reuse decision] → ACT → JUDGE ("continue")
Iteration 3: PLAN (replan) → ACT → JUDGE ("replan")
Iteration 4: [skip PLAN, reuse decision] → ACT → JUDGE ("done")
```

## ACT Phase

### Hybrid Sequential vs Parallel Execution

ACT phase chooses execution mode based on AgentDecision.execution_mode:

```python
async def act_phase(
    decision: AgentDecision,
    core_agent: CompiledStateGraph,
    thread_id: str
) -> list[StepResult]:

    if decision.execution_mode == "parallel":
        # Execute steps in parallel with isolated threads
        results = await asyncio.gather(*[
            execute_step_via_core_agent(
                core_agent=core_agent,
                step=step,
                thread_id=f"{thread_id}__step_{i}"
            )
            for i, step in enumerate(decision.steps)
        ])

    elif decision.execution_mode == "sequential":
        # Execute steps sequentially in one agent turn
        combined_input = build_sequential_input(decision.steps)
        result_stream = await core_agent.astream(
            input=combined_input,
            config={"configurable": {"thread_id": thread_id}}
        )
        results = await collect_stream_results(result_stream)

    elif decision.execution_mode == "dependency":
        # Use StepScheduler for DAG-based execution (RFC-0009)
        scheduler = StepScheduler(decision.steps)
        results = await execute_dag_steps(scheduler, core_agent, thread_id)

    return results  # Evidence for JUDGE phase
```

### Layer 1 CoreAgent Integration

Each step (or combined input) calls `core_agent.astream(input, thread_config)`:

```python
async def execute_step_via_core_agent(
    agent: CompiledStateGraph,
    step: StepAction,
    thread_id: str
) -> StepResult:
    """Execute single step through Layer 1 CoreAgent with hints."""

    # Build config with Layer 2 → Layer 1 hints (advisory)
    config = {
        "configurable": {
            "thread_id": thread_id,
            "soothe_step_tools": step.tools,           # Suggested tools
            "soothe_step_subagent": step.subagent,     # Suggested subagent
            "soothe_step_expected_output": step.expected_output,  # Expected result
        }
    }

    stream = await agent.astream(
        input=f"Execute: {step.description}",
        config=config  # Hints passed via config
    )
    # Collect evidence from stream
    result = await collect_stream_evidence(stream)
    return result
```

**Hint Integration**: Layer 1's `ExecutionHintsMiddleware` injects hints into system prompt, allowing LLM to consider Layer 2's planning suggestions during execution. See RFC-0023 for integration contract details.

**CoreAgent Responsibilities** (Layer 1):
- Execute tools/subagents as requested by input context
- Consider execution hints from Layer 2 (advisory suggestions)
- Apply middlewares (context injection, policy checking, memory recall/persist, hints)
- Manage thread state and LangGraph turn loop
- Return streaming results for evidence collection

**Layer 2 Controls**:
- What to execute (step content)
- What to suggest (tool/subagent hints, optional)
- When to execute (iteration timing)
- How to sequence (parallel vs sequential vs dependency)
- Thread isolation strategy

## JUDGE Phase

### Evidence Accumulation Evaluation

JUDGE evaluates goal progress by accumulating evidence from all step results:

```python
async def judge_phase(
    goal: str,
    step_results: list[StepResult],
    agent_decision: AgentDecision
) -> JudgeResult:
    """Evaluate progress toward goal completion."""

    # Accumulate evidence
    evidence = accumulate_evidence(step_results)

    # LLM evaluation
    judgment = await llm_evaluate_goal_progress(
        goal=goal,
        evidence=evidence,
        steps_executed=agent_decision.steps,
        prompt=f"""
        Goal: {goal}

        Evidence from execution:
        {evidence.summary}

        Evaluate:
        1. Progress toward goal (0.0-1.0)
        2. Is goal achieved? (done)
        3. Is current strategy still valid? (continue vs replan)
        4. Confidence in your evaluation

        Return JudgeResult with status, reasoning, and confidence.
        """
    )

    return judgment
```

### Goal-Directed Judgment

JUDGE focuses on goal completion, not plan completion:

```python
# Example judgments:

# Done: Goal achieved
JudgeResult(
    status="done",
    evidence_summary="File read ✓, Parsed ✓, Validated ✓, Result correct ✓",
    goal_progress=1.0,
    confidence=0.95,
    reasoning="All requirements met, goal achieved"
)

# Continue: Strategy valid, partial progress
JudgeResult(
    status="continue",
    evidence_summary="Step 1/3 complete, remaining steps needed",
    goal_progress=0.33,
    confidence=0.85,
    reasoning="Strategy valid, continue with remaining steps"
)

# Replan: Strategy failed
JudgeResult(
    status="replan",
    evidence_summary="Steps 2-3 failed, approach incorrect",
    goal_progress=0.25,
    confidence=0.75,
    reasoning="API endpoint changed, need different approach"
)
```

## Iteration Flow

### Decision Reuse Model

Layer 2 reuses AgentDecision until JUDGE indicates strategy needs revision:

```
Iteration 1:
  PLAN: Create AgentDecision (4 steps)
  ACT: Execute steps 1-2 (partial execution)
  JUDGE: "continue" (strategy valid, 2 more steps needed)

Iteration 2:
  [Skip PLAN, reuse previous AgentDecision]
  ACT: Execute steps 3-4 (remaining steps)
  JUDGE: "replan" (steps 3-4 failed, need different approach)

Iteration 3:
  PLAN: Create new AgentDecision (3 new steps)
  ACT: Execute new steps
  JUDGE: "done" (goal achieved)

Return JudgeResult to Layer 3
```

### Iteration Decision Logic

```python
while iteration < max_iterations:
    # PLAN phase (create or reuse)
    if iteration == 0 or last_judgment.should_replan():
        decision = await plan_phase(goal, context, previous_judgment)
    else:
        decision = previous_decision  # Reuse

    # ACT phase (execute via Layer 1)
    step_results = await act_phase(decision, core_agent, thread_id)

    # JUDGE phase (evaluate goal progress)
    judgment = await judge_phase(goal, step_results, decision)

    # Decision
    if judgment.is_done():
        return judgment  # Goal achieved
    elif judgment.should_replan():
        previous_judgment = judgment
        iteration += 1
        continue  # Replan next iteration
    else:  # should_continue()
        previous_decision = decision
        previous_judgment = judgment
        iteration += 1
        continue  # Execute remaining steps

# Max iterations reached, return current judgment
return judgment
```

## Components

### 1. Agentic Loop Runner (`core/runner/_runner_agentic.py`)

**Interface**:
```python
async def astream(
    goal_description: str,
    thread_id: str | None = None,
    max_iterations: int = 8,
    return_judge_result: bool = False
) -> AsyncGenerator[StreamChunk, None] | JudgeResult:
    """
    Execute single goal through PLAN → ACT → JUDGE loop.

    Args:
        goal_description: Goal to execute
        thread_id: Thread context
        max_iterations: Maximum loop iterations
        return_judge_result: If True, return JudgeResult instead of streaming

    Yields:
        StreamChunk events during execution

    Returns:
        JudgeResult if return_judge_result=True
    """
```

### 2. Planner Integration

`PlannerProtocol` extended for Layer 2:

```python
class PlannerProtocol(Protocol):
    async def create_plan(self, goal: str, context: PlanContext) -> Plan: ...

    async def decide_steps(
        self,
        goal: str,
        context: PlanContext,
        previous_judgment: JudgeResult | None = None
    ) -> AgentDecision:
        """Decide what steps to execute for goal progress."""
        ...

    async def revise_plan(self, plan: Plan, reflection: str) -> Plan: ...

    async def reflect(
        self,
        plan: Plan,
        step_results: list[StepResult],
        goal_context: GoalContext | None = None,
        layer2_judgment: JudgeResult | None = None
    ) -> Reflection: ...
```

### 3. Judge Engine

LLM-based evaluation for goal progress:

```python
class JudgeEngine:
    """Evaluate goal progress using LLM."""

    def __init__(self, model: BaseChatModel):
        self.model = model

    async def judge(
        self,
        goal: str,
        evidence: Evidence,
        steps: list[StepAction]
    ) -> JudgeResult:
        """Evaluate progress toward goal completion."""
        ...
```

## Stream Events

| Type | Fields | Description |
|------|--------|-------------|
| `soothe.agentic.loop.started` | `thread_id`, `goal_description`, `max_iterations` | Loop began |
| `soothe.agentic.iteration.started` | `iteration`, `decision_summary` | Iteration began |
| `soothe.agentic.plan.decision` | `steps_count`, `execution_mode`, `reasoning` | AgentDecision created |
| `soothe.agentic.act.started` | `steps`, `execution_mode` | ACT phase began |
| `soothe.agentic.act.step_completed` | `step_id`, `result_preview` | Step completed |
| `soothe.agentic.judge.completed` | `status`, `goal_progress`, `confidence` | JUDGE phase completed |
| `soothe.agentic.loop.completed` | `final_status`, `total_iterations` | Loop completed |

## Configuration

```yaml
agentic:
  enabled: true
  max_iterations: 8
  planning:
    adaptive_granularity: true  # LLM decides step size
  judgment:
    evidence_threshold: 0.7  # Minimum confidence for "done"
```

## Implementation Status

- ❌ Current implementation: observe → act → verify (not PLAN → ACT → JUDGE)
- ❌ AgentDecision: Single tool model (not hybrid multi-step)
- ❌ Planning: Happens before loop (not iteration-scoped)
- ❌ Judgment: Heuristic-based (not structured goal-directed evaluation)
- ❌ Iteration flow: No decision reuse model
- ❌ ACT phase: No explicit Layer 1 CoreAgent integration
- **Action**: Complete redesign and implementation required

## Related Documents

- [RFC-0001](./RFC-0001-system-conceptual-design.md) - System Conceptual Design
- [RFC-0002](./RFC-0002-core-modules-architecture.md) - Core Modules Architecture
- [RFC-0007](./RFC-0007-autonomous-goal-management-loop.md) - Layer 3: Autonomous Goal Management
- [RFC-0009](./RFC-0009-dag-based-execution.md) - DAG-Based Execution
- [RFC-00XX](./RFC-00XX-coreagent-runtime.md) - Layer 1: CoreAgent Runtime

## Changelog

### 2026-03-29
- Established as Layer 2 foundation in three-layer architecture
- Fundamental redesign with PLAN → ACT → JUDGE loop
- Introduced AgentDecision (hybrid multi-step model)
- Introduced JudgeResult (evidence accumulation model)
- Defined iteration-scoped planning (inside loop)
- Defined goal-directed judgment (evaluate progress toward goal)
- Defined decision reuse iteration flow
- Defined ACT → Layer 1 integration (hybrid execution)
- Updated title to "Layer 2: Agentic Goal Execution Loop"

### 2026-03-16
- Initial agentic loop design