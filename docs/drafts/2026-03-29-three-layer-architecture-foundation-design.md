# Three-Layer Execution Architecture Foundation Design

**Created**: 2026-03-29
**Status**: Draft
**Purpose**: Establish foundational RFC architecture for Soothe's three-layer execution model

---

## Abstract

This design establishes Soothe's three-layer execution architecture as a foundational framework for all agent runtime systems. Each layer has distinct responsibilities, clear delegation boundaries, and explicit integration contracts. The architecture separates concerns between goal orchestration (Layer 3), goal execution (Layer 2), and runtime execution (Layer 1), enabling modular evolution while maintaining coherent system behavior.

---

## 1. Architecture Overview

### 1.1 Three-Layer Model

Soothe operates through a hierarchical execution model with three distinct layers:

```
┌─────────────────────────────────────────────────────────────┐
│ Layer 3: Autonomous Goal Management (RFC-200)               │
│                                                                │
│ • Scope: Long-running complex workflows, multi-goal DAGs      │
│ • Loop: Goal/Goals → PLAN → PERFORM → REFLECT → Update       │
│ • Max iterations: Large (10-50+)                             │
│ • Delegation: PERFORM invokes Layer 2's full loop             │
│ • Integration: Receives Layer 2's JudgeResult for REFLECT    │
└─────────────────────────────────────────────────────────────┘
                          ↓ PERFORM (full delegation)
┌─────────────────────────────────────────────────────────────┐
│ Layer 2: Agentic Goal Execution (RFC-200 - redesigned)      │
│                                                                │
│ • Scope: Single-goal execution through iterative refinement   │
│ • Loop: PLAN → ACT → JUDGE (max iterations: ~8)              │
│ • AgentDecision: Hybrid (single step or batch of steps)      │
│ • Step granularity: Adaptive (LLM decides atomic vs semantic)│
│ • Judgment: Evidence accumulation toward goal completion     │
│ • Iteration flow: Reuse decision until "replan" or "done"    │
│ • Delegation: ACT invokes Layer 1 CoreAgent for execution    │
└─────────────────────────────────────────────────────────────┘
                          ↓ ACT (step execution)
┌─────────────────────────────────────────────────────────────┐
│ Layer 1: CoreAgent Runtime (new RFC)                          │
│                                                                │
│ • Foundation: create_soothe_agent() → CompiledStateGraph     │
│ • Capabilities: Tools, subagents, middlewares (built-in)     │
│ • Execution: Model → Tools → Model loop (LangGraph native)   │
│ • Thread model: Sequential vs parallel (isolated threads)    │
│ • Integration: ACT phase uses agent.astream() with config   │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 Design Principles

1. **Layer Separation**: Each layer has distinct responsibilities and does not cross boundaries
2. **Delegation Model**: Higher layers delegate to lower layers through explicit contracts
3. **Iterative Refinement**: Each layer uses iterative loops appropriate to its scope
4. **Evidence Flow**: Results flow upward as evidence for decision-making at each layer
5. **Strategy Reuse**: Layers reuse strategies until evaluation indicates revision needed
6. **Adaptive Execution**: LLM-driven decisions adapt to goal clarity and progress state

### 1.3 Layer Relationships

| Layer | Purpose | Delegates To | Receives From |
|-------|---------|--------------|---------------|
| **Layer 3** | Goal DAG orchestration | Layer 2 (PERFORM) | JudgeResult, goal directives |
| **Layer 2** | Single-goal execution | Layer 1 (ACT) | StreamChunks, step evidence |
| **Layer 1** | Runtime execution | deepagents/LangGraph | Tool results, model responses |

---

## 2. Layer 3: Autonomous Goal Management

### 2.1 Architecture Position

**RFC**: RFC-200 (revised)
**Title**: "Layer 3: Autonomous Goal Management Loop"
**Status**: Layer 3 foundation for multi-goal orchestration

Layer 3 manages complex, long-running workflows that decompose into goal DAGs with dependencies, priorities, and dynamic restructuring capabilities. It operates at the highest abstraction level, focusing on goal lifecycle management rather than execution details.

### 2.2 Loop Model

```
Goal/Goals → PLAN (goal-level decomposition) → PERFORM (delegate to Layer 2)
  → REFLECT (evaluate DAG progress) → Goal Update → REPLAN → repeat
