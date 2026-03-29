# IG-097: RFC-0008 (Layer 2) Implementation - LoopAgent System

**Implementation Guide**: IG-097
**RFC**: RFC-0008 - Layer 2: Agentic Goal Execution Loop
**Status**: In Progress
**Created**: 2026-03-29
**Related**: RFC-0007, RFC-0023, RFC-0001, RFC-0002

## Overview

This implementation guide addresses the major gaps in RFC-0008 (Layer 2: Agentic Goal Execution Loop). The current implementation uses an observe → act → verify model that doesn't match the intended PLAN → ACT → JUDGE architecture defined in the revised RFC-0008.

### Objectives

1. **Replace observe → act → verify with PLAN → ACT → JUDGE** loop
2. **Implement AgentDecision** with hybrid multi-step model (1 or N steps)
3. **Implement goal-directed judgment** with evidence accumulation
4. **Integrate with Layer 1 CoreAgent** for step execution
5. **Create LoopAgent** as self-contained Layer 2 component
6. **Remove all old scaffolding** and create fresh implementation

### Breaking Changes

This implementation will make breaking changes:
- API signatures changed (no backward compatibility)
- Event names changed (new PLAN/ACT/JUDGE taxonomy)
- Old `cognition/loop_agent/` deleted entirely
- New fresh `cognition/loop_agent/` created

## Architecture Summary

### Component Structure

```
cognition/loop_agent/
├── __init__.py              # Public interface
├── schemas.py               # AgentDecision, StepAction, JudgeResult, LoopState, StepResult
├── loop_agent.py            # Main loop orchestration
├── planner.py               # PLAN phase logic
├── executor.py              # ACT phase logic
└── judge.py                 # JUDGE phase logic

protocols/
├── planner.py               # Extended PlannerProtocol with decide_steps()
└── judge.py                 # New JudgeProtocol

backends/judgment/
└── llm_judge.py             # LLMJudgeEngine implementation

core/runner/
└── _runner_agentic.py       # Refactored to use LoopAgent
```

### Loop Flow

```
LoopAgent.run(goal, thread_id, max_iterations)
    |
    v
while iteration < max_iterations:
    |
    +-- PLAN: Create or reuse AgentDecision
    +-- ACT: Execute steps via CoreAgent (parallel/sequential/dependency)
    +-- JUDGE: Evaluate goal progress (evidence accumulation)
    |
    +-- Decision:
           ├─ "done": Goal achieved, return JudgeResult
           ├─ "replan": Create new AgentDecision, next iteration
           └─ "continue": Reuse AgentDecision, execute remaining steps
```

## Implementation Phases

### Phase 1: Create Schemas (Days 1-2)

**Objective**: Implement all Layer 2 data models

**Tasks**:
1. Delete old `cognition/loop_agent/` directory
2. Create new `cognition/loop_agent/schemas.py`
3. Implement schemas:
   - `StepAction` - single step specification
   - `AgentDecision` - hybrid multi-step decision
   - `JudgeResult` - goal progress evaluation
   - `StepResult` - step execution result with error evidence
   - `LoopState` - Layer 2 state tracking
4. Add validation logic
5. Write unit tests

**Success Criteria**:
- ✅ All schemas implemented
- ✅ Validation working
- ✅ Unit tests passing

### Phase 2: Extend Protocols (Days 3-4)

**Objective**: Add Layer 2 methods to protocols

**Tasks**:
1. Extend `PlannerProtocol` with `decide_steps()` method
2. Create `JudgeProtocol` in `protocols/judge.py`
3. Update `SimplePlanner` to implement `decide_steps()`
4. Create `LLMJudgeEngine` implementation
5. Add protocol wiring to config

**Success Criteria**:
- ✅ Extended PlannerProtocol
- ✅ New JudgeProtocol
- ✅ SimplePlanner updated
- ✅ LLMJudgeEngine implemented
- ✅ Config integration working

### Phase 3: Implement LoopAgent (Days 5-8)

**Objective**: Create complete LoopAgent system

**Tasks**:
1. Implement `planner.py` - PLAN phase with decision reuse
2. Implement `executor.py` - ACT phase with CoreAgent integration
3. Implement `judge.py` - JUDGE phase with evidence accumulation
4. Implement `loop_agent.py` - main orchestration
5. Test each component individually
6. Test integrated loop

**Success Criteria**:
- ✅ PLAN phase working (create/reuse decisions)
- ✅ ACT phase working (parallel/sequential/dependency execution)
- ✅ JUDGE phase working (evidence accumulation)
- ✅ LoopAgent orchestration complete
- ✅ Decision reuse logic working
- ✅ Error handling (errors → evidence)

### Phase 4: Runner Integration (Days 9-10)

**Objective**: Integrate LoopAgent with runner

**Tasks**:
1. Refactor `_runner_agentic.py` to use LoopAgent
2. Remove old observe/act/verify methods
3. Update event emission
4. Wire judge protocol creation
5. Test Layer 3 integration
6. Test end-to-end flow

**Success Criteria**:
- ✅ Runner uses LoopAgent
- ✅ Old observe/act/verify removed
- ✅ New event system working
- ✅ Layer 3 integration tested

