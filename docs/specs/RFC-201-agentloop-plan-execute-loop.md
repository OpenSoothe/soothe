# RFC-201: AgentLoop Plan-Execute Loop Architecture

**RFC**: 201
**Title**: AgentLoop Plan-Execute Loop Architecture (Consolidated Layer 2)
**Status**: Implemented
**Kind**: Architecture Design
**Created**: 2026-04-17
**Last Updated**: 2026-04-29
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

**AgentLoop Goal Pull Architecture** (Inverted Control Flow):

Layer 2 AgentLoop actively queries Layer 3 GoalEngine for goal assignment and reports execution results. GoalEngine provides goal state service, never invokes AgentLoop.

**Integration Pattern**:

```python
# AgentLoop initialization (run_with_progress)
async def run_with_progress(...):
    # PULL: AgentLoop queries GoalEngine for current goal
    goal_engine = config.resolve_goal_engine()
    current_goal = goal_engine.get_next_ready_goal()
    
    if not current_goal:
        return None
    
    # Execute Layer 2 loop (AgentLoop drives)
    state = LoopState(
        current_goal_id=current_goal.id,
        goal_text=current_goal.description,
        ...
    )
    
    plan_result = await self.run_iteration(state)
    
    # REPORT: AgentLoop reports result to GoalEngine
    if plan_result.status == "done":
        goal_engine.complete_goal(current_goal.id, plan_result)
    elif plan_result.status == "failed":
        evidence = EvidenceBundleBuilder().build_from_plan_result(...)
        await goal_engine.fail_goal(current_goal.id, evidence)
    
    return plan_result
```

**Integration Contract**:

| Trigger | AgentLoop Action | GoalEngine Response |
|---------|------------------|---------------------|
| Goal assignment | `get_next_ready_goal()` | Return DAG-satisfied goal |
| Goal completion | `complete_goal(goal_id, plan_result)` | Update goal status |
| Goal failure | `fail_goal(goal_id, EvidenceBundle)` | Apply BackoffReasoner |

**Architectural Principle**: AgentLoop owns execution timing, GoalEngine provides goal state service (inverted control flow, no active PERFORM delegation).

### Integration with Layer 1

**Layer 2 → Layer 1**: `result = await core_agent.astream(input, config)` for step execution.

**Layer 1 → Layer 2**: CoreAgent returns streaming execution results for evidence accumulation.

### Adaptive final user response (IG-199)

When the Plan phase returns `status: done`, AgentLoop must produce the user-visible completion text. Two strategies exist:

1. **Reuse last Execute assistant text**: After each Execute wave on the goal thread, AgentLoop records the assistant-visible text from the CoreAgent stream. For simple goals (light evidence, single-wave semantics, no parallel multi-step wave), this text may be returned directly without a second CoreAgent turn.
2. **Final thread synthesis**: An additional CoreAgent turn asks for a consolidated report over full thread history. Used when evidence heuristics indicate a multi-step or heavy run, when the last wave used parallel multi-step execution, when the subagent task cap was hit, or when no assistant text was captured.

Configuration (`agentic.final_response`): `adaptive` (default) applies the policy above; `always_synthesize` always runs the report turn; `always_last_execute` skips the report when last Execute text exists (falling back to plan evidence otherwise).

### Architectural Role Clarification

**Important**: AgentLoop is the **Layer 2 Plan → Execute loop runner**, not a consciousness module or knowledge accumulator. Its responsibilities are execution orchestration and iterative refinement, not knowledge persistence.

**Architectural Separation**:
- **AgentLoop**: Layer 2 loop runner (Plan → Execute iterations)
- **ContextProtocol**: Consciousness/knowledge ledger (unbounded context accumulation)
- **GoalEngine**: Layer 3 goal lifecycle manager (DAG management, goal status)
- **Executor**: AgentLoop component for thread coordination

**Why This Matters**: Brainstorming sessions sometimes confuse AgentLoop with "consciousness" because it maintains execution history. However, consciousness (unbounded knowledge with bounded projections) lives in ContextProtocol, not AgentLoop. AgentLoop's history is iteration-scoped execution state, not global knowledge accumulation.

### Retrieval authority (AgentLoop versus ContextProtocol)

**Architectural clarification**: Brainstorming sessions sometimes assign "unbounded retrieval authority" to AgentLoop. RFCs clarify the ownership boundary:

**ContextProtocol ownership** (RFC-001, RFC-400):
- Append-only ledger semantics (unbounded knowledge accumulator)
- Persistence hooks (thread-level restore/persist)
- **Retrieval module implementation** (RFC-400 `ContextRetrievalModule`)
- Retrieval algorithm evolution behind stable API

**AgentLoop operational authority** (this RFC):
- **When** to retrieve (iteration start, thread switch, goal dependency)
- **For which goal** (goal-centric retrieval via `retrieve_by_goal_relevance()`)
- **How** retrieved entries combine with GoalContextManager output and Plan/Execute prompts

