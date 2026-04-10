# RFC-201 (Layer 2) Implementation Design

**Created**: 2026-03-29
**Status**: Draft
**Purpose**: Fill RFC-201 (Layer 2) implementation gaps with PLAN → ACT → JUDGE architecture

---

## Abstract

This design addresses the major implementation gaps in RFC-201 (Layer 2: Agentic Goal Execution Loop). The current implementation uses an observe → act → verify model that doesn't match the intended PLAN → ACT → JUDGE architecture. We will replace the existing implementation entirely with a fresh `cognition/agent_loop/` module that implements the three-phase loop with AgentDecision (hybrid multi-step), goal-directed judgment (evidence accumulation), and Layer 1 CoreAgent integration.

---

## 1. Current State Analysis

### 1.1 Existing Implementation Gaps

**Current Implementation** (`_runner_agentic.py`):
- Uses observe → act → verify loop
- AgentDecision: Single tool model (not hybrid multi-step)
- Planning: Happens before loop (not iteration-scoped)
- Judgment: Heuristic-based verification (not goal-directed evaluation)
- No decision reuse model
- No explicit Layer 1 CoreAgent integration

**Required by RFC-201**:
- PLAN → ACT → JUDGE loop with goal-directed evaluation
- AgentDecision: Hybrid multi-step model (1 or N steps)
- Iteration-scoped planning (inside loop)
- Evidence accumulation judgment model
- Decision reuse until "replan" or "done"
- Layer 1 CoreAgent integration for step execution

**Gap Severity**: ❌ **Major implementation required** - fundamental redesign

### 1.2 Existing Scaffolding

Current `cognition/agent_loop/` contains partial scaffolding:
- `core/schemas.py`: AgentDecision (single tool), JudgeResult, ToolOutput
- `execution/judge.py`: JudgeEngine stub
- `integration/tool_loop_adapter.py`: Returns "not fully implemented yet"

**Decision**: Replace entirely - create fresh implementation without legacy constraints

---

## 2. Architecture Design

### 2.1 Module Structure

```
cognition/agent_loop/
├── __init__.py              # Public interface (AgentLoop)
├── schemas.py               # AgentDecision, StepAction, JudgeResult, LoopState, StepResult
├── loop_agent.py            # Main loop orchestration (PLAN → ACT → JUDGE)
├── planner.py               # PLAN phase logic
├── executor.py              # ACT phase logic
└── judge.py                 # JUDGE phase logic

protocols/
├── planner.py               # Extended PlannerProtocol with decide_steps()
└── judge.py                 # New JudgeProtocol

core/runner/
├── _runner_agentic.py       # Refactored to use AgentLoop
└── _runner_steps.py         # Step execution (existing, reused)
```

### 2.2 Component Responsibilities

**Schemas (`cognition/agent_loop/schemas.py`)**:
- Data models for Layer 2 loop
- No business logic, pure Pydantic models
- Reusable across modules

**AgentLoop (`cognition/agent_loop/loop_agent.py`)**:
- Main orchestration for PLAN → ACT → JUDGE loop
- Iteration management and decision reuse logic
- State management (LoopState)
- Returns JudgeResult to caller (Layer 3)

**Planner (`cognition/agent_loop/planner.py`)**:
- PLAN phase implementation
- Calls PlannerProtocol.decide_steps()
- Handles decision reuse logic

**Executor (`cognition/agent_loop/executor.py`)**:
- ACT phase implementation
- Executes steps via CoreAgent.astream()
- Hybrid execution modes (parallel, sequential, dependency)
- Error handling (errors become evidence)

**Judge (`cognition/agent_loop/judge.py`)**:
- JUDGE phase implementation
- Calls JudgeProtocol.judge()
- Evidence accumulation

**PlannerProtocol (Extended)**:
- Add decide_steps() method for Layer 2 planning
- Implementations: SimplePlanner, ClaudePlanner

**JudgeProtocol (New)**:
- Protocol for judgment logic
- Implementation: LLMJudgeEngine

**Runner Integration**:
- Create AgentLoop with dependencies
- Call loop_agent.run()
- Return JudgeResult to Layer 3

---

## 3. Core Schemas

### 3.1 AgentDecision (Hybrid Multi-Step Model)