### Phase 5: Testing & Documentation (Days 11-12)

**Objective**: Comprehensive testing and documentation

**Tasks**:
1. Write comprehensive unit tests
2. Write integration tests
3. Test error scenarios
4. Performance testing
5. Update documentation
6. Create migration guide

**Success Criteria**:
- ✅ Test coverage >90%
- ✅ All tests passing
- ✅ Documentation updated
- ✅ Migration guide created

## Detailed Implementation

### 1. Schemas Implementation

**File**: `src/soothe/cognition/loop_agent/schemas.py`

Key schemas to implement:

```python
from pydantic import BaseModel, Field, model_validator
from typing import Any, Literal
from datetime import datetime
import uuid

class StepAction(BaseModel):
    """Single step in execution strategy."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    description: str
    tools: list[str] | None = None
    subagent: str | None = None
    expected_output: str
    dependencies: list[str] | None = None

class AgentDecision(BaseModel):
    """LLM's decision on next action for goal execution."""
    type: Literal["execute_steps", "final"]
    steps: list[StepAction]
    execution_mode: Literal["parallel", "sequential", "dependency"]
    reasoning: str
    adaptive_granularity: Literal["atomic", "semantic"] | None = None

    @model_validator(mode="after")
    def validate_decision(self) -> "AgentDecision":
        if self.type == "execute_steps" and not self.steps:
            raise ValueError("execute_steps requires at least one step")
        return self

    def has_remaining_steps(self, completed_step_ids: set[str]) -> bool:
        return any(s.id not in completed_step_ids for s in self.steps)

    def get_ready_steps(self, completed_step_ids: set[str]) -> list[StepAction]:
        ready = []
        for step in self.steps:
            if step.id in completed_step_ids:
                continue
            if step.dependencies and any(d not in completed_step_ids for d in step.dependencies):
                continue
            ready.append(step)
        return ready

class JudgeResult(BaseModel):
    """LLM's judgment after evaluating goal progress."""
    status: Literal["continue", "replan", "done"]
    evidence_summary: str
    goal_progress: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)
    reasoning: str
    next_steps_hint: str | None = None

    def should_continue(self) -> bool:
        return self.status == "continue"

    def should_replan(self) -> bool:
        return self.status == "replan"

    def is_done(self) -> bool:
        return self.status == "done"

class StepResult(BaseModel):
    """Result from executing a single step."""
    step_id: str
    success: bool
    output: str | None = None
    error: str | None = None
    error_type: Literal["execution", "tool", "timeout", "policy", "unknown"] | None = None
    duration_ms: int
    thread_id: str

    def to_evidence_string(self) -> str:
        if self.success:
            return f"Step {self.step_id}: ✓ {self.output[:200]}"
        else:
            return f"Step {self.step_id}: ✗ Error: {self.error}"

class LoopState(BaseModel):
    """State for Layer 2 agentic loop."""
    goal: str
    thread_id: str
    iteration: int = 0
    max_iterations: int = 8

    current_decision: AgentDecision | None = None
    completed_step_ids: set[str] = Field(default_factory=set)
    previous_judgment: JudgeResult | None = None
    step_results: list[StepResult] = []
    evidence_summary: str = ""

    started_at: datetime = Field(default_factory=datetime.utcnow)
    total_duration_ms: int = 0

    def add_step_result(self, result: StepResult) -> None:
        self.step_results.append(result)
        if result.success:
            self.completed_step_ids.add(result.step_id)

    def has_remaining_steps(self) -> bool:
        if not self.current_decision:
            return False
        return self.current_decision.has_remaining_steps(self.completed_step_ids)
```

### 2. Protocol Extensions

**File**: `src/soothe/protocols/planner.py`

Add to existing PlannerProtocol:

```python
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
    """
    ...
```

**File**: `src/soothe/protocols/judge.py` (NEW)

```python
from typing import Protocol
from soothe.cognition.loop_agent.schemas import JudgeResult, StepResult, StepAction

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
            evidence: Results from executed steps
            steps: Steps that were executed

        Returns:
            JudgeResult with status, progress, and reasoning
        """
        ...
```

### 3. LoopAgent Implementation

**File**: `src/soothe/cognition/loop_agent/loop_agent.py`

Main orchestration class - see design draft for full implementation.

Key methods:
- `run()` - Main loop
- `_plan_phase()` - PLAN phase
- `_act_phase()` - ACT phase
- `_judge_phase()` - JUDGE phase

**File**: `src/soothe/cognition/loop_agent/planner.py`

PLAN phase implementation - handles decision creation and reuse.

**File**: `src/soothe/cognition/loop_agent/executor.py`

ACT phase implementation - executes steps via CoreAgent with parallel/sequential/dependency modes.

**File**: `src/soothe/cognition/loop_agent/judge.py`

JUDGE phase implementation - calls JudgeProtocol and accumulates evidence.

### 4. Judge Implementation

**File**: `src/soothe/backends/judgment/llm_judge.py`