**Integration**: AgentLoop calls `ContextProtocol.get_retrieval_module().retrieve_by_goal_relevance(goal_id, execution_context, limit)` when building Plan/Execute context. Retrieval algorithm implementation details stay encapsulated in ContextProtocol, preserving architectural separation.

**Integration Pattern Example**:

```python
# AgentLoop.Executor calls ContextProtocol retrieval module
retrieval = context.get_retrieval_module()
relevant_history = retrieval.retrieve_by_goal_relevance(
    goal_id=state.current_goal_id,
    execution_context={"iteration": state.iteration},
    limit=10,
)
# Combine with GoalContextManager output for Plan/Execute context
```

**Reference**: RFC-400 defines canonical retrieval API. RFC-001 §28-62 references RFC-400 as single authoritative retrieval specification.

### Dual Trigger Synchronization Ordering

Layer 2 (AgentLoop) and Layer 3 (GoalEngine, RFC-200) stay synchronized through **ordered complementary triggers** with precise timing guarantees.

**Trigger Types**:

**REACTIVE Trigger** (Event-Bound):
- Timing: Fired after execution boundaries (completion, failure, step completion)
- Purpose: Push evidence to GoalEngine immediately
- Direction: AgentLoop → GoalEngine (push)
- Examples: complete_goal(), fail_goal(), event emission

**PULL Trigger** (Need-Based):
- Timing: Fired before decisions requiring goal context (Plan, after backoff, iteration boundaries)
- Purpose: Query GoalEngine for authoritative state
- Direction: AgentLoop → GoalEngine (query)
- Examples: get_goal(), get_next_ready_goal(), ready_goals()

**Ordered Sync Sequence (Per Iteration)**:

| Step | Trigger | When | AgentLoop Call | Purpose |
|------|---------|------|----------------|---------|
| 1 | **PULL #1** | Before Plan | `get_goal(goal_id)` | Get goal state (priority, dependencies) |
| 2 | PLAN | - | - | LLM reasoning with goal context |
| 3 | EXECUTE | - | - | Run steps, collect evidence |
| 4 | **REACTIVE #1** | Goal completion | `complete_goal()` | Mark goal completed |
| 5 | **REACTIVE #2** | Execution failure | `fail_goal(evidence)` | Handoff failure evidence |
| 6 | **PULL #2** | After backoff | `get_goal(goal_id)` | Check updated goal status |
| 7 | **REACTIVE #3** | Step completion | `emit_event()` | Observability (optional) |
| 8 | **PULL #3** | Before next iteration | `ready_goals()` | Check DAG consistency |

**Critical Ordering Constraints**:

1. **PULL before Plan (mandatory)**: Planning requires authoritative goal state. Violation: stale goal context, wrong priority order.
2. **REACTIVE after execution (immediate)**: GoalEngine needs evidence for DAG decisions. Violation: state stale during reflection.
3. **PULL after backoff (before continuing)**: Backoff may reset goal status. Violation: AgentLoop continues on inactive goal.
4. **PULL before iteration boundary**: Reflection may add dependencies. Violation: executing goal with unsatisfied dependencies.

**Race Condition Handling**:

- **External DAG mutation**: PULL #1 detects status change → abort iteration
- **Parallel threads**: Each thread pulls independently, GoalEngine atomic updates
- **Backoff while executing**: PULL #2 detects goal "pending" → end iteration
- **Reflection adds dependency**: PULL #3 detects goal not ready → defer iteration

**Contract**: Synchronization is intentionally hybrid (PULL + REACTIVE) with ordering guarantees for consistency.

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

**Iteration-Scoped Planning**: PLAN inside loop (not before loop starts).

**Reuse Logic**:
- Reuse plan if previous PlanResult.status == "continue" and has remaining steps (skip PLAN phase)
- Create new plan (initial or replan) when PlanResult.status == "replan" or plan exhausted

**Plan Metrics Enhancement**: Structured wave metrics inform Plan decisions.

### GoalContext Construction for Plan

**Dependency-Driven Retrieval**: Plan phase requires dependency-aware context synthesized from GoalEngine and ContextProtocol.

**Synthesis Components**:
1. **GoalEngine metadata**: Current goal priority, dependency goal IDs
2. **ContextProtocol retrieval**: 
   - Dependency goals: retrieve execution history (5 entries per dependency)
   - Current goal: goal-centric retrieval (10 entries)
3. **GoalContextManager summaries**: Previous goal summaries (5 entries)

**PlanContext Integration**: AgentLoop calls `GoalContextConstructor.construct_plan_context(goal_id)` during PULL #1 before Plan phase.

**Architectural Principle**: Goal dependencies define relevant context scope. Prerequisite goal execution history provides constraints and learned patterns for planning.

### Plan Metrics Enhancement

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

**CoreAgent Config Injection**: Executor passes execution hints via `config.configurable` (thread_id, step tools, subagent hints, expected output).

**CoreAgent Responsibilities**:
- Execute tools/subagents
- Consider execution hints
- Apply middlewares
- Manage thread state
- Return streaming results

