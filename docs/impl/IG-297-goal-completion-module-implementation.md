# IG-297: Goal Completion Module Implementation

**Status**: Completed
**Date**: 2026-04-28
**RFC**: RFC-615
**Issue**: Monolithic goal completion logic in AgentLoop orchestration

---

## Objective

Extract ~200 lines of goal completion logic from `agent_loop.py` into dedicated `completion/` module hierarchy following RFC-615 architecture design.

**Goals**:
- Simplify AgentLoop orchestration (reduce from ~200 lines to ~10 lines)
- Make goal completion logic unit-testable
- Enable extensible completion strategies
- Preserve IG-295, IG-296 fixes (planner recommendation, synthesis policy)

---

## Implementation Plan

### Step 1: Create Module Structure

Create new `cognition/agent_loop/completion/` directory with:

```
completion/
├── __init__.py
├── goal_completion.py         # Main orchestrator
├── response_categorizer.py    # Classification logic
├── synthesis_executor.py      # LLM synthesis execution
└── completion_strategies.py   # Strategy pattern implementations
```

### Step 2: Extract ResponseCategorizer

**Source**: `agent_loop.py:343-377`

**Extract**:
- Response length categorization
- Goal type classification from evidence
- Evidence metrics calculation
- Intent/complexity extraction

**Implementation**: Create `ResponseCategorizer` class in `response_categorizer.py`

### Step 3: Extract SynthesisExecutor

**Source**: `agent_loop.py:419-489`

**Extract**:
- Synthesis prompt construction
- CoreAgent streaming execution
- Goal completion accumulation
- Stream chunk normalization

**Implementation**: Create `SynthesisExecutor` class in `synthesis_executor.py`

### Step 4: Extract CompletionStrategies

**Source**: `agent_loop.py:391-495` (decision tree)

**Extract**:
- Strategy selection logic (planner_skip, direct, synthesis, summary)
- Strategy execution implementations
- Empty generator helper

**Implementation**: Create `CompletionStrategies` + strategy classes in `completion_strategies.py`

### Step 5: Create GoalCompletionModule Orchestrator

**Implementation**: Create `GoalCompletionModule` class in `goal_completion.py`

**Responsibilities**:
- Initialize categorizer, executor, strategies
- Orchestrate completion flow (categorize → select → execute → update)
- Return updated PlanResult + stream generator

### Step 6: Simplify AgentLoop

**Modification**: Replace ~200 lines in `agent_loop.py:329-523` with module call

**New code** (simplified):
```python
if plan_result.is_done():
    # Delegate to GoalCompletionModule
    completion_module = GoalCompletionModule(
        self.core_agent,
        self.loop_planner._model,
        self.config,
    )
    
    updated_result, stream_gen = await completion_module.complete_goal(
        goal, state, plan_result
    )
    
    # Yield stream chunks
    async for chunk in stream_gen:
        yield chunk
    
    # Finalize goal
    await state_manager.finalize_goal(goal_record, updated_result.full_output)
    yield ("completed", {"result": updated_result, ...})
    return
```

### Step 7: Add Unit Tests

**Test Coverage**:
- `test_response_categorizer.py`: Categorization logic
- `test_completion_strategies.py`: Strategy selection and execution
- `test_synthesis_executor.py`: Synthesis execution (mock CoreAgent)
- `test_goal_completion_module.py`: Full module integration

### Step 8: Verification

Run verification suite:
```bash
./scripts/verify_finally.sh
```

---

## Implementation Details

### Imports to Preserve

**From synthesis_policy.py** (IG-296):
- `needs_final_thread_synthesis`
- `should_return_goal_completion_directly`

**From response_length_policy.py**:
- `ResponseLengthCategory`
- `calculate_evidence_metrics`
- `determine_response_length`

**From synthesis.py** (execution layer):
- `SynthesisPhase` (for `_classify_goal_type`)

**From stream_normalize.py**:
- `GoalCompletionAccumState`
- `iter_messages_for_act_aggregation`
- `resolve_goal_completion_text`
- `update_goal_completion_from_message`

### Preservation Guarantees

**IG-295 Fix**: `evidence_requires_final_synthesis()` checks `plan_result.require_goal_completion` first
- ✅ Preserved in `CompletionStrategies.select_strategy()` decision tree

**IG-296 Refactoring**: Decision logic in `synthesis_policy.py`, execution in `synthesis.py`
- ✅ Preserved: Strategies import from `synthesis_policy.py`

**No Behavior Changes**: Pure refactoring, all existing tests should pass

---

## File-by-File Implementation

### File 1: `completion/__init__.py`

```python
"""Goal completion module (RFC-615)."""

from .goal_completion import GoalCompletionModule

__all__ = ["GoalCompletionModule"]
```

### File 2: `completion/response_categorizer.py`

(Extract from agent_loop.py:343-377)

### File 3: `completion/synthesis_executor.py`

(Extract from agent_loop.py:419-489)

### File 4: `completion/completion_strategies.py`

(Extract decision tree from agent_loop.py:391-495)

### File 5: `completion/goal_completion.py`

(New orchestrator combining above)

### File 6: `core/agent_loop.py`

(Simplify goal completion section)

---

## Testing Strategy

### Unit Tests

**ResponseCategorizer**:
```python
def test_categorizer_standard_category():
    categorizer = ResponseCategorizer(mock_model)
    state = LoopState(step_results=[mock_step], intent=mock_intent)
    plan_result = PlanResult(...)
    category = categorizer.categorize(state, plan_result)
    assert category.value in ["brief", "concise", "standard", "comprehensive"]
```

**CompletionStrategies**:
```python
def test_strategy_selection_synthesis_when_planner_requests():
    strategies = CompletionStrategies(mock_executor)
    plan_result = PlanResult(require_goal_completion=True, ...)
    strategy = strategies.select_strategy(mock_state, plan_result, mock_category)
    assert isinstance(strategy, SynthesisStrategy)
```

**SynthesisExecutor**:
```python
def test_executor_yields_chunks():
    executor = SynthesisExecutor(mock_core_agent)
    chunks = []
    async for chunk in executor.execute_synthesis(...):
        chunks.append(chunk)
    assert len(chunks) > 0
```

**GoalCompletionModule**:
```python
def test_module_integration():
    module = GoalCompletionModule(mock_core_agent, mock_model, mock_config)
    result, gen = await module.complete_goal("goal", mock_state, mock_plan_result)
    assert result.full_output is not None
```

---

## Success Criteria

- ✅ AgentLoop goal completion simplified (< 50 lines)
- ✅ Each module unit-testable
- ✅ Strategy pattern extensible
- ✅ IG-295, IG-296 fixes preserved
- ✅ All existing tests pass
- ✅ Verification suite passes (lint, format, tests)

---

## References

- RFC-615: Goal Completion Module Architecture
- RFC-201: AgentLoop Plan-Execute Loop (§90-97 adaptive final response)
- IG-295: Planner recommendation honored
- IG-296: Synthesis policy module refactoring