```python
from langchain_core.language_models import BaseChatModel
from soothe.protocols.judge import JudgeProtocol
from soothe.cognition.loop_agent.schemas import JudgeResult, StepResult, StepAction

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
        """Evaluate goal progress using LLM."""
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

Return JSON:
{{
  "status": "continue" | "replan" | "done",
  "goal_progress": 0.0-1.0,
  "confidence": 0.0-1.0,
  "reasoning": "explanation",
  "next_steps_hint": "optional hint"
}}
"""

        response = await self.model.ainvoke(prompt)
        return self._parse_judge_result(response)

    def _parse_judge_result(self, response: str) -> JudgeResult:
        """Parse LLM response into JudgeResult."""
        import json

        try:
            data = json.loads(response)
            return JudgeResult(**data)
        except Exception as e:
            logger.error(f"Failed to parse judge result: {e}")
            return JudgeResult(
                status="replan",
                goal_progress=0.0,
                confidence=0.0,
                reasoning="Failed to parse LLM judgment"
            )
```

### 5. Runner Integration

**File**: `src/soothe/core/runner/_runner_agentic.py`

Refactor to use LoopAgent:

```python
from soothe.cognition.loop_agent import LoopAgent
from soothe.backends.judgment.llm_judge import LLMJudgeEngine

class AgenticMixin:
    """Layer 2 agentic loop integration."""

    async def _run_agentic_loop(
        self,
        user_input: str,
        *,
        thread_id: str | None = None,
        max_iterations: int = 8,
    ):
        """Run Layer 2: Agentic Goal Execution Loop."""
        # Create judge
        judge = LLMJudgeEngine(self.config.create_chat_model("fast"))

        # Create LoopAgent
        loop_agent = LoopAgent(
            core_agent=self.agent,
            planner=self._planner,
            judge=judge,
            config=self.config
        )

        # Run loop
        judge_result = await loop_agent.run(
            goal=user_input,
            thread_id=thread_id or self._current_thread_id,
            max_iterations=max_iterations
        )

        return judge_result
```

## Testing Strategy

### Unit Tests

**File**: `tests/unit/test_loop_agent_schemas.py`
- Test all schema validation
- Test StepAction dependency resolution
- Test AgentDecision step management
- Test JudgeResult status methods
- Test LoopState step tracking

**File**: `tests/unit/test_planner_phase.py`
- Test decision creation
- Test decision reuse logic
- Test replan trigger

**File**: `tests/unit/test_executor.py`
- Test parallel execution
- Test sequential execution
- Test dependency execution
- Test error handling (errors → StepResult)

**File**: `tests/unit/test_judge_phase.py`
- Test evidence accumulation
- Test error analysis
- Test progress evaluation

### Integration Tests

**File**: `tests/integration/test_loop_agent.py`
- Test full PLAN → ACT → JUDGE loop
- Test iteration management
- Test decision reuse flow
- Test replan flow
- Test error scenarios

**File**: `tests/integration/test_layer_integration.py`
- Test Layer 3 → Layer 2 delegation
- Test Layer 2 → Layer 1 execution
- Test JudgeResult return to Layer 3

## Configuration Updates

**File**: `config/config.yml`

Add new sections:

```yaml
judgment:
  provider: llm
  model_role: fast
  evidence_threshold: 0.7
  max_step_errors: 3

agentic:
  max_iterations: 8
  planning:
    adaptive_granularity: true
    default_mode: sequential
  execution:
    timeout_ms: 30000
    max_parallel_steps: 5
```

## Migration Notes

### Breaking Changes for Users

1. Event names changed (observe/act/verify → plan/act/judge)
2. `_run_agentic_loop()` now returns JudgeResult
3. New configuration structure

### Migration Steps

1. Update event handlers for new taxonomy
2. Process JudgeResult from loop
3. Add `judgment` section to config
4. Test Layer 3 integration

## Success Metrics

✅ PLAN → ACT → JUDGE loop fully implemented
✅ AgentDecision supports hybrid multi-step model
✅ Goal-directed judgment with evidence accumulation working
✅ Layer 1 CoreAgent integration complete
✅ All unit tests passing (>90% coverage)
✅ All integration tests passing
✅ Layer 3 integration tested
✅ Documentation updated
✅ Migration guide provided

## Timeline

- **Days 1-2**: Schemas implementation
- **Days 3-4**: Protocol extensions
- **Days 5-8**: LoopAgent implementation
- **Days 9-10**: Runner integration
- **Days 11-12**: Testing & documentation

**Total**: 12 days (2 weeks)

## Related Documents

- [RFC-0008](../specs/RFC-0008-agentic-goal-execution-loop.md) - Layer 2 Specification
- [RFC-0007](../specs/RFC-0007-autonomous-goal-management-loop.md) - Layer 3 Specification
- [RFC-0023](../specs/RFC-0023-coreagent-runtime.md) - Layer 1 Specification
- [Design Draft](../drafts/2026-03-29-rfc-0008-layer2-implementation-design.md) - Implementation Design

## Changelog

### 2026-03-29
- Initial implementation guide created
- 5-phase implementation plan defined
- Architecture and components specified