```

**Iteration Semantics**:
- **Max iterations**: Large budget (10-50+) for complex problem solving
- **Goal lifecycle**: Create → Activate → Execute → Reflect → Complete/Fail
- **DAG scheduling**: Goals execute when dependencies satisfied, parallel batches when independent

### 2.3 Delegation Model

**PERFORM Stage → Layer 2 (Full Delegation)**:

Layer 3's PERFORM stage invokes Layer 2's **complete PLAN → ACT → JUDGE loop** for single-goal execution:

```python
# Layer 3 PERFORM stage
async def perform_goal(goal: Goal) -> JudgeResult:
    # Delegate to Layer 2's full loop
    judge_result = await agentic_loop.astream(
        goal_description=goal.description,
        thread_id=f"{parent_tid}__goal_{goal.id}",
        max_iterations=8  # Layer 2 iteration budget
    )
    return judge_result  # Layer 2 returns final judgment
```

**Integration with Layer 2**:
- Layer 2 runs autonomously until returning JudgeResult (done/replan status)
- Layer 3's REFLECT stage receives JudgeResult and uses evidence_summary for goal DAG evaluation
- GoalProgress from Layer 2 informs Layer 3's goal completion decisions

### 2.4 Dynamic Goal Management

**GoalDirective Model** (merged from RFC-200 (merged)):

Layer 3's reflection can dynamically restructure the goal DAG through structured directives:

```python
class GoalDirective(BaseModel):
    action: Literal["create", "adjust_priority", "add_dependency", "decompose", "fail", "complete"]
    goal_id: str | None  # Target goal for directive
    description: str | None  # For create/decompose actions
    priority: int | None  # For adjust_priority
    depends_on: list[str] | None  # For add_dependency
    reason: str  # Why this directive was generated
```

**GoalContext Model**:

Reflection receives full goal DAG state for informed decision-making:

```python
class GoalContext(BaseModel):
    current_goal_id: str
    all_goals: list[GoalSnapshot]
    completed_goals: list[str]  # Goal IDs
    failed_goals: list[str]
    ready_goals: list[str]  # Dependency-satisfied
    max_parallel_goals: int
```

**Safety Mechanisms**:
- **Cycle detection**: DFS-based validation prevents dependency cycles
- **Depth limits**: Maximum hierarchy depth (default: 5 levels)
- **Total goals limit**: Prevents runaway creation (default: 50 goals)
- **Validation before application**: All directives validated before state mutation
- **Atomic checkpoints**: Goal mutations checkpointed immediately after application

### 2.5 Integration with Layer 2 JudgeResult

Layer 3's REFLECT stage receives Layer 2's judgment and incorporates evidence into goal DAG evaluation:

```python
# Layer 3 REFLECT stage
async def reflect_on_goal(goal: Goal, judge_result: JudgeResult) -> Reflection:
    reflection = await planner.reflect(
        plan=goal_plan,
        step_results=goal_step_results,
        goal_context=goal_context,  # Includes Layer 2 evidence
        layer2_judgment=judge_result  # Layer 2's evaluation
    )
    # reflection includes:
    # - should_revise: whether goal plan needs revision
    # - goal_directives: DAG restructuring actions
    return reflection
```

---

## 3. Layer 2: Agentic Goal Execution

### 3.1 Architecture Position

**RFC**: RFC-200 (fundamental redesign)
**Title**: "Layer 2: Agentic Goal Execution Loop"
**Status**: Layer 2 foundation for single-goal execution

Layer 2 executes individual goals through iterative refinement, using LLM-driven planning, execution, and judgment. Each iteration evaluates progress toward the goal and decides whether to continue the current strategy, replan, or conclude goal achievement.

### 3.2 Loop Model

```
PLAN (create/reuse execution strategy) → ACT (execute steps via Layer 1)
  → JUDGE (evaluate goal progress) → continue/replan/done
