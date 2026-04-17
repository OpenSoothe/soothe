# RFC-201: AgentLoop Plan-Execute Loop Architecture

**RFC**: 201
**Title**: AgentLoop Plan-Execute Loop Architecture (Consolidated Layer 2)
**Status**: Implemented
**Kind**: Architecture Design
**Created**: 2026-04-17
**Dependencies**: RFC-000, RFC-001, RFC-100
**Related**: RFC-203 (State), RFC-207 (Thread), RFC-213 (Reasoning)

---

## Abstract

This RFC defines Layer 2 of Soothe's three-layer execution architecture: agentic goal execution for single-goal completion through iterative refinement. Layer 2 uses a **Plan → Execute** loop where the LLM performs planning, progress assessment, and goal-distance estimation in a single structured response (PlanResult), then executes steps via Layer 1 CoreAgent. This RFC consolidates the core loop architecture including Plan-Execute loop structure, AgentDecision batch execution model, and PlanResult goal-directed evaluation model.

---

## Architecture Position

### Three-Layer Model

```
Layer 3: Autonomous Goal Management (RFC-200) → Layer 2 (PERFORM stage)
Layer 2: Agentic Goal Execution (this RFC) → Layer 1 (Execute phase)
Layer 1: CoreAgent Runtime (RFC-100) → Tools/Subagents
```

**Layer 2 Responsibilities**:
- Single-goal focus with iterative refinement
- LLM-driven reasoning through PlanResult
- Evidence accumulation and goal-directed evaluation
- Adaptive execution with strategy reuse
- Context isolation and execution bounds
- Layer 1 delegation via CoreAgent execution

### Integration with Layer 3

**Layer 3 → Layer 2**: `judge_result = await agentic_loop.astream(goal_description, thread_id, max_iterations=8)`

**Layer 2 → Layer 3**: Return `PlanResult` with status, evidence_summary, goal_progress, confidence, reasoning.

### Integration with Layer 1

**Layer 2 → Layer 1**: `result = await core_agent.astream(input, config)` for step execution.

**Layer 1 → Layer 2**: CoreAgent returns streaming execution results for evidence accumulation.

### Architectural Role Clarification

**Important**: AgentLoop is the **Layer 2 Plan → Execute loop runner**, not a consciousness module or knowledge accumulator. Its responsibilities are execution orchestration and iterative refinement, not knowledge persistence.

**Architectural Separation**:
- **AgentLoop**: Layer 2 loop runner (Plan → Execute iterations)
- **ContextProtocol**: Consciousness/knowledge ledger (unbounded context accumulation)
- **GoalEngine**: Layer 3 goal lifecycle manager (DAG management, goal status)
- **Executor**: AgentLoop component for thread coordination

**Why This Matters**: Brainstorming sessions sometimes confuse AgentLoop with "consciousness" because it maintains execution history. However, consciousness (unbounded knowledge with bounded projections) lives in ContextProtocol, not AgentLoop. AgentLoop's history is iteration-scoped execution state, not global knowledge accumulation.

### Retrieval authority (AgentLoop versus ContextProtocol)

Design discussions sometimes assign "unbounded retrieval authority" to the loop. In Soothe specs:

- **ContextProtocol** owns append-only ledger semantics, persistence hooks, and the **retrieval module implementation** (see RFC-400).
- **AgentLoop** owns **when** to retrieve, **for which goal**, and how retrieved entries combine with `GoalContextManager` output and Plan / Execute prompts. It exercises **operational retrieval authority** without owning the ledger.

### GoalEngine-AgentLoop synchronization (dual trigger)

Layer 3 (`GoalEngine`, RFC-200) and AgentLoop stay in sync through **two complementary triggers** (both may appear in a single run):

1. **Reactive (event-bound)**: On thread completion, step boundaries, or failure paths, Layer 2 updates evidence and drives calls that mutate or query goal state as required by RFC-200 (for example failure handling and backoff application).
2. **Need-based pull**: Before scheduling or thread decisions, Layer 2 **pulls** authoritative goal data (`ready_goals`, snapshots, directive results) whenever the next action depends on the DAG.

