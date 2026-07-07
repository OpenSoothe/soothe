# IG-154: Layer 3 AgentLoop Integration Refactoring

**ID**: IG-154
**Title**: Layer 3 AgentLoop Integration Refactoring
**Status**: Draft
**Created**: 2026-04-12
**RFC References**: RFC-200 (Layer 3), RFC-200 (Layer 2)
**Priority**: P0 (Critical Architecture Fix)
**Estimated Effort**: 3-4 days

---

## Abstract

This guide refactors Layer 3 autonomous goal execution to properly delegate to Layer 2's AgentLoop, fixing the architectural boundary violation where Layer 3 bypasses Layer 2 and directly manages step execution. After this refactoring, Layer 3 will invoke `AgentLoop.run()` for single-goal execution, receive `PlanResult` for reflection, and maintain clean layer separation.

---

## Problem Statement

### Current Architecture Violation

**RFC-200 specifies**:
```
Layer 3 PERFORM → Layer 2 AgentLoop.run() → Layer 1 CoreAgent.astream()
```

**Current implementation** (`_runner_autonomous.py:360-366`):
```python
# Layer 3 bypasses Layer 2!
if iter_state.plan and len(iter_state.plan.steps) > 1:
    async for chunk in self._run_step_loop(current_input, iter_state, iter_state.plan, goal_id=goal.id):
        yield chunk  # Direct step loop, no AgentLoop
else:
    async with self._concurrency.acquire_llm_call():
        async for chunk in self._stream_phase(current_input, iter_state):
            yield chunk  # Direct CoreAgent stream
```

### Impact

1. **Architectural Boundary Violation**: Layer 3 performs Layer 2's job
2. **Missing Iterative Refinement**: No Plan → Execute loop per goal
3. **Duplicate Logic**: Step scheduling exists in both layers
4. **No PlanResult Flow**: Layer 3 cannot use Layer 2's judgment and evidence

---

## Solution Design

### Target Architecture

```
User Input (Autonomous)
  → Layer 3 GoalEngine.create_goal()
  → while goals not complete:
      ready_goals = GoalEngine.ready_goals()
      for each goal (PERFORM stage):
        ✅ Delegate to Layer 2 AgentLoop.run(goal.description, thread_id)
        ✅ Receive PlanResult with status, evidence, goal_progress
      REFLECT stage:
        ✅ Use PlanResult for goal-level reflection
        ✅ Generate GoalDirectives for DAG restructuring
```

### Integration Contract

**Layer 3 provides to Layer 2**:
- `goal.description`: Goal text
- `thread_id`: `{parent_tid}__goal_{goal.id}` for isolated execution
- `workspace`: Thread-specific workspace path
- `max_iterations`: Goal-specific iteration budget (default: 8)

**Layer 2 returns to Layer 3**:
- `PlanResult.status`: "done" | "continue" | "replan"
- `PlanResult.evidence_summary`: Accumulated evidence
- `PlanResult.goal_progress`: Progress percentage (0.0-1.0)
- `PlanResult.confidence`: Confidence level
- `PlanResult.full_output`: Final answer (when done)

---

## Implementation Steps

### Step 1: Import AgentLoop in Autonomous Runner

**File**: `src/soothe/core/runner/_runner_autonomous.py`

**Changes**:
```python
# Add import at top (Line 14)
from soothe.cognition.agent_loop import AgentLoop
from soothe.cognition.agent_loop.schemas import PlanResult
```

### Step 2: Create AgentLoop Instance per Goal

**File**: `src/soothe/core/runner/_runner_autonomous.py`

**Location**: Inside `_execute_autonomous_goal()` method (before Line 360)