```

**Iteration Semantics**:
- **Max iterations**: Moderate budget (~8) for goal completion
- **Decision reuse**: Continue executing existing strategy until evaluation indicates revision
- **Goal-directed judgment**: Evaluate progress toward goal completion, not just plan execution

### 3.3 AgentDecision Schema

**Hybrid Decision Model**:

AgentDecision specifies either a single step or a batch of steps for execution:

```python
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

class StepAction(BaseModel):
    """Single step in execution strategy."""

    description: str  # What this step does
    tools: list[str] | None = None  # Tools to use (optional)
    subagent: str | None = None  # Subagent to invoke (optional)
    expected_output: str  # Expected result for evidence accumulation
    dependencies: list[str] | None = None  # Step IDs this depends on
```

**Decision Properties**:
- **Batch execution**: LLM decides how many steps to execute per iteration
- **Execution mode**: Parallel (isolated threads), sequential (shared context), dependency (DAG)
- **Adaptive granularity**: LLM chooses step size based on goal clarity

### 3.4 Step Granularity

**Adaptive Granularity Model**:

Layer 2's planner decides step granularity based on goal characteristics:

- **Clear goals** with well-known procedures → **coarse steps** (semantic subtasks)
  - Example: "analyze requirements", "design solution", "implement", "verify"
  - Broader scope, fewer steps, faster iteration

- **Uncertain goals** requiring exploration → **fine steps** (atomic actions)
  - Example: "check file exists", "read config", "call API", "parse response"
  - Narrow scope, more steps, granular evidence for judgment

- **Granularity as planning decision**: Not fixed policy, but LLM-driven strategy choice

### 3.5 JUDGE Evaluation

**Evidence Accumulation Model**:

JUDGE evaluates goal progress by accumulating evidence from all executed step results:

```python
class JudgeResult(BaseModel):
    """LLM's judgment after evaluating goal progress."""

    status: Literal["continue", "replan", "done"]
    evidence_summary: str  # Accumulated from all step results
    goal_progress: float = Field(ge=0.0, le=1.0)  # Progress toward goal
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)  # Judgment confidence
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

### 3.6 Iteration Flow

**Reuse Existing Decision Model**:

Layer 2 reuses AgentDecision until JUDGE indicates strategy needs revision:

```
Iteration 1:
  PLAN: Create AgentDecision (4 steps)
  ACT: Execute steps 1-2 (partial execution)
  JUDGE: "continue" (strategy valid, 2 more steps needed)

Iteration 2:
  [Skip PLAN, reuse previous AgentDecision]
  ACT: Execute steps 3-4 (remaining steps)
  JUDGE: "replan" (steps 3-4 failed, evidence reveals need for different approach)

Iteration 3:
  PLAN: Create new AgentDecision (3 new steps)
  ACT: Execute new steps
  JUDGE: "done" (goal achieved)

Iteration 4 (if needed): Return to Layer 3
```

**Iteration Semantics**:
- PLAN called at iteration start OR when JUDGE returns "replan"
- If JUDGE returns "continue", reuse existing AgentDecision and execute remaining steps
- Each iteration can execute partial batch (some steps from AgentDecision)
- JUDGE evaluates overall evidence, decides strategy validity

### 3.7 ACT Phase Integration with Layer 1

**Hybrid Sequential vs Parallel Execution**:

ACT phase uses Layer 1 CoreAgent for step execution, choosing execution mode based on AgentDecision.execution_mode:

```python
# Layer 2 ACT phase
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
                thread_id=f"{thread_id}__step_{i}"  # Isolated thread
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
        # Use StepScheduler for DAG-based execution (RFC-200)
        scheduler = StepScheduler(decision.steps)
        results = await execute_dag_steps(scheduler, core_agent, thread_id)

    return results  # Evidence for JUDGE phase
```

**Layer 1 Invocation**:
- Each step (or combined input) calls `core_agent.astream(input, thread_config)`
- CoreAgent handles tool/subagent orchestration internally (Layer 1 responsibility)
- Layer 2 controls WHAT and WHEN (step selection and sequencing)
- Layer 1 controls HOW (tool sequencing within agent turn)

---

## 4. Layer 1: CoreAgent Runtime

### 4.1 Architecture Position