Exact ordering is defined across RFC-200, RFC-203, and RFC-207; this subsection fixes the **contract** that synchronization is intentionally hybrid, not exclusively polling or exclusively push.

### Execute-time packaging (`config.configurable` versus TaskPackage)

The normative interchange for passing execution hints into CoreAgent today is **LangGraph `config.configurable`** (see Executor integration in this RFC). A **documentary alternative** is assembling a single **`TaskPackage`** object (goal briefing, history snippets, backoff evidence, and `StepAction`) and mapping it into config before `astream`. Either pattern satisfies "direct provisioning" from design brainstorms; promoting `TaskPackage` to a required wire type would be a separate RFC change.

---

## Plan-Execute Loop Model

### Execution Flow

```text
Goal → while iteration < max_iterations:
  PLAN: Produce PlanResult (plan assessment + progress judgment + next steps)
  EXECUTE: Execute steps via Layer 1 CoreAgent, collect evidence
  Decision: "done" (return), "replan" (new plan), "continue" (reuse plan)
```

**Iteration Semantics**:
- Max ~8 iterations
- Decision reuse (skip PLAN if strategy valid)
- Goal-directed judgment (evaluate progress toward goal, not plan completion)

### Iteration Flow Example

```
Iteration 1: PLAN (create 4 steps) → EXECUTE (execute 1-2) → "continue"
Iteration 2: [Skip PLAN] → EXECUTE (execute 3-4) → "replan"
Iteration 3: PLAN (create 3 new steps) → EXECUTE → "done"
Return PlanResult
```

---

## AgentDecision Model

### Batch Execution Design

```python
class StepAction(BaseModel):
    """Single step action within AgentDecision."""
    description: str
    """Human-readable step description."""
    tools: list[str] | None = None
    """Tool suggestions for this step."""
    subagent: str | None = None
    """Subagent suggestion for this step."""
    expected_output: str
    """Expected output description."""
    dependencies: list[str] | None = None
    """Step dependencies for DAG scheduling."""

class AgentDecision(BaseModel):
    """LLM decision output for Execute phase."""
    type: Literal["execute_steps", "final"]
    """Decision type: execute steps or final result."""
    steps: list[StepAction]
    """1 or N steps (hybrid flexibility)."""
    execution_mode: Literal["parallel", "sequential", "dependency"]
    """Execution mode for batch steps."""
    reasoning: str
    """LLM reasoning for this decision."""
```

**Batch Execution Properties**:
- LLM decides 1 or N steps (adaptive granularity)
- Execution mode (parallel/sequential/dependency)
- Hybrid flexibility (step-level execution hints)

### Adaptive Step Granularity

LLM decides step granularity based on goal clarity:
- **Coarse steps**: Clear goals with semantic subtasks
- **Fine steps**: Uncertain goals with atomic actions

**Logic**: Goal uncertainty → fine steps (exploratory), Goal clarity → coarse steps (semantic tasks).

---

## PlanResult Model

### Goal-Directed Evaluation

```python
class PlanResult(BaseModel):
    """Single LLM call combining planning + judgment + next steps."""
    status: Literal["continue", "replan", "done"]
    """Decision status for iteration continuation."""
    goal_progress: float = Field(ge=0.0, le=1.0)
    """Progress toward goal (0.0-1.0)."""
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)
    """Confidence in progress assessment."""
    reasoning: str
    """Natural language reasoning for decision."""
    evidence_summary: str
    """Accumulated evidence from step results."""
    user_summary: str
    """Human-readable progress summary."""
    plan_action: Literal["keep", "new"]
    """Reuse or replace plan decision."""
    decision: AgentDecision | None
    """New plan when plan_action=="new"."""
    next_steps_hint: str
    """Guidance for next Execute phase."""
```

**Planning Logic**:
- Single LLM call combines: planning + progress assessment + goal-distance estimation
- Decision criteria: done (goal achieved), continue (strategy valid, partial progress), replan (strategy failed)

---

## PLAN Phase

### Planning Decision Logic