```python
class StepAction(BaseModel):
    """Single step in execution strategy."""

    id: str = Field(default_factory=lambda: str(uuid4())[:8])
    description: str  # What this step does
    tools: list[str] | None = None  # Tools to use (optional)
    subagent: str | None = None  # Subagent to invoke (optional)
    expected_output: str  # Expected result for evidence accumulation
    dependencies: list[str] | None = None  # Step IDs this depends on

class AgentDecision(BaseModel):
    """LLM's decision on next action for goal execution.

    Hybrid model: can specify 1 step or N steps.
    """

    type: Literal["execute_steps", "final"]
    steps: list[StepAction]  # Can be 1 or N steps
    execution_mode: Literal["parallel", "sequential", "dependency"]
    reasoning: str  # Why these steps advance toward goal
    adaptive_granularity: Literal["atomic", "semantic"] | None = None

    @model_validator(mode="after")
    def validate_decision(self) -> AgentDecision:
        if self.type == "execute_steps" and not self.steps:
            raise ValueError("execute_steps requires at least one step")
        return self

    def has_remaining_steps(self, completed_step_ids: set[str]) -> bool:
        """Check if there are steps not yet executed."""
        return any(s.id not in completed_step_ids for s in self.steps)

    def get_ready_steps(self, completed_step_ids: set[str]) -> list[StepAction]:
        """Get steps ready for execution (dependencies satisfied)."""
        ready = []
        for step in self.steps:
            if step.id in completed_step_ids:
                continue
            if step.dependencies and any(d not in completed_step_ids for d in step.dependencies):
                continue
            ready.append(step)
        return ready
```

### 3.2 JudgeResult (Evidence Accumulation Model)

```python
class JudgeResult(BaseModel):
    """LLM's judgment after evaluating goal progress."""

    status: Literal["continue", "replan", "done"]
    evidence_summary: str  # Accumulated from all step results
    goal_progress: float = Field(ge=0.0, le=1.0)  # 0.0-1.0 progress
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)
    reasoning: str  # Why this judgment was made
    next_steps_hint: str | None = None  # Hint for next iteration

    def should_continue(self) -> bool:
        return self.status == "continue"

    def should_replan(self) -> bool:
        return self.status == "replan"

    def is_done(self) -> bool:
        return self.status == "done"
```

### 3.3 StepResult (Execution Result with Error Evidence)

```python
class StepResult(BaseModel):
    """Result from executing a single step."""

    step_id: str
    success: bool
    output: str | None = None
    error: str | None = None
    error_type: Literal["execution", "tool", "timeout", "unknown"] | None = None
    duration_ms: int
    thread_id: str  # Thread used for execution

    def to_evidence_string(self) -> str:
        """Convert to evidence string for judgment."""
        if self.success:
            return f"Step {self.step_id}: ✓ {self.output[:200]}"
        else:
            return f"Step {self.step_id}: ✗ Error: {self.error}"
```

### 3.4 LoopState (Layer 2 State Tracking)

```python
class LoopState(BaseModel):
    """State for Layer 2 agentic loop."""

    goal: str
    thread_id: str
    iteration: int = 0
    max_iterations: int = 8

    # Decision management
    current_decision: AgentDecision | None = None
    completed_step_ids: set[str] = Field(default_factory=set)

    # Judgment history
    previous_judgment: JudgeResult | None = None

    # Execution results
    step_results: list[StepResult] = []

    # Evidence accumulation
    evidence_summary: str = ""

    # Timing
    started_at: datetime = Field(default_factory=datetime.utcnow)
    total_duration_ms: int = 0

    def add_step_result(self, result: StepResult) -> None:
        """Add step result and update completed set."""
        self.step_results.append(result)
        if result.success:
            self.completed_step_ids.add(result.step_id)

    def has_remaining_steps(self) -> bool:
        """Check if current decision has remaining steps."""
        if not self.current_decision:
            return False
        return self.current_decision.has_remaining_steps(self.completed_step_ids)
```

---

## 4. Protocol Extensions

### 4.1 Extended PlannerProtocol

```python
# In protocols/planner.py

class PlannerProtocol(Protocol):
    """Planning protocol for goal decomposition and step decisions."""

    # Existing Layer 3 methods
    async def create_plan(self, goal: str, context: PlanContext) -> Plan: ...
    async def reflect(
        self,
        plan: Plan,
        step_results: list[StepResult],
        goal_context: GoalContext | None = None
    ) -> Reflection: ...
    async def revise_plan(self, plan: Plan, reflection: str) -> Plan: ...

    # New Layer 2 method
    async def decide_steps(
        self,
        goal: str,
        context: PlanContext,
        previous_judgment: JudgeResult | None = None
    ) -> AgentDecision:
        """
        Decide what steps to execute for goal progress.

        Args:
            goal: Goal description
            context: Planning context (available tools, subagents, etc.)
            previous_judgment: Previous judgment (if replanning)

        Returns:
            AgentDecision with steps to execute

        Implementation should:
        - Decide step granularity (atomic vs semantic)
        - Choose execution mode (parallel, sequential, dependency)
        - Specify 1 or N steps based on goal state
        """
        ...
```