**Layer 2 Controls**:
- What to execute (AgentDecision.steps)
- Execution suggestions (tools, subagent hints)
- Timing and sequencing
- Thread isolation (automatic via RFC-207)
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

### Execute-Phase Output Suppression Contract (IG-304)

Execute-phase assistant prose is internal orchestration output and should not be emitted as user-facing output events. AgentLoop must:

1. keep tool activity observable via message-mode tool chunks/events,
2. emit final user-facing answer text through goal-completion output events only,
3. avoid relying on client-side suppression to hide execute-phase prose.

### Premature Continue Detection

**Problem**: Plan decides `continue` after satisfactory Execute output, triggering unnecessary iteration.

**Solution**: Structured metrics inform Plan of wave completion status. Output length, subagent count, cap hit signal done vs continue criteria.

**Mechanism**: `<SOOTHE_WAVE_METRICS>` section in Plan prompt. Model judges based on metrics pattern + goal text.

---

## Layer 2 Failure Evidence Handoff to Layer 3

Layer 2 does not own backoff policy. It produces high-fidelity execution evidence and hands it to Layer 3 GoalEngine, which owns backoff reasoning and DAG restructuring (encapsulated).

**Ownership Boundary**:
- **Layer 2 (`RFC-201`)**: Produce execution evidence via EvidenceBundleBuilder, call GoalEngine.fail_goal()
- **Layer 3 (`RFC-200`)**: Define and execute GoalBackoffReasoner policy internally, apply BackoffDecision
- **Shared contract**: EvidenceBundle (RFC-200 §14-22) with structured + narrative fields
- **Encapsulation**: AgentLoop never calls BackoffReasoner directly

### EvidenceBundle Contract

**EvidenceBundle Data Model** (RFC-200 §14-22 canonical structure):

**Structured Field**: Machine-readable execution metrics from LoopState wave tracking (§236-245)
- iteration: int
- wave_tool_calls: int (last_wave_tool_call_count)
- wave_subagent_tasks: int (last_wave_subagent_task_count)
- wave_errors: int (last_wave_error_count)
- wave_output_length: int (last_wave_output_length)
- wave_hit_subagent_cap: bool
- goal_progress: float
- confidence: float
- plan_status: str

**Narrative Field**: Natural language synthesis for GoalBackoffReasoner
- Synthesized from: PlanResult.reasoning, evidence_summary, user_summary
- Wave metrics pattern analysis: tool/subagent counts, error patterns, resource constraints

**Source**: "layer2_execute" or "layer2_plan" (evidence producer stage)
**Timestamp**: Evidence emission time

### Handoff Integration Architecture

**AgentLoop → GoalEngine Flow**:

1. **Build Evidence**: AgentLoop Executor constructs EvidenceBundle from execution context (PlanResult + LoopState wave metrics)
2. **Handoff**: REACTIVE trigger #2 - AgentLoop calls GoalEngine.fail_goal(goal_id, evidence)
3. **GoalEngine Processing** (encapsulated):
   - Build GoalContext snapshot from goal DAG
   - Call BackoffReasoner.reason_backoff() with goal context + evidence
   - Apply BackoffDecision (DAG restructuring, reset backoff target to "pending")
   - Persist DAG mutation
4. **Next Iteration**: PULL #2 checks updated goal status → abort if "pending"

**Architectural Guarantee**: AgentLoop hands off evidence, GoalEngine owns backoff reasoning (clear ownership boundary, no circular dependency).

---

## Stream Events

| Event | Description |
|-------|-------------|
| `soothe.cognition.agent_loop.started` | AgentLoop execution began |
| `soothe.cognition.agent_loop.reasoned` | Plan/assessment progress summary event |
| `soothe.cognition.agent_loop.step.started` | EXECUTE step began |
| `soothe.cognition.agent_loop.step.completed` | EXECUTE step completed |
| `soothe.output.goal_completion.streaming` | Streaming final answer chunk |
| `soothe.output.goal_completion.responded` | Final answer payload |
| `soothe.cognition.agent_loop.completed` | Loop completed lifecycle event |

**Contract note**: Message-mode tool telemetry chunks remain visible during execute; plain execute-phase assistant prose is daemon-suppressed and not part of user-facing output events.

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

### 2026-04-29
- Aligned stream event table with current event contract (`soothe.cognition.agent_loop.reasoned`).
- Clarified execute-phase suppression and tool-telemetry visibility semantics.

### 2026-04-17
- Consolidated legacy Layer 2 loop/decision/result RFC fragments into this unified core loop architecture
- Unified batch execution model with PlanResult goal-directed evaluation
- Maintained all implementation status and configuration details
- Added contamination prevention section (cross-wave, output duplication, premature continue)
- Preserved stream events and metrics-driven planning logic

---

*Layer 2 agentic execution through Plan → Execute loop with context isolation, execution bounds, metrics-driven planning, and goal-directed evaluation.*