**RFC**: RFC-00XX (new RFC)
**Title**: "Layer 1: CoreAgent Runtime Architecture"
**Status**: Layer 1 foundation for runtime execution

Layer 1 provides the CoreAgent runtime that executes tool and subagent operations through LangGraph's Model → Tools → Model loop. It serves as the execution foundation for both Layer 2's ACT phase and direct CLI/daemon usage.

### 4.2 Foundation

**CoreAgent Factory**:

Layer 1 is built on `create_soothe_agent()` factory from `soothe.core.agent`:

```python
def create_soothe_agent(config: SootheConfig) -> CompiledStateGraph:
    """
    Factory that creates Soothe's CoreAgent runtime.

    Returns:
        CompiledStateGraph with attached protocol instances:
        - soothe_context: ContextProtocol instance
        - soothe_memory: MemoryProtocol instance
        - soothe_planner: PlannerProtocol instance
        - soothe_policy: PolicyProtocol instance
        - soothe_durability: DurabilityProtocol instance
    """
```

**Core Components**:
- **CompiledStateGraph**: LangGraph runtime with Model → Tools → Model loop
- **Tools**: Built-in tools (execution, websearch, research, etc.)
- **Subagents**: Browser, Claude, Skillify, Weaver (deepagents SubAgents)
- **MCP Servers**: Loaded and configured MCP capabilities
- **Middlewares**: Context, Memory, Policy, Planner, Summarization, PromptCaching

### 4.3 Execution Interface

**Agent Stream API**:

CoreAgent provides streaming execution interface for Layer 2 and direct usage:

```python
agent.astream(
    input: str | dict,
    config: RunnableConfig
) → AsyncIterator[StreamChunk]
```

**Config Structure**:
```python
config = {
    "configurable": {
        "thread_id": str,  # Thread context for execution
        "recursion_limit": int,  # Max tool calls per turn
        # ... other LangGraph config
    }
}
```

### 4.4 Thread Model

**Sequential Execution**:
- Single thread context: `thread_id` maintained across agent turn
- Middlewares work per-thread: context isolation, memory persistence
- Tools/subagents share thread state

**Parallel Execution**:
- Isolated thread contexts: Parent thread → child threads (`{parent}__step_{i}`)
- Each parallel execution gets independent agent context
- Results merged after parallel completion

**Thread Isolation for Layer 2**:
- Layer 2 ACT phase creates isolated threads for parallel steps
- CoreAgent manages per-thread middleware state automatically
- Evidence collection aggregates across all thread results

### 4.5 Built-in Capabilities

**Tools** (from various RFCs):
- Execution tools (RFC-101): `execute`, `ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`
- Websearch tools: `TavilySearchResults`, `DuckDuckGoSearchRun`
- Research tools (RFC-601): ArXiv, Wikipedia, GitHub
- Other langchain ecosystem tools

**Subagents** (RFC-601, RFC-601):
- **Browser**: Web browsing and automation
- **Claude**: Claude CLI integration
- **Skillify**: Skill discovery and execution
- **Weaver**: Code weaving and synthesis

**MCP Servers** (RFC-600):
- Loaded via configuration
- Exposed as tools through langchain-mcp-adapters

**Middlewares**:
- **deepagents middlewares**: Summarization, PromptCaching, TodoList, Filesystem
- **Soothe protocol middlewares**: Context, Memory, Policy, Planner (wrapped)

### 4.6 Integration Contract

**Layer 2 → Layer 1 Usage**:

Layer 2's ACT phase invokes CoreAgent for step execution:

```python
# Layer 2 executes step via Layer 1
step_result = await core_agent.astream(
    input=f"Execute: {step.description}",
    config={
        "configurable": {
            "thread_id": f"{parent_tid}__step_{step_index}",
            "recursion_limit": 25
        }
    }
)
```

**CoreAgent Responsibilities**:
- Execute tools/subagents as requested by input context
- Apply middlewares (context injection, policy checking, memory recall/persist)
- Manage thread state and LangGraph turn loop
- Return streaming results for evidence collection

**Layer 2 Controls**:
- What to execute (step content)
- When to execute (iteration timing)
- How to sequence (parallel vs sequential vs dependency)
- Thread isolation strategy