### 4.2 New JudgeProtocol

```python
# In protocols/judge.py

class JudgeProtocol(Protocol):
    """Protocol for evaluating goal progress during Layer 2 execution."""

    async def judge(
        self,
        goal: str,
        evidence: list[StepResult],
        steps: list[StepAction]
    ) -> JudgeResult:
        """
        Evaluate progress toward goal completion.

        Args:
            goal: Goal description
            evidence: Results from executed steps (includes errors)
            steps: Steps that were executed

        Returns:
            JudgeResult with status, progress, and reasoning

        Implementation should:
        - Accumulate evidence from all step results
        - Evaluate progress toward goal (0.0-1.0)
        - Decide: done (goal achieved), continue (strategy valid), replan (need new approach)
        - Include error analysis in reasoning
        """
        ...
```

---

## 5. AgentLoop Implementation

### 5.1 Main Orchestration (`loop_agent.py`)

```python
class AgentLoop:
    """Layer 2: Agentic Goal Execution Loop.

    Executes single goals through PLAN → ACT → JUDGE iterations.
    """

    def __init__(
        self,
        core_agent: CompiledStateGraph,
        planner: PlannerProtocol,
        judge: JudgeProtocol,
        config: SootheConfig
    ):
        self.core_agent = core_agent
        self.planner = planner
        self.judge = judge
        self.config = config

        # Phase components
        self.planner_phase = PlannerPhase(planner)
        self.executor = Executor(core_agent)
        self.judge_phase = JudgePhase(judge)

    async def run(
        self,
        goal: str,
        thread_id: str,
        max_iterations: int = 8
    ) -> JudgeResult:
        """
        Run PLAN → ACT → JUDGE loop for goal execution.

        Args:
            goal: Goal description
            thread_id: Thread context
            max_iterations: Maximum loop iterations

        Returns:
            JudgeResult (final status and evidence)
        """
        state = LoopState(
            goal=goal,
            thread_id=thread_id,
            max_iterations=max_iterations
        )

        while state.iteration < state.max_iterations:
            iteration_start = perf_counter()

            # PLAN Phase
            decision = await self.planner_phase.plan(
                goal=goal,
                state=state,
                context=self._build_plan_context()
            )

            # ACT Phase
            step_results = await self.executor.execute(
                decision=decision,
                state=state
            )

            # Update state with results
            for result in step_results:
                state.add_step_result(result)

            # JUDGE Phase
            judgment = await self.judge_phase.judge(
                goal=goal,
                state=state
            )

            state.previous_judgment = judgment
            state.iteration += 1
            state.total_duration_ms += int((perf_counter() - iteration_start) * 1000)

            # Decision logic
            if judgment.is_done():
                return judgment

            elif judgment.should_replan():
                # Next iteration will create new decision
                state.current_decision = None
                state.completed_step_ids.clear()
                continue

            else:  # should_continue()
                # Reuse current decision, execute remaining steps
                state.current_decision = decision
                continue

        # Max iterations reached
        return state.previous_judgment or JudgeResult(
            status="replan",
            evidence_summary=state.evidence_summary,
            goal_progress=0.0,
            confidence=0.0,
            reasoning="Max iterations reached without completion"
        )

    def _build_plan_context(self) -> PlanContext:
        """Build planning context with available capabilities."""
        return PlanContext(
            available_tools=list(self.core_agent.tools.keys()) if hasattr(self.core_agent, 'tools') else [],
            available_subagents=["browser", "claude", "skillify", "weaver"],
            config=self.config
        )
```

### 5.2 PLAN Phase (`planner.py`)

```python
class PlannerPhase:
    """PLAN phase: Decide what steps to execute."""

    def __init__(self, planner: PlannerProtocol):
        self.planner = planner

    async def plan(
        self,
        goal: str,
        state: LoopState,
        context: PlanContext
    ) -> AgentDecision:
        """
        Create or reuse AgentDecision.

        Decision reuse logic:
        - If no existing decision → create new
        - If previous judgment says "replan" → create new
        - If previous judgment says "continue" and has remaining steps → reuse
        """
        # Check if we should reuse existing decision
        if state.current_decision and state.has_remaining_steps():
            if state.previous_judgment and state.previous_judgment.should_continue():
                logger.info("Reusing existing AgentDecision (continue strategy)")
                return state.current_decision

        # Create new decision
        logger.info("Creating new AgentDecision")
        decision = await self.planner.decide_steps(
            goal=goal,
            context=context,
            previous_judgment=state.previous_judgment
        )

        return decision
```

### 5.3 ACT Phase (`executor.py`)