**Add**:
```python
async def _execute_autonomous_goal(
    self,
    goal: Any,
    *,
    parent_state: Any,
    thread_id: str,
    user_input: str,
    iteration_records: list[Any],
    total_iterations: int,
    parallel_goals: int = 1,
) -> AsyncGenerator[StreamChunk]:
    """Execute a single goal through Layer 2 AgentLoop (RFC-200 §PERFORM)."""
    
    # ... existing setup code ...
    
    # ✅ NEW: Create AgentLoop for this goal
    if self._planner and hasattr(self._planner, 'plan'):
        # Planner implements LoopPlannerProtocol
        loop_planner = self._planner
        
        agent_loop = AgentLoop(
            core_agent=self._agent,
            loop_planner=loop_planner,
            config=self._config,
        )
        
        logger.info(
            "[Layer3] Delegating goal %s to AgentLoop (thread=%s, max_iter=8)",
            goal.id,
            thread_id,
        )
        
        # ✅ Delegate to Layer 2
        plan_result = await agent_loop.run(
            goal=goal.description,
            thread_id=thread_id,
            max_iterations=8,  # Layer 2 iteration budget
        )
        
        # ✅ Process PlanResult
        yield _custom(
            GoalReportEvent(
                goal_id=goal.id,
                step_count=len(plan_result.decision.steps) if plan_result.decision else 0,
                completed=len([s for s in plan_result.decision.steps if s.id in plan_result.status]),
                failed=0,
                summary=plan_result.evidence_summary[:200],
            ).to_dict()
        )
        
        # ✅ Store result for Layer 3 reflection
        goal_result = GoalResult(
            goal_id=goal.id,
            status="completed" if plan_result.is_done() else "failed",
            evidence_summary=plan_result.evidence_summary,
            goal_progress=plan_result.goal_progress,
            confidence=plan_result.confidence,
            full_output=plan_result.full_output,
        )
        
        # Update goal report
        goal.report = GoalReport(
            goal_id=goal.id,
            description=goal.description,
            summary=plan_result.full_output or plan_result.evidence_summary,
            status="completed" if plan_result.is_done() else "failed",
        )
        
        # Complete or fail goal based on PlanResult
        if plan_result.is_done():
            await self._goal_engine.complete_goal(goal.id)
            yield _custom(GoalCompletedEvent(goal_id=goal.id).to_dict())
        else:
            await self._goal_engine.fail_goal(goal.id, error="Layer 2 did not achieve goal")
            yield _custom(GoalFailedEvent(goal_id=goal.id, error="Not achieved", retry_count=goal.retry_count).to_dict())
        
        # ✅ Return early - Layer 2 handled everything
        return
    else:
        # Fallback: No planner, use direct execution (existing code path)
        # Keep existing _run_step_loop and _stream_phase for backward compatibility
        if iter_state.plan and len(iter_state.plan.steps) > 1:
            async for chunk in self._run_step_loop(...):
                yield chunk
        else:
            async with self._concurrency.acquire_llm_call():
                async for chunk in self._stream_phase(...):
                    yield chunk
```

### Step 3: Create GoalResult Model

**File**: `src/soothe/core/runner/_types.py`

**Add**:
```python
class GoalResult(BaseModel):
    """Result from Layer 2 goal execution (RFC-200 integration)."""
    
    goal_id: str
    status: Literal["completed", "failed", "in_progress"]
    evidence_summary: str
    goal_progress: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    full_output: str | None = None
    iteration_count: int = 0
    duration_ms: int = 0
```

### Step 4: Modify Reflection to Use GoalResult

**File**: `src/soothe/core/runner/_runner_autonomous.py`

**Location**: Replace existing reflection logic (Lines 384-465)

**Changes**:
```python
# Build goal context for reflection with Layer 2 results
reflection_context = GoalContext(
    current_goal_id=goal.id,
    all_goals=[GoalSnapshot(...) for g in self._goal_engine.list_goals()],
    completed_goals=self._goal_engine.list_goals(status="completed"),
    failed_goals=self._goal_engine.list_goals(status="failed"),
    ready_goals=[g.id for g in ready_goals],
    max_parallel_goals=self._config.execution.concurrency.max_parallel_goals,
)

# ✅ Pass Layer 2 result to reflection
reflection = await self._planner.reflect(
    plan=iter_state.plan,
    step_results=[],  # Empty - Layer 2 handled steps
    goal_context=reflection_context,
    layer2_result=goal_result,  # NEW parameter
)

# Process directives from reflection
if reflection.goal_directives:
    async for chunk in self._apply_goal_directives(
        reflection.goal_directives,
        goal,
        parent_state,
        user_input=user_input,
        mode="autonomous",
    ):
        yield chunk
```

### Step 5: Update PlannerProtocol.reflect() Signature

**File**: `src/soothe/protocols/planner.py`

**Changes**:
```python
async def reflect(
    self,
    plan: Plan,
    step_results: list[StepResult],
    goal_context: GoalContext | None = None,
    layer2_result: GoalResult | None = None,  # ✅ NEW parameter
) -> Reflection:
    """
    Reflect on execution results with optional Layer 2 integration.
    
    Args:
        plan: The plan being reflected on.
        step_results: Step execution results (empty when Layer 2 handles execution).
        goal_context: Goal DAG context for Layer 3.
        layer2_result: Layer 2 PlanResult wrapper (when Layer 2 delegates).
    
    Returns:
        Reflection with goal directives for DAG restructuring.
    """
```

### Step 6: Implement Layer 2-Aware Reflection

**File**: `src/soothe/cognition/agent_loop/planner.py`

**Add logic**:
```python
async def reflect(
    self,
    plan: Plan,
    step_results: list[StepResult],
    goal_context: GoalContext | None = None,
    layer2_result: GoalResult | None = None,
) -> Reflection:
    """Reflection using Layer 2 evidence when available."""
    
    # ✅ Layer 2 integration: use GoalResult evidence
    if layer2_result:
        evidence = layer2_result.evidence_summary
        progress = layer2_result.goal_progress
        confidence = layer2_result.confidence
        
        assessment = f"Layer 2 achieved {progress:.0%} progress (confidence {confidence:.0%}). "
        assessment += evidence[:300]
        
        should_revise = (
            layer2_result.status == "failed" 
            or (layer2_result.goal_progress < 0.7 and confidence < 0.6)
        )
        
        feedback = (
            "Goal achieved successfully" if layer2_result.status == "completed"
            else "Goal not achieved, may need revision or new approach"
        )
        
        # Generate directives based on Layer 2 outcome
        directives = []
        if layer2_result.status == "failed" and goal_context:
            # Try alternative approach or create dependency
            directives.append(
                GoalDirective(
                    action="create",
                    description=f"Alternative approach for {plan.goal}",
                    priority=goal_context.current_goal.priority - 10,
                    reason="Primary approach failed via Layer 2",
                )
            )
        
        return Reflection(
            assessment=assessment,
            should_revise=should_revise,
            feedback=feedback,
            goal_directives=directives,
        )
    
    # Fallback: existing step-results-based reflection
    # ... existing logic ...
```

### Step 7: Add Streaming Progress from AgentLoop

**Issue**: AgentLoop.run() returns final PlanResult, but we need streaming events.

**Solution**: Use `AgentLoop.run_with_progress()` which yields events.

**File**: `src/soothe/core/runner/_runner_autonomous.py`

**Changes**:
```python
# Use streaming variant
async for event_type, event_data in agent_loop.run_with_progress(
    goal=goal.description,
    thread_id=thread_id,
    max_iterations=8,
):
    # Propagate Layer 2 events to Layer 3 stream
    if event_type == "completed":
        plan_result = event_data.get("result")
        # ... handle completion
    else:
        # Yield intermediate events (step started, step completed, etc.)
        yield _custom(event_data)
```

---

## Testing Strategy

### Unit Tests

**File**: `tests/core/runner/test_autonomous_layer2_integration.py`

```python
async def test_autonomous_delegates_to_agentloop():
    """Verify Layer 3 calls AgentLoop.run() for goal execution."""
    config = SootheConfig()
    runner = SootheRunner(config)
    
    # Mock AgentLoop
    mock_agent_loop = Mock()
    mock_agent_loop.run = AsyncMock(return_value=PlanResult(
        status="done",
        evidence_summary="Goal achieved",
        goal_progress=1.0,
        confidence=0.9,
    ))
    
    # Execute autonomous goal
    chunks = []
    async for chunk in runner._execute_autonomous_goal(...):
        chunks.append(chunk)
    
    # ✅ Verify AgentLoop was called
    assert mock_agent_loop.run.called
    assert mock_agent_loop.run.call_args[1]["goal"] == "test goal"
    assert mock_agent_loop.run.call_args[1]["max_iterations"] == 8

async def test_planresult_flows_to_reflection():
    """Verify PlanResult from Layer 2 is used in Layer 3 reflection."""
    # ... test reflection receives layer2_result parameter

async def test_layer_isolation():
    """Verify each goal uses isolated thread_id."""
    # ... test thread_id = {parent_tid}__goal_{goal.id}
```

### Integration Tests

```python
async def test_full_autonomous_workflow():
    """Test complete Layer 3 → Layer 2 → Layer 1 flow."""
    config = SootheConfig(autonomous={"enabled": True, "max_iterations": 3})
    runner = SootheRunner(config)
    
    chunks = []
    async for chunk in runner.astream("Complex multi-goal task", autonomous=True):
        chunks.append(chunk)
    
    # Verify goal created
    assert any(c["type"] == "soothe.cognition.goal.created" for c in chunks)
    
    # Verify AgentLoop delegation (no direct step events from Layer 3)
    assert not any(c["type"] == "soothe.plan.step_started" and "autonomous" in str(c) for c in chunks)
    
    # Verify goal completed
    assert any(c["type"] == "soothe.cognition.goal.completed" for c in chunks)
```

---

## Migration Path

### Phase 1: Add Layer 2 Integration (Non-Breaking)

1. Add AgentLoop imports and GoalResult model
2. Implement new Layer 2 delegation code path in `_execute_autonomous_goal()`
3. Keep existing `_run_step_loop()` as fallback for backward compatibility
4. Add `layer2_result` parameter to `reflect()` (optional, default None)

### Phase 2: Test and Validate

1. Run unit tests verifying AgentLoop delegation
2. Run integration tests for full autonomous workflow
3. Monitor metrics: goal completion rate, iteration counts, evidence quality

### Phase 3: Remove Duplicate Logic

1. Once Layer 2 path is stable, remove `_run_step_loop()` from autonomous runner
2. Remove direct `_stream_phase()` calls
3. Update all reflection logic to use `layer2_result`

### Phase 4: Update Documentation

1. Update RFC-200 Implementation Status to mark delegation ✅
2. Update architecture diagrams to show clean layer separation
3. Add integration contract documentation

---

## Validation Checklist

After implementation:

- [ ] Layer 3 creates AgentLoop instance per goal
- [ ] AgentLoop.run() invoked with correct parameters
- [ ] PlanResult captured and stored in GoalResult
- [ ] GoalResult passed to planner.reflect()
- [ ] Reflection uses layer2_result for assessment
- [ ] Goal completed/failed based on PlanResult.status
- [ ] No direct step execution in Layer 3
- [ ] Thread isolation: `{parent_tid}__goal_{goal.id}`
- [ ] Unit tests pass
- [ ] Integration tests pass
- [ ] Performance metrics match or improve

---

## Expected Outcomes

### Architecture Benefits

1. **Clean Layer Separation**: Layer 3 → Layer 2 → Layer 1
2. **Single Responsibility**: Each layer handles its scope
3. **Evidence Flow**: PlanResult propagates through layers
4. **Iterative Refinement**: Goals benefit from Plan → Execute loop

### Functional Benefits

1. **Better Goal Execution**: Layer 2's sophisticated planning per goal
2. **Evidence-Based Reflection**: Layer 3 uses Layer 2's judgment
3. **Reduced Complexity**: Remove duplicate step scheduling
4. **Consistent Behavior**: Autonomous and non-autonomous use same Layer 2

---

## References

- RFC-200: Layer 3 Autonomous Goal Management
- RFC-200: Layer 2 Agentic Goal Execution
- RFC-100: Layer 1 CoreAgent Runtime
- IG-115: AgentLoop Plan-and-Execute implementation
- `src/soothe/cognition/agent_loop/agent_loop.py`
- `src/soothe/core/runner/_runner_agentic.py` (correct Layer 2 usage)

---

## Estimated Timeline

- **Day 1**: Implement AgentLoop delegation and GoalResult model
- **Day 2**: Update reflection to use layer2_result
- **Day 3**: Write unit and integration tests
- **Day 4**: Remove duplicate logic, validate, update documentation

**Total**: 3-4 days

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Breaking existing autonomous behavior | High | Phase 1: Keep fallback path, gradual rollout |
| Performance regression | Medium | Benchmark iteration counts, goal completion time |
| PlanResult not flowing correctly | High | Add logging, test PlanResult propagation |
| Reflection logic incompatible | Medium | Make layer2_result optional, test both paths |

---

**Next**: Proceed to IG-155 (Autopilot Goal Discovery Implementation)