---

## 5. Cross-Layer Integration

### 5.1 Layer 3 → Layer 2 Integration

**PERFORM Stage Delegation**:

```python
# Layer 3 autonomous loop
async def autonomous_iteration(goal_engine: GoalEngine) -> None:
    ready_goals = goal_engine.ready_goals(limit=max_parallel_goals)

    for goal in ready_goals:
        # PERFORM: Delegate to Layer 2's full loop
        judge_result = await agentic_loop.astream(
            user_input=goal.description,
            thread_id=f"{parent_tid}__goal_{goal.id}",
            max_iterations=8,
            return_judge_result=True  # Layer 2 returns JudgeResult
        )

        # REFLECT: Use Layer 2 judgment for goal evaluation
        reflection = await planner.reflect(
            goal_context=build_goal_context(goal_engine),
            layer2_judgment=judge_result  # Layer 2 evidence
        )

        # Apply goal directives from reflection
        if reflection.goal_directives:
            apply_directives(goal_engine, reflection.goal_directives)
```

**Integration Contract**:
- Layer 2 runs complete PLAN → ACT → JUDGE loop
- Layer 2 returns final JudgeResult (not intermediate states)
- JudgeResult.evidence_summary informs Layer 3 goal reflection
- JudgeResult.goal_progress informs goal completion decisions

### 5.2 Layer 2 → Layer 1 Integration

**ACT Phase Execution**:

```python
# Layer 2 agentic loop
async def act_phase(
    decision: AgentDecision,
    core_agent: CompiledStateGraph,
    thread_id: str
) -> list[StepResult]:

    step_results = []

    if decision.execution_mode == "parallel":
        # Parallel execution with isolated threads
        tasks = [
            execute_step_via_agent(core_agent, step, f"{thread_id}__step_{i}")
            for i, step in enumerate(decision.steps)
        ]
        step_results = await asyncio.gather(*tasks)

    elif decision.execution_mode == "sequential":
        # Sequential execution in one agent turn
        stream = await core_agent.astream(
            input=build_input_from_steps(decision.steps),
            config={"thread_id": thread_id}
        )
        step_results = await collect_results(stream)

    return step_results  # Evidence for JUDGE

async def execute_step_via_agent(
    agent: CompiledStateGraph,
    step: StepAction,
    thread_id: str
) -> StepResult:
    """Execute single step through Layer 1 CoreAgent."""
    stream = await agent.astream(
        input=f"Execute: {step.description}",
        config={"configurable": {"thread_id": thread_id}}
    )
    # Collect evidence from stream
    result = await collect_stream_evidence(stream)
    return result
```

**Integration Contract**:
- Layer 2 provides step input and thread configuration
- Layer 1 executes tools/subagents via CoreAgent
- Layer 1 returns streaming results for evidence collection
- Layer 2 accumulates evidence for JUDGE phase

### 5.3 Data Flow Across Layers

```
User Request (complex workflow)
    ↓
Layer 3: Goal DAG Management
    ├─ create_goal(user_request) → root goal
    ├─ PLAN: Goal-level decomposition
    │   └─ GoalEngine creates DAG with dependencies
    ├─ PERFORM: Delegate to Layer 2
    │   ↓
    │   Layer 2: Single-Goal Execution (per goal)
    │   ├─ PLAN: Create AgentDecision (batch of steps)
    │   │   └─ Planner decides step granularity and execution mode
    │   ├─ ACT: Execute steps via Layer 1
    │   │   ↓
    │   │   Layer 1: CoreAgent Runtime
    │   │   ├─ agent.astream(step_input, thread_config)
    │   │   ├─ Model → Tools → Model loop
    │   │   ├─ Middlewares: context, memory, policy
    │   │   ├─ Tool/subagent execution
    │   │   └─ Return: StreamChunk results
    │   │   ↑
    │   ├─ Collect evidence from Layer 1
    │   ├─ JUDGE: Evaluate goal progress
    │   │   └─ Evidence accumulation → JudgeResult
    │   ├─ Loop decision:
    │   │   ├─ "continue" → reuse AgentDecision, execute remaining steps
    │   │   ├─ "replan" → call PLAN, create new strategy
    │   │   └─ "done" → return JudgeResult to Layer 3
    │   └─ Return: JudgeResult
    │   ↑
    ├─ REFLECT: Use JudgeResult for goal evaluation
    │   └─ planner.reflect(goal_context, layer2_judgment)
    │   └─ Generate goal_directives if needed
    ├─ Apply GoalDirective: Update goal DAG
    │   └─ Create new goals, adjust priorities, add dependencies
    ├─ Loop: Continue autonomous iteration
    │   └─ Ready goals → PERFORM → REFLECT → repeat
    └─ Output: Final goal reports
```

---

## 6. RFC Documentation Plan

### 6.1 RFC-200 (Layer 3) - Revised

**Changes**:
- Add §2 "Architecture Layer Position": Three-layer hierarchy, Layer 3 scope
- Merge RFC-200 (merged) content: Dynamic goal management sections
- Update title: "Layer 3: Autonomous Goal Management Loop"
- Specify PERFORM → Layer 2 delegation model (full delegation)
- Define REFLECT integration with Layer 2 JudgeResult
- Update goal lifecycle to include Layer 2 invocation

**Status**: Architecture revision (Draft → Revised)

### 6.2 RFC-200 (Layer 2) - Fundamental Redesign

**Changes**:
- Add §2 "Architecture Layer Position": Three-layer hierarchy, Layer 2 scope
- Redesign AgentDecision: Hybrid multi-step model (batch execution)
- Redesign StepAction: Step-level action model with tools/subagents
- Define iteration-scoped PLAN phase (inside loop, not before)
- Specify goal-directed JUDGE evaluation (evidence accumulation model)
- Define JudgeResult schema: status, evidence_summary, goal_progress, confidence
- Define iteration flow: Reuse decision model
- Define ACT → Layer 1 integration: Hybrid sequential vs parallel execution
- Update title: "Layer 2: Agentic Goal Execution Loop"

**Status**: Fundamental redesign (Draft → Revised)

**Implementation Gap**: Major implementation required (new IG needed)

### 6.3 RFC-00XX (Layer 1) - New RFC

**Content**:
- Title: "Layer 1: CoreAgent Runtime Architecture"
- Abstract: Layer 1 foundation for runtime execution
- §2 Architecture Position: Three-layer hierarchy, Layer 1 scope
- §3 CoreAgent Factory: `create_soothe_agent()` architecture
- §4 Execution Interface: agent.astream() API, config structure
- §5 Thread Model: Sequential vs parallel execution, thread isolation
- §6 Built-in Capabilities: Tools, subagents, middlewares (reference other RFCs)
- §7 Integration Contract: Layer 2 ACT phase usage patterns
- §8 Architecture Role: Foundation for Layer 2 and direct CLI/daemon usage

**Status**: New RFC (Draft)

**Implementation**: Already implemented (`create_soothe_agent()` exists)

### 6.4 RFC-000 - Update

**Changes**:
- Add Principle 11: "Three-layer execution architecture"
- Define layer hierarchy and delegation model
- Update architecture diagram to show three-layer model
- Reference RFC-200, RFC-200, RFC-00XX as foundational documents

**Status**: Architecture update (Draft → Revised)

### 6.5 RFC-200 (merged) - Deprecation

**Status**: Deprecated (merged into RFC-200)

**Merge Notice**: "RFC-200 (merged) content merged into RFC-200 §5.5-5.7"

---

## 7. Implementation Status and Roadmap

### 7.1 Layer Implementation Status

**Layer 3 (RFC-200)**: ✅ **Implemented**
- GoalEngine with DAG scheduling
- Dynamic goal management (RFC-200 (merged) features already in code)
- Reflection with goal directives
- Safety mechanisms and validation
- **Gap**: Missing explicit Layer 2 delegation (PERFORM → Layer 2 loop)
- **Action**: Add Layer 2 invocation in PERFORM stage

**Layer 2 (RFC-200)**: ❌ **Major Implementation Gaps**
- Current implementation: observe → act → verify (not PLAN → ACT → JUDGE)
- AgentDecision: Single tool model (not hybrid multi-step)
- Planning: Happens before loop (not iteration-scoped)
- Judgment: Heuristic-based (not structured goal-directed evaluation)
- Iteration flow: No decision reuse model
- ACT phase: No explicit Layer 1 CoreAgent integration
- **Action**: Complete redesign and implementation (new IG required)

**Layer 1 (RFC-00XX)**: ✅ **Implemented**
- `create_soothe_agent()` factory exists
- CompiledStateGraph with tools, subagents, middlewares
- Execution interface (agent.astream()) works
- Thread model implemented
- **Gap**: Missing architecture documentation as Layer 1 foundation
- **Action**: Document architecture in new RFC

### 7.2 Implementation Roadmap

**Phase 1: RFC Documentation** (Week 1-2)
1. Merge RFC-200 (merged) into RFC-200
2. Revise RFC-200 with Layer 3 positioning
3. Fundamental redesign of RFC-200 (Layer 2)
4. Create RFC-00XX (Layer 1 CoreAgent)
5. Update RFC-000 with three-layer model
6. Run `specs-refine` for validation

**Phase 2: Layer 1 Documentation** (Week 2)
1. Implement RFC-00XX (document existing code)
2. Validate CoreAgent architecture matches RFC
3. Add Layer 1 integration tests

**Phase 3: Layer 2 Implementation** (Week 3-5) - **CRITICAL**
1. Create IG for RFC-200 implementation
2. Redesign AgentDecision schema
3. Implement iteration-scoped planning
4. Implement goal-directed judgment (JudgeEngine)
5. Implement decision reuse model
6. Implement ACT → Layer 1 integration (hybrid execution)
7. Add Layer 2 tests (multi-step, evidence accumulation, iteration flow)

**Phase 4: Layer 3 Integration** (Week 6)
1. Update PERFORM stage to invoke Layer 2 loop
2. Add Layer 2 JudgeResult integration in REFLECT
3. Add cross-layer tests (autonomous → agentic → CoreAgent)

**Phase 5: Validation and Review** (Week 7)
1. Run compliance review for all three layers
2. End-to-end integration tests
3. Performance benchmarking
4. Update RFC status (Draft → Implemented)

---

## 8. Success Criteria

### 8.1 Architecture Integrity
- ✅ Clear layer separation with distinct responsibilities
- ✅ Explicit delegation contracts between layers
- ✅ Evidence flows upward for decision-making
- ✅ No layer boundary violations

### 8.2 Layer 3 Success Criteria
- ✅ Goal DAG management works (create, schedule, complete)
- ✅ Dynamic goal restructuring via GoalDirective
- ✅ PERFORM delegates to Layer 2's full loop
- ✅ REFLECT receives and uses Layer 2 JudgeResult
- ✅ Safety mechanisms prevent runaway creation

### 8.3 Layer 2 Success Criteria
- ✅ PLAN → ACT → JUDGE loop executes iteratively
- ✅ AgentDecision supports hybrid multi-step execution
- ✅ Adaptive step granularity (LLM decides atomic vs semantic)
- ✅ Goal-directed judgment evaluates progress toward goal
- ✅ Decision reuse model works (continue vs replan)
- ✅ ACT phase integrates with Layer 1 CoreAgent (hybrid execution)
- ✅ JudgeResult provides evidence_summary and goal_progress

### 8.4 Layer 1 Success Criteria
- ✅ CoreAgent factory creates CompiledStateGraph with capabilities
- ✅ Execution interface (agent.astream()) works for Layer 2
- ✅ Thread model supports sequential and parallel execution
- ✅ Middlewares integrate (context, memory, policy, planner)
- ✅ Tools/subagents execute correctly

### 8.5 Cross-Layer Integration Success Criteria
- ✅ Layer 3 → Layer 2: PERFORM receives JudgeResult
- ✅ Layer 2 → Layer 1: ACT executes steps via CoreAgent
- ✅ Evidence flows across layers correctly
- ✅ End-to-end workflow: User request → Layer 3 → Layer 2 → Layer 1 → results

---

## 9. Non-Goals

This design does not address:

1. **Tool/subagent implementation details**: Referenced from other RFCs (RFC-601, RFC-601, RFC-101, RFC-601)
2. **Middleware implementation details**: Referenced from RFC-001 and deepagents documentation
3. **LangGraph internals**: Layer 1 uses LangGraph as-is (RFC-000 Principle 2)
4. **Protocol implementation details**: Referenced from RFC-001 (Context, Memory, Policy, Planner, Durability)
5. **Concurrency policy details**: Referenced from RFC-200 (ConcurrencyController, StepScheduler)
6. **Event system details**: Referenced from RFC-400, RFC-400
7. **Plugin system details**: Referenced from RFC-600

---

## 10. References

### Foundational RFCs
- RFC-000: System Conceptual Design
- RFC-001: Core Modules Architecture
- RFC-500: CLI TUI Architecture
- RFC-200: Autonomous Iteration Loop (Layer 3 - revised)
- RFC-200: Agentic Goal Execution Loop (Layer 2 - redesigned)
- RFC-00XX: CoreAgent Runtime Architecture (Layer 1 - new)

### Component RFCs
- RFC-601: Skillify Agent Architecture
- RFC-601: Weaver Agent Architecture
- RFC-200: DAG-Based Execution and Unified Concurrency
- RFC-200: Failure Recovery Persistence
- RFC-102: Secure Filesystem Policy
- RFC-400: Progress Event Protocol
- RFC-101: Tool Interface Optimization
- RFC-600: Plugin Extension System
- RFC-400: Unified Event Processing
- RFC-601: Research Subagent

### Merged RFCs
- RFC-200 (merged): Dynamic Goal Management (merged into RFC-200)

### External References
- LangGraph Documentation: CompiledStateGraph, RunnableConfig
- deepagents Documentation: SubAgent, CompiledSubAgent, Middlewares
- langchain Documentation: Tools, BaseTool

---

## 11. Glossary

**AgentDecision**: Layer 2's LLM decision specifying steps to execute (hybrid single or batch)

**CoreAgent**: Layer 1 runtime (CompiledStateGraph) built by `create_soothe_agent()`

**GoalDirective**: Layer 3's structured action for goal DAG management

**GoalContext**: Snapshot of all goals for Layer 3 reflection

**JudgeResult**: Layer 2's evaluation of goal progress after execution

**StepAction**: Single step in Layer 2's execution strategy

**Evidence Accumulation**: JUDGE phase evaluation model - collects all step results for goal progress judgment

**Decision Reuse**: Iteration model - reuse AgentDecision until JUDGE indicates replan needed

**Adaptive Granularity**: Step sizing model - LLM decides atomic vs semantic based on goal clarity

**Full Delegation**: Layer 3 → Layer 2 model - PERFORM invokes complete PLAN → ACT → JUDGE loop

**Hybrid Execution**: Layer 2 → Layer 1 model - ACT chooses parallel, sequential, or dependency execution

---

## 12. Appendix: Design Decisions Summary

This design was refined through collaborative discussion with the following key decisions:

1. **Layer 3 → Layer 2 Delegation**: Full Delegation (PERFORM invokes Layer 2's complete loop)
2. **Layer 2 Judgment Model**: Goal-Directed Judgment (evaluate progress toward goal, not plan completion)
3. **AgentDecision Model**: Hybrid Decision (single step or batch, LLM decides)
4. **Step Granularity**: Adaptive Granularity (LLM chooses atomic vs semantic)
5. **JUDGE Evaluation**: Evidence Accumulation Model (holistic evaluation from all step results)
6. **Iteration Flow**: Reuse Existing Decision (continue executing strategy until replan needed)
7. **Layer 1 Integration**: Hybrid Sequential vs Parallel (ACT chooses execution mode)
8. **Layer 1 Foundation**: CoreAgent based on `create_soothe_agent()` (existing implementation)
9. **RFC-200 (merged) Merge**: Merge into RFC-200 (both address Layer 3 goal management)
10. **CoreAgent RFC Scope**: Architecture Documentation (establish Layer 1 foundation, reference other RFCs for details)

Each decision was validated incrementally through the design discussion process.

---

**End of Design Draft**