```python
class Executor:
    """ACT phase: Execute steps via Layer 1 CoreAgent."""

    def __init__(self, core_agent: CompiledStateGraph):
        self.core_agent = core_agent

    async def execute(
        self,
        decision: AgentDecision,
        state: LoopState
    ) -> list[StepResult]:
        """
        Execute steps based on execution mode.

        Modes:
        - parallel: Execute all ready steps concurrently
        - sequential: Execute steps one at a time in order
        - dependency: Execute steps respecting dependency DAG
        """
        ready_steps = decision.get_ready_steps(state.completed_step_ids)

        if not ready_steps:
            logger.warning("No ready steps to execute")
            return []

        if decision.execution_mode == "parallel":
            return await self._execute_parallel(ready_steps, state)
        elif decision.execution_mode == "sequential":
            return await self._execute_sequential(ready_steps, state)
        elif decision.execution_mode == "dependency":
            return await self._execute_dependency(decision, state)
        else:
            raise ValueError(f"Unknown execution mode: {decision.execution_mode}")

    async def _execute_parallel(
        self,
        steps: list[StepAction],
        state: LoopState
    ) -> list[StepResult]:
        """Execute steps in parallel with isolated threads."""
        tasks = [
            self._execute_step(step, f"{state.thread_id}__step_{i}")
            for i, step in enumerate(steps)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert exceptions to error results
        step_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                step_results.append(StepResult(
                    step_id=steps[i].id,
                    success=False,
                    error=str(result),
                    error_type="execution",
                    duration_ms=0,
                    thread_id=f"{state.thread_id}__step_{i}"
                ))
            else:
                step_results.append(result)

        return step_results

    async def _execute_sequential(
        self,
        steps: list[StepAction],
        state: LoopState
    ) -> list[StepResult]:
        """Execute steps sequentially in one agent turn."""
        combined_input = self._build_sequential_input(steps)

        start = perf_counter()
        try:
            stream = await self.core_agent.astream(
                input=combined_input,
                config={"configurable": {"thread_id": state.thread_id}}
            )

            # Collect results from stream
            output = await self._collect_stream(stream)

            duration_ms = int((perf_counter() - start) * 1000)

            # Return single result for all steps
            return [StepResult(
                step_id=steps[0].id,  # Primary step
                success=True,
                output=output,
                duration_ms=duration_ms,
                thread_id=state.thread_id
            )]

        except Exception as e:
            duration_ms = int((perf_counter() - start) * 1000)
            logger.error("Sequential execution failed", exc_info=True)

            return [StepResult(
                step_id=steps[0].id,
                success=False,
                error=str(e),
                error_type="execution",
                duration_ms=duration_ms,
                thread_id=state.thread_id
            )]

    async def _execute_step(
        self,
        step: StepAction,
        thread_id: str
    ) -> StepResult:
        """Execute single step through CoreAgent."""
        start = perf_counter()

        try:
            stream = await self.core_agent.astream(
                input=f"Execute: {step.description}",
                config={"configurable": {"thread_id": thread_id}}
            )

            output = await self._collect_stream(stream)
            duration_ms = int((perf_counter() - start) * 1000)

            return StepResult(
                step_id=step.id,
                success=True,
                output=output,
                duration_ms=duration_ms,
                thread_id=thread_id
            )

        except Exception as e:
            duration_ms = int((perf_counter() - start) * 1000)
            logger.error(f"Step {step.id} failed: {e}", exc_info=True)

            return StepResult(
                step_id=step.id,
                success=False,
                error=str(e),
                error_type="execution",
                duration_ms=duration_ms,
                thread_id=thread_id
            )

    async def _collect_stream(self, stream: AsyncIterator) -> str:
        """Collect output from agent stream."""
        chunks = []
        async for chunk in stream:
            if isinstance(chunk, dict) and "content" in chunk:
                chunks.append(chunk["content"])
        return "".join(chunks)

    def _build_sequential_input(self, steps: list[StepAction]) -> str:
        """Build combined input for sequential execution."""
        descriptions = [f"{i+1}. {step.description}" for i, step in enumerate(steps)]
        return f"Execute these steps sequentially:\n" + "\n".join(descriptions)
```

### 5.4 JUDGE Phase (`judge.py`)