```python
# Reuse plan if previous PlanResult says "continue" and has remaining steps
if previous_plan.status == "continue" and has_remaining_steps(previous_decision):
    return previous_decision  # Skip PLAN phase

# Create new plan (initial or replan)
result = await planner.plan(goal, state, context, previous_plan)
```

**Iteration-Scoped Planning**: PLAN inside loop (not before loop starts).
- Reuse plan on "continue" (skip PLAN phase)
- Replan on "replan" (new PLAN phase)

### Plan Metrics Enhancement

Structured wave metrics inform Plan decisions:
```python
class LoopState(BaseModel):
    # Wave execution metrics
    last_wave_tool_call_count: int = 0
    last_wave_subagent_task_count: int = 0
    last_wave_hit_subagent_cap: bool = False
    last_wave_output_length: int = 0
    last_wave_error_count: int = 0

    # Context window metrics
    total_tokens_used: int = 0
    context_percentage_consumed: float = 0.0
```

**Metrics-Driven Approach**: Prevents premature `continue` after satisfactory output by considering:
- Tool call count
- Subagent task count
- Output length
- Error count
- Context window usage

---

## EXECUTE Phase

### Hybrid Execution Modes

```python
async def execute(decision: AgentDecision, state: LoopState):
    if decision.execution_mode == "parallel":
        # RFC-207: All steps use parent thread_id (langgraph handles concurrency)
        results = await asyncio.gather([
            execute_step(step, thread_id=state.thread_id)
            for step in decision.steps
        ])
    elif decision.execution_mode == "sequential":
        combined_input = build_sequential_input(decision.steps)
        results = await core_agent.astream(combined_input, thread_id)
    elif decision.execution_mode == "dependency":
        results = await execute_dag_steps(scheduler, core_agent, thread_id)
```

### Context Isolation (Simplified by RFC-207)

**Subagent Steps**: Task tool creates isolated thread branches automatically (`{thread_id}__task_{uuid}` internally)

**Tool-Only Steps**: Use parent thread context (langgraph handles concurrent execution safely)

**Thread Safety**: Langgraph's atomic state updates and message queue prevent conflicts

**No Manual Thread ID Generation**: Executor passes parent thread_id to CoreAgent for all executions

### Execution Bounds

**Two-Layer Constraint**: Prevents runaway subagent loops.

**Soft Constraint**: Schema/prompt defines "one delegation = one call; retry = explicit second step"

**Hard Constraint**: `max_subagent_tasks_per_wave` cap (default 2) stops stream early. Cap hit signals metrics to Plan for replan/continue decision.

### Layer 1 Integration

```python
config = {
    "configurable": {
        "thread_id": tid,
        "soothe_step_tools": step.tools,
        "soothe_step_subagent": step.subagent,
        "soothe_step_expected_output": step.expected_output,
    }
}
```

**CoreAgent Responsibilities**:
- Execute tools/subagents
- Consider execution hints
- Apply middlewares
- Manage thread state
- Return streaming results

**Layer 2 Controls**:
- What to execute
- Execution suggestions
- Timing and sequencing
- Thread isolation (automatic)
- Execution bounds (soft + hard cap)
- Metrics aggregation

---

## Contamination Prevention

### Cross-Wave Isolation

**Problem**: Wave 1 output contaminates Wave 2 delegation (e.g., research output causes translation language detection failure).

**Solution**: Thread isolation for delegation steps. Subagent sees only explicit task input, no prior wave outputs or conversation history.

**Mechanism** (simplified by RFC-207): Task tool automatically creates isolated thread branch for subagent delegations.

### Output Duplication Prevention

**Problem**: Subagent output streamed to TUI, then main model repeats it verbatim.

**Solution**: Output contract suffix (anti-repetition instructions) + metrics-driven Plan prevents premature `continue`.

**Mechanism**: Layer 2 contract suffix in executor. Better Plan decisions (metrics-aware) reduce post-delegation summary tendency.

### Premature Continue Detection

**Problem**: Plan decides `continue` after satisfactory Execute output, triggering unnecessary iteration.

**Solution**: Structured metrics inform Plan of wave completion status. Output length, subagent count, cap hit signal done vs continue criteria.

**Mechanism**: `<SOOTHE_WAVE_METRICS>` section in Plan prompt. Model judges based on metrics pattern + goal text.

---

## Layer 2 Failure Evidence Handoff to Layer 3

Layer 2 does not own backoff policy. It produces high-fidelity execution evidence and hands it to Layer 3 GoalEngine, which owns backoff reasoning and DAG restructuring.

**Ownership boundary**:
- Layer 2 (`RFC-201`): produce execution evidence and failure context.
- Layer 3 (`RFC-200`): define and execute `GoalBackoffReasoner` policy and `BackoffDecision`.

**Canonical models**:
- Backoff and DAG-restructuring models: see `RFC-200`.
- Shared evidence schema (`EvidenceBundle`, `GoalSubDAGStatus`): see `RFC-200`.

### Handoff Contract

```python
class Layer2FailureHandoff(BaseModel):
    """Layer 2 handoff payload to Layer 3 on goal-path failure."""

    goal_id: str
    """Failed goal identifier."""

    plan_result: PlanResult
    """Latest PlanResult with iteration reasoning."""

    evidence: EvidenceBundle
    """Canonical evidence payload (RFC-200 shared contract)."""

    thread_context_hint: str | None = None
    """Optional thread-switch/goal-context note from RFC-207 components."""
```

### Integration Flow

```
Layer 2 Execute/Plan detects failed path
├─ Build canonical EvidenceBundle from wave metrics + summaries
├─ Emit Layer2FailureHandoff(goal_id, plan_result, evidence)
└─ Return control to Layer 3 PERFORM/REFLECT boundary

Layer 3 GoalEngine receives handoff
├─ Calls GoalBackoffReasoner (RFC-200)
├─ Applies BackoffDecision + GoalDirectives
└─ Reschedules DAG from selected backoff point
```

---

## Stream Events

| Event | Description |
|-------|-------------|
| `soothe.agentic.loop.started` | AgentLoop execution began |
| `soothe.agentic.iteration.started` | Iteration began |
| `soothe.cognition.agent_loop.plan` | PLAN phase completed (PlanResult) |
| `soothe.agentic.execute.started` | EXECUTE phase began |
| `soothe.agentic.execute.step_completed` | Step completed |
| `soothe.agentic.loop.completed` | Loop completed |

---

## Configuration

```yaml
agentic:
  enabled: true
  max_iterations: 8

  # Thread isolation for sequential Execute
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

---

## Implementation Status

- ✅ Plan → Execute loop implemented
- ✅ AgentDecision batch execution model
- ✅ PlanResult goal-directed evaluation
- ✅ Iteration-scoped planning
- ✅ EXECUTE → CoreAgent integration
- ✅ Thread isolation pattern
- ✅ Subagent task cap tracking
- ✅ Output contract suffix
- ✅ Prior conversation for Plan
- ✅ Metrics aggregation in executor
- ✅ LoopState wave metrics schema
- ✅ Metrics-driven Plan prompts
- ✅ Token tracking with tiktoken fallback
- ✅ Evidence-driven Plan messages

---

## References

- RFC-000: System conceptual design
- RFC-001: Core modules architecture
- RFC-100: CoreAgent runtime
- RFC-200: Layer 3 Goal management and backoff authority
- RFC-203: AgentLoop State & Memory Architecture
- RFC-207: AgentLoop Thread Management & Goal Context
- RFC-213: AgentLoop Reasoning Quality & Robustness

---

## Changelog

### 2026-04-17
- Consolidated legacy Layer 2 loop/decision/result RFC fragments into this unified core loop architecture
- Unified batch execution model with PlanResult goal-directed evaluation
- Maintained all implementation status and configuration details
- Added contamination prevention section (cross-wave, output duplication, premature continue)
- Preserved stream events and metrics-driven planning logic

---

*Layer 2 agentic execution through Plan → Execute loop with context isolation, execution bounds, metrics-driven planning, and goal-directed evaluation.*