```python
class JudgePhase:
    """JUDGE phase: Evaluate goal progress."""

    def __init__(self, judge: JudgeProtocol):
        self.judge = judge

    async def judge(
        self,
        goal: str,
        state: LoopState
    ) -> JudgeResult:
        """
        Evaluate progress toward goal completion.

        Evidence accumulation:
        - Collect all step results (successes and errors)
        - Build evidence summary
        - Call JudgeProtocol to evaluate
        """
        # Build evidence summary
        evidence_lines = [
            result.to_evidence_string()
            for result in state.step_results
        ]
        evidence_summary = "\n".join(evidence_lines)

        # Get executed steps
        steps = state.current_decision.steps if state.current_decision else []

        # Call judge protocol
        judgment = await self.judge.judge(
            goal=goal,
            evidence=state.step_results,
            steps=steps
        )

        # Update state
        state.evidence_summary = evidence_summary

        return judgment
```

---

## 6. Protocol Implementations

### 6.1 SimplePlanner Extension

```python
# In cognition/planning/simple.py

class SimplePlanner:
    """Simple planner implementation."""

    # Existing Layer 3 methods...

    async def decide_steps(
        self,
        goal: str,
        context: PlanContext,
        previous_judgment: JudgeResult | None = None
    ) -> AgentDecision:
        """
        Decide steps using single LLM call.

        Uses structured output to get AgentDecision.
        """
        prompt = self._build_step_decision_prompt(goal, context, previous_judgment)

        response = await self.model.ainvoke(prompt)

        # Parse structured output
        decision = self._parse_agent_decision(response)

        return decision

    def _build_step_decision_prompt(
        self,
        goal: str,
        context: PlanContext,
        previous_judgment: JudgeResult | None
    ) -> str:
        """Build prompt for step decision."""
        parts = [f"Goal: {goal}"]

        if previous_judgment:
            parts.append(f"\nPrevious judgment: {previous_judgment.reasoning}")
            parts.append(f"Progress: {previous_judgment.goal_progress:.0%}")

        parts.append(f"\nAvailable tools: {', '.join(context.available_tools)}")
        parts.append(f"Available subagents: {', '.join(context.available_subagents)}")

        parts.append("\nDecide what steps to execute next:")
        parts.append("- Specify 1 or more steps")
        parts.append("- Choose execution mode (parallel, sequential, dependency)")
        parts.append("- Decide step granularity (atomic for uncertain goals, semantic for clear goals)")

        return "\n".join(parts)
```

### 6.2 LLMJudgeEngine Implementation

```python
# In backends/judgment/llm_judge.py

class LLMJudgeEngine:
    """LLM-based judge implementation."""

    def __init__(self, model: BaseChatModel):
        self.model = model

    async def judge(
        self,
        goal: str,
        evidence: list[StepResult],
        steps: list[StepAction]
    ) -> JudgeResult:
        """
        Evaluate goal progress using LLM.

        Evidence accumulation approach:
        - Present all step results (successes and errors)
        - Ask LLM to evaluate progress toward goal
        - Decide: done, continue, or replan
        """
        # Build evidence summary
        evidence_lines = [result.to_evidence_string() for result in evidence]
        evidence_text = "\n".join(evidence_lines)

        # Build prompt
        prompt = f"""Goal: {goal}

Evidence from execution:
{evidence_text}

Steps executed: {len(steps)}

Evaluate progress toward the goal:
1. What percentage complete is the goal? (0.0-1.0)
2. Is the goal achieved? (done)
3. Is the current strategy still valid? (continue vs replan)
4. What is your confidence in this evaluation? (0.0-1.0)

Consider:
- Successful steps indicate progress
- Failed steps may indicate wrong approach (need replan)
- Partial progress with valid strategy suggests continue
- Goal fully achieved suggests done

Return your evaluation as JSON:
{{
  "status": "continue" | "replan" | "done",
  "goal_progress": 0.0-1.0,
  "confidence": 0.0-1.0,
  "reasoning": "explanation",
  "next_steps_hint": "optional hint for next iteration"
}}
"""

        response = await self.model.ainvoke(prompt)

        # Parse structured output
        judgment = self._parse_judge_result(response)

        return judgment

    def _parse_judge_result(self, response: str) -> JudgeResult:
        """Parse LLM response into JudgeResult."""
        import json

        try:
            data = json.loads(response)
            return JudgeResult(**data)
        except Exception as e:
            logger.error(f"Failed to parse judge result: {e}")
            # Return conservative default
            return JudgeResult(
                status="replan",
                goal_progress=0.0,
                confidence=0.0,
                reasoning="Failed to parse LLM judgment"
            )
```

---

## 7. Runner Integration

### 7.1 Refactored _runner_agentic.py

```python
# In core/runner/_runner_agentic.py

from soothe.cognition.agent_loop import AgentLoop
from soothe.protocols.judge import JudgeProtocol

class AgenticMixin:
    """Layer 2 agentic loop integration."""

    async def _run_agentic_loop(
        self,
        user_input: str,
        *,
        thread_id: str | None = None,
        max_iterations: int = 8,
    ) -> AsyncGenerator[StreamChunk]:
        """
        Run Layer 2: Agentic Goal Execution Loop.

        Implements PLAN → ACT → JUDGE via AgentLoop.

        Args:
            user_input: Goal description
            thread_id: Thread context
            max_iterations: Maximum loop iterations (default: 8)

        Yields:
            StreamChunk events during execution

        Returns:
            JudgeResult (final status)
        """
        from soothe.cognition.agent_loop import AgentLoop
        from soothe.core.event_catalog import (
            AgenticLoopStartedEvent,
            AgenticLoopCompletedEvent,
            AgenticIterationCompletedEvent,
        )

        tid = thread_id or self._current_thread_id or ""

        # Create judge instance
        judge = self._create_judge()

        # Create AgentLoop
        loop_agent = AgentLoop(
            core_agent=self.agent,
            planner=self._planner,
            judge=judge,
            config=self.config
        )

        # Emit loop started
        yield _custom(
            AgenticLoopStartedEvent(
                thread_id=tid,
                goal=user_input[:100],
                max_iterations=max_iterations
            ).to_dict()
        )

        # Run loop
        judge_result = await loop_agent.run(
            goal=user_input,
            thread_id=tid,
            max_iterations=max_iterations
        )

        # Emit loop completed
        yield _custom(
            AgenticLoopCompletedEvent(
                thread_id=tid,
                status=judge_result.status,
                goal_progress=judge_result.goal_progress,
                evidence_summary=judge_result.evidence_summary[:500]
            ).to_dict()
        )

        return judge_result

    def _create_judge(self) -> JudgeProtocol:
        """Create judge instance from config."""
        from soothe.backends.judgment.llm_judge import LLMJudgeEngine

        model = self.config.create_chat_model("fast")
        return LLMJudgeEngine(model)
```

---

## 8. Error Handling Strategy

### 8.1 Error Evidence Model

**Principle**: Errors become evidence for JUDGE phase to evaluate.

**Implementation**:
1. Step execution catches exceptions
2. Creates StepResult with success=False and error details
3. Error becomes part of evidence for judgment
4. LLM decides if error is fatal or recoverable

**Example Flow**:
```
ACT Phase:
  Step 1: Success ✓ → StepResult(success=True, output="...")
  Step 2: Exception ✗ → StepResult(success=False, error="API timeout", error_type="timeout")
  Step 3: Success ✓ → StepResult(success=True, output="...")

JUDGE Phase:
  Evidence: "Step 1: ✓ ..., Step 2: ✗ Error: API timeout, Step 3: ✓ ..."

  LLM Evaluation:
  - "Step 2 failed due to transient timeout"
  - "Steps 1 and 3 succeeded"
  - "Progress: 66% (2/3 steps)"
  - "Strategy still valid, retry step 2"
  - Decision: continue (with retry hint)

Result: JudgeResult(status="continue", goal_progress=0.66, reasoning="...")
```

### 8.2 Error Types

```python
class StepResult(BaseModel):
    error_type: Literal["execution", "tool", "timeout", "policy", "unknown"] | None
```

- `execution`: General execution error
- `tool`: Tool-specific error
- `timeout`: Execution timeout
- `policy`: Policy violation
- `unknown`: Unclassified error

---

## 9. Event System

### 9.1 New Event Taxonomy

**Loop Lifecycle**:
- `soothe.agentic.loop.started`
- `soothe.agentic.loop.completed`

**Iteration Events**:
- `soothe.agentic.iteration.started`
- `soothe.agentic.iteration.completed`

**Phase Events**:
- `soothe.agentic.plan.decision_created`
- `soothe.agentic.plan.decision_reused`
- `soothe.agentic.act.execution_started`
- `soothe.agentic.act.step_completed`
- `soothe.agentic.act.step_failed`
- `soothe.agentic.judge.completed`

**Breaking Change**: Old observe/act/verify events deprecated

---

## 10. Implementation Plan

### Phase 1: Create Schemas (Week 1, Days 1-2)

**Tasks**:
1. Delete old `cognition/agent_loop/` directory
2. Create new `cognition/agent_loop/schemas.py`
3. Implement AgentDecision, StepAction, JudgeResult, LoopState, StepResult
4. Write unit tests for schemas
5. Add validation logic

**Deliverables**:
- ✅ Fresh `cognition/agent_loop/schemas.py`
- ✅ Unit tests passing
- ✅ Schemas validated against RFC-201 spec

### Phase 2: Extend Protocols (Week 1, Days 3-4)

**Tasks**:
1. Add `decide_steps()` to PlannerProtocol in `protocols/planner.py`
2. Create JudgeProtocol in `protocols/judge.py`
3. Update SimplePlanner to implement decide_steps()
4. Create LLMJudgeEngine implementation
5. Update config to wire judge protocol

**Deliverables**:
- ✅ Extended PlannerProtocol
- ✅ New JudgeProtocol
- ✅ SimplePlanner with decide_steps()
- ✅ LLMJudgeEngine implementation
- ✅ Configuration support

### Phase 3: Implement AgentLoop (Week 1-2, Days 5-8)

**Tasks**:
1. Implement `planner.py` - PLAN phase with decision reuse
2. Implement `executor.py` - ACT phase with CoreAgent integration
3. Implement `judge.py` - JUDGE phase with evidence accumulation
4. Implement `loop_agent.py` - main orchestration
5. Write unit tests for each component
6. Test decision reuse logic
7. Test error handling (errors → evidence)

**Deliverables**:
- ✅ Complete AgentLoop implementation
- ✅ PLAN phase working
- ✅ ACT phase with parallel/sequential/dependency modes
- ✅ JUDGE phase with evidence accumulation
- ✅ Unit tests passing
- ✅ Error handling tested

### Phase 4: Runner Integration (Week 2, Days 9-10)

**Tasks**:
1. Refactor `_runner_agentic.py` to use AgentLoop
2. Remove observe/act/verify methods
3. Update event emission for new taxonomy
4. Wire judge protocol creation
5. Write integration tests
6. Test Layer 3 integration (PERFORM delegation)

**Deliverables**:
- ✅ Refactored runner using AgentLoop
- ✅ Old observe/act/verify removed
- ✅ New event system working
- ✅ Integration tests passing
- ✅ Layer 3 integration tested

### Phase 5: Testing & Documentation (Week 2, Days 11-12)

**Tasks**:
1. Comprehensive unit tests (schemas, protocols, AgentLoop)
2. Integration tests (full loop, error scenarios)
3. Performance tests (parallel vs sequential)
4. Update documentation
5. Create migration guide (for users)
6. Run full test suite

**Deliverables**:
- ✅ Test coverage >90%
- ✅ All tests passing
- ✅ Documentation updated
- ✅ Migration guide created
- ✅ Ready for production

---

## 11. Testing Strategy

### 11.1 Unit Tests

**Schemas**:
- AgentDecision validation (1 step, N steps, invalid)
- StepAction dependency resolution
- JudgeResult status methods
- LoopState step tracking
- StepResult evidence strings

**Planner Phase**:
- Decision creation (new decision)
- Decision reuse (continue strategy)
- Decision replan (replan trigger)
- PlanContext building

**Executor**:
- Parallel execution (isolated threads)
- Sequential execution (combined input)
- Dependency execution (DAG resolution)
- Error handling (exception → StepResult)

**Judge Phase**:
- Evidence accumulation
- Error analysis
- Progress evaluation
- Status decision (done/continue/replan)

**AgentLoop**:
- Full loop orchestration
- Iteration management
- Max iterations handling
- State transitions

### 11.2 Integration Tests

**End-to-End Loop**:
- Simple goal (1-2 iterations)
- Complex goal (multiple iterations)
- Replan scenario (strategy fails)
- Continue scenario (strategy valid)
- Done scenario (goal achieved)

**Error Scenarios**:
- Step execution error → judgment handles
- Multiple step failures → LLM evaluates
- Transient error → retry decision
- Fatal error → replan decision

**Layer 3 Integration**:
- PERFORM calls Layer 2
- JudgeResult returned to Layer 3
- Evidence used for REFLECT

**Performance**:
- Parallel vs sequential comparison
- Dependency DAG execution efficiency
- Thread isolation verification

---

## 12. Configuration

### 12.1 Judge Configuration

```yaml
# In config.yml
judgment:
  provider: llm  # llm | rule_based | hybrid
  model_role: fast  # Model to use for judgment
  evidence_threshold: 0.7  # Minimum confidence for "done"
  max_step_errors: 3  # Max errors before forced replan
```

### 12.2 Loop Configuration

```yaml
# In config.yml
agentic:
  max_iterations: 8
  planning:
    adaptive_granularity: true
    default_mode: sequential  # parallel | sequential | dependency
  execution:
    timeout_ms: 30000  # Per-step timeout
    max_parallel_steps: 5
```

---

## 13. Migration Guide (For Users)

### Breaking Changes

1. **Event Names Changed**:
   - Old: `soothe.agentic.observation.*`, `soothe.agentic.verification.*`
   - New: `soothe.agentic.plan.*`, `soothe.agentic.act.*`, `soothe.agentic.judge.*`

2. **API Signature**:
   - `_run_agentic_loop()` now returns `JudgeResult` (not just streams)
   - Different internal behavior (PLAN → ACT → JUDGE)

3. **Configuration**:
   - New `judgment` section in config
   - Updated `agentic` configuration structure

### Migration Steps

1. **Update Event Handlers**: Replace old event names with new taxonomy
2. **Handle JudgeResult**: Process returned JudgeResult from loop
3. **Update Config**: Add `judgment` section, update `agentic` settings
4. **Test Integration**: Verify Layer 3 integration still works

---

## 14. Success Criteria

### Functional Requirements

✅ PLAN phase creates AgentDecision with steps (hybrid 1 or N)
✅ PLAN phase supports decision reuse (continue vs replan)
✅ ACT phase executes steps via CoreAgent (parallel, sequential, dependency modes)
✅ ACT phase handles errors → StepResult with error details
✅ JUDGE phase evaluates goal progress (evidence accumulation)
✅ JUDGE phase returns JudgeResult with status/progress/confidence
✅ AgentLoop orchestrates full PLAN → ACT → JUDGE loop
✅ Iteration management works (max iterations, decision reuse)
✅ State management via LoopState (tracks decisions, judgments, steps)
✅ Error handling: errors become evidence for judgment
✅ Integration with Layer 3 (PERFORM delegation returns JudgeResult)
✅ Integration with Layer 1 (ACT calls CoreAgent.astream())

### Non-Functional Requirements

✅ Test coverage >90%
✅ All unit tests passing
✅ All integration tests passing
✅ Performance: parallel execution faster than sequential
✅ No breaking changes to Layer 3 external API
✅ Clean architecture: no legacy code remnants
✅ Documentation updated
✅ Migration guide provided

### Implementation Quality

✅ Clean module structure (schemas, loop_agent, protocols, runner)
✅ Single responsibility: each component has one job
✅ Testability: components testable in isolation
✅ Extensibility: protocols allow alternative implementations
✅ Observability: comprehensive event emission
✅ Error resilience: graceful degradation via evidence model

---

## 15. Risks and Mitigations

### Risk 1: LLM Judge Quality

**Risk**: LLM may make poor judgments about goal progress.

**Mitigation**:
- Use structured output with clear evaluation criteria
- Include confidence scores
- Add validation rules (e.g., goal_progress must be >0.9 for "done")
- Fallback to heuristics if LLM judgment unclear

### Risk 2: Decision Reuse Complexity

**Risk**: Decision reuse logic may be error-prone.

**Mitigation**:
- Clear state tracking (completed_step_ids)
- Explicit validation: has_remaining_steps()
- Comprehensive unit tests for reuse scenarios
- Logging for debugging

### Risk 3: Error Handling Ambiguity

**Risk**: LLM may misinterpret error severity.

**Mitigation**:
- Categorize error types (timeout, execution, policy)
- Include error context in evidence
- Provide guidance in judge prompt
- Add safety rules (e.g., "3 consecutive errors → forced replan")

### Risk 4: Performance Overhead

**Risk**: New architecture may be slower than old.

**Mitigation**:
- Parallel execution for independent steps
- Lazy evaluation where possible
- Caching of plan context
- Performance benchmarks during development

---

## 16. Related Documents

- [RFC-201](./RFC-201-agentic-goal-execution-loop.md) - Layer 2 Specification
- [RFC-200](./RFC-200-autonomous-goal-management-loop.md) - Layer 3 Specification
- [RFC-100](./RFC-100-coreagent-runtime.md) - Layer 1 Specification
- [RFC-000](./RFC-000-system-conceptual-design.md) - System Conceptual Design
- [RFC-001](./RFC-001-core-modules-architecture.md) - Core Modules Architecture

---

## 17. Glossary

**AgentDecision**: Layer 2's LLM decision specifying steps to execute (hybrid single or batch)

**StepAction**: Single step specification with description, tools/subagents, expected output

**JudgeResult**: Layer 2's evaluation of goal progress after execution (status, evidence, progress)

**LoopState**: Layer 2's state tracking for PLAN → ACT → JUDGE loop

**StepResult**: Result from executing a single step (success/error evidence)

**Evidence Accumulation**: Judgment model that collects all step results for goal progress evaluation

**Decision Reuse**: Iteration pattern where AgentDecision is reused until replan needed

**Error Evidence**: Model where step execution errors become evidence for judgment

**Adaptive Granularity**: Step sizing where LLM chooses atomic vs semantic based on goal clarity

---

## 18. Changelog

### 2026-03-29
- Initial design draft
- Complete architecture for RFC-201 implementation
- Defined schemas, protocols, AgentLoop, runner integration
- Specified error handling, testing, and migration strategies