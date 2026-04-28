# RFC-615: Goal Completion Module Architecture

**RFC**: 615
**Title**: Goal Completion Module Architecture
**Status**: Implemented
**Kind**: Architecture Design
**Created**: 2026-04-28
**Dependencies**: RFC-201, RFC-603
**Related**: IG-199, IG-295, IG-296

---

## Abstract

This RFC defines a modular architecture for AgentLoop goal completion logic, extracting the complex decision tree from monolithic orchestration code into a dedicated GoalCompletionModule with clear separation of concerns. The module encapsulates all decisions and execution logic for producing user-visible goal completion responses, making AgentLoop orchestration simpler, testable, and extensible.

---

## Problem Statement

**Current Issues** (RFC-201 §90-97):

1. **Monolithic Logic**: ~200 lines of goal completion code embedded in `agent_loop.py:run_with_progress()` main orchestration method
2. **Mixed Concerns**: Response categorization, synthesis policy decisions, LLM calls, and prompt construction all intertwined
3. **Hard to Test**: Complex branching logic (planner_skip → direct → synthesis → summary) requires mocking entire AgentLoop
4. **Hard to Maintain**: Multiple decision points, nested conditionals, scattered state access
5. **Hard to Extend**: Adding new completion modes requires modifying core orchestration loop

**Current Architecture** (lines 329-523 in agent_loop.py):

```
if plan_result.is_done():
    # ~200 lines of:
    - Response length categorization
    - Goal type classification
    - Policy decisions (planner_skip, direct, synthesis)
    - LLM synthesis execution
    - Streaming accumulation
    - Final output resolution
    - State updates
```

This violates **separation of concerns** (RFC-001 §28) and makes AgentLoop orchestration harder to reason about.

---

## Architecture Design

### Module Structure

Extract goal completion logic into dedicated module hierarchy:

```
cognition/agent_loop/
├── completion/                    # NEW module directory
│   ├── __init__.py
│   ├── goal_completion.py         # Main orchestrator
│   ├── response_categorizer.py    # Length/goal type classification
│   ├── synthesis_executor.py      # LLM synthesis execution
│   └── completion_strategies.py   # Strategy implementations
└── core/
    ├── agent_loop.py              # Simplified (calls completion module)
    ├── executor.py                # Unchanged
    └── plan_phase.py              # Unchanged
```

### Module Responsibilities

| Module | Responsibility | Dependencies |
|--------|----------------|--------------|
| `GoalCompletionModule` | Orchestrate completion flow | All below + synthesis_policy |
| `ResponseCategorizer` | Determine length category, goal type | response_length_policy, synthesis (classification only) |
| `SynthesisExecutor` | Execute LLM synthesis, accumulate stream | CoreAgent, stream_normalize |
| `CompletionStrategies` | Implement planner_skip, direct, synthesis, summary | State, PlanResult |

### Clean Architecture Principles

**Separation of Concerns** (RFC-001 §28):
- **Policy Layer**: `synthesis_policy.py` (decisions)
- **Execution Layer**: `completion/synthesis_executor.py` (LLM calls, streaming)
- **Classification Layer**: `completion/response_categorizer.py` (categorization logic)
- **Orchestration Layer**: `completion/goal_completion.py` (strategy selection, flow control)

**Dependency Rule** (Clean Architecture):
- Orchestration → Strategies → Execution → CoreAgent
- Classification → Policy (no execution dependencies)
- Policy → State schemas (no execution dependencies)

---

## Module APIs

### GoalCompletionModule (Main Orchestrator)

```python
class GoalCompletionModule:
    """Orchestrates goal completion flow with strategy selection."""
    
    def __init__(self, core_agent: CoreAgent, planner_model: BaseChatModel, config: SootheConfig):
        self.categorizer = ResponseCategorizer(planner_model)
        self.executor = SynthesisExecutor(core_agent)
        self.strategies = CompletionStrategies()
    
    async def complete_goal(
        self,
        goal: str,
        state: LoopState,
        plan_result: PlanResult,
    ) -> tuple[PlanResult, AsyncGenerator]:
        """Produce user-visible goal completion response.
        
        Decision flow:
        1. Categorize response (length, goal type)
        2. Select strategy (planner_skip, direct, synthesis, summary)
        3. Execute strategy (may involve LLM synthesis)
        4. Return updated PlanResult + stream chunks
        
        Args:
            goal: Goal description
            state: Loop state with execution history
            plan_result: Plan result with require_goal_completion
            
        Returns:
            (updated PlanResult, async generator of stream chunks)
        """
        # 1. Categorize response
        category = self.categorizer.categorize(state, plan_result)
        
        # 2. Select strategy
        strategy = self.strategies.select_strategy(state, plan_result, category)
        
        # 3. Execute strategy
        final_output, stream_gen = await strategy.execute(goal, state, plan_result, category)
        
        # 4. Update PlanResult
        updated_result = plan_result.model_copy(update={
            "full_output": final_output,
            "response_length_category": category.value,
        })
        
        return updated_result, stream_gen
```

### ResponseCategorizer (Classification)

```python
class ResponseCategorizer:
    """Determines response length category and goal type from execution evidence."""
    
    def __init__(self, planner_model: BaseChatModel):
        self.planner_model = planner_model
    
    def categorize(self, state: LoopState, plan_result: PlanResult) -> ResponseLengthCategory:
        """Determine response length category and goal type.
        
        Uses:
        - Intent classification from state
        - Goal type from evidence patterns
        - Evidence metrics (volume, diversity)
        - Task complexity
        
        Returns:
            ResponseLengthCategory with min_words, max_words
        """
        # Calculate evidence metrics
        volume, diversity = calculate_evidence_metrics(state.step_results)
        
        # Determine goal type (reuse synthesis classification)
        evidence_text = "\n\n".join(r.to_evidence_string(truncate=False) for r in state.step_results if r.success)
        goal_type = SynthesisPhase(self.planner_model)._classify_goal_type(evidence_text)
        
        # Determine intent and complexity
        intent_type = getattr(state.intent, "intent_type", "new_goal")
        task_complexity = getattr(state.intent, "task_complexity", "medium")
        
        # Determine response length
        return determine_response_length(
            intent_type=intent_type,
            goal_type=goal_type,
            task_complexity=task_complexity,
            evidence_volume=volume,
            evidence_diversity=diversity,
        )
```

### SynthesisExecutor (LLM Execution)

```python
class SynthesisExecutor:
    """Executes LLM synthesis turn with streaming accumulation."""
    
    def __init__(self, core_agent: CoreAgent):
        self.core_agent = core_agent
    
    async def execute_synthesis(
        self,
        goal: str,
        state: LoopState,
        plan_result: PlanResult,
        category: ResponseLengthCategory,
    ) -> AsyncGenerator:
        """Execute synthesis LLM turn and yield stream chunks.
        
        Args:
            goal: Goal description
            state: Loop state for thread context
            plan_result: Plan result with evidence
            category: Response length category
            
        Yields:
            ("goal_completion_stream", chunk) tuples
        """
        # Build synthesis prompt
        prompt = self._build_synthesis_prompt(goal, category)
        
        # Create human message
        human_msg = LoopHumanMessage(
            content=prompt,
            thread_id=state.thread_id,
            iteration=state.iteration,
            goal_summary=state.goal[:200],
            phase="goal_completion",
        )
        
        # Stream and accumulate
        accum = GoalCompletionAccumState()
        async for chunk in self.core_agent.astream(
            {"messages": [human_msg]},
            config={"configurable": {"thread_id": state.thread_id}},
            stream_mode=["messages"],
            subgraphs=False,
        ):
            for msg in iter_messages_for_act_aggregation(chunk):
                update_goal_completion_from_message(accum, msg)
            yield ("goal_completion_stream", chunk)
        
        # Resolve final text
        return resolve_goal_completion_text(accum)
    
    def _build_synthesis_prompt(self, goal: str, category: ResponseLengthCategory) -> str:
        """Construct synthesis prompt with length guidance."""
        # (Move prompt construction logic from agent_loop.py)
        ...
```

### CompletionStrategies (Strategy Pattern)

```python
class CompletionStrategies:
    """Strategy selection and execution for goal completion."""
    
    def select_strategy(
        self,
        state: LoopState,
        plan_result: PlanResult,
        category: ResponseLengthCategory,
    ) -> CompletionStrategy:
        """Select completion strategy based on policy decisions.
        
        Decision tree (simplified):
        1. if not plan_result.require_goal_completion → PlannerSkipStrategy
        2. if should_return_directly() → DirectReturnStrategy
        3. if needs_synthesis() → SynthesisStrategy
        4. else → SummaryStrategy
        
        Args:
            state: Loop state
            plan_result: Plan result
            category: Response category
            
        Returns:
            Selected strategy instance
        """
        mode = "adaptive"  # From config
        
        if not plan_result.require_goal_completion:
            return PlannerSkipStrategy()
        
        if should_return_goal_completion_directly(state, plan_result, mode, response_length_category=category.value):
            return DirectReturnStrategy()
        
        if needs_final_thread_synthesis(state, plan_result, mode):
            return SynthesisStrategy()
        
        return SummaryStrategy()


class CompletionStrategy(Protocol):
    """Protocol for completion strategy implementations."""
    
    async def execute(
        self,
        goal: str,
        state: LoopState,
        plan_result: PlanResult,
        category: ResponseLengthCategory,
    ) -> tuple[str, AsyncGenerator]:
        """Execute strategy and return final output + stream chunks."""
        ...


class PlannerSkipStrategy(CompletionStrategy):
    """Reuse Execute assistant text when planner says no synthesis needed."""
    
    async def execute(self, goal, state, plan_result, category):
        reuse = (state.last_execute_assistant_text or "").strip()
        return reuse, _empty_generator()


class DirectReturnStrategy(CompletionStrategy):
    """Direct return when Execute output is rich and aligned."""
    
    async def execute(self, goal, state, plan_result, category):
        reuse = (state.last_execute_assistant_text or "").strip()
        return reuse, _empty_generator()


class SynthesisStrategy(CompletionStrategy):
    """Execute LLM synthesis turn for comprehensive report."""
    
    def __init__(self, executor: SynthesisExecutor):
        self.executor = executor
    
    async def execute(self, goal, state, plan_result, category):
        final_text = await self.executor.execute_synthesis(goal, state, plan_result, category)
        # Consume generator to get final text
        # (Implementation detail: synthesis executor yields chunks, we collect final text)
        ...


class SummaryStrategy(CompletionStrategy):
    """Fallback summary from plan_result or step counts."""
    
    async def execute(self, goal, state, plan_result, category):
        if plan_result.full_output:
            return plan_result.full_output, _empty_generator()
        elif state.step_results:
            successful = sum(1 for r in state.step_results if r.success)
            total = len(state.step_results)
            return f"Completed {successful}/{total} steps. {plan_result.next_action}", _empty_generator()
        else:
            return plan_result.next_action or "Goal achieved", _empty_generator()
```

---

## Integration with AgentLoop

### Simplified agent_loop.py

```python
# In agent_loop.py:run_with_progress()
if plan_result.is_done():
    # Delegate to GoalCompletionModule (10 lines instead of 200)
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

**Benefits**:
- ✅ AgentLoop orchestration is simple and readable (10 lines vs 200)
- ✅ Goal completion logic is encapsulated and testable
- ✅ Strategies are extensible (add new strategy without touching AgentLoop)
- ✅ Clean separation: orchestration vs execution vs policy

---

## Testability

**Unit Tests** (each module independently testable):

```python
# Test categorizer
def test_response_categorizer_standard_category():
    categorizer = ResponseCategorizer(mock_model)
    state = LoopState(step_results=[...], intent=mock_intent)
    category = categorizer.categorize(state, mock_plan_result)
    assert category.value == "standard"

# Test strategy selection
def test_strategy_selection_synthesis_when_planner_requests():
    strategies = CompletionStrategies()
    plan_result = PlanResult(require_goal_completion=True, ...)
    strategy = strategies.select_strategy(mock_state, plan_result, mock_category)
    assert isinstance(strategy, SynthesisStrategy)

# Test executor (mock CoreAgent)
def test_synthesis_executor_accumulates_stream():
    executor = SynthesisExecutor(mock_core_agent)
    chunks = []
    async for chunk in executor.execute_synthesis(...):
        chunks.append(chunk)
    assert len(chunks) > 0

# Test full module integration
def test_goal_completion_module_produces_output():
    module = GoalCompletionModule(mock_core_agent, mock_model, mock_config)
    result, gen = await module.complete_goal("goal", mock_state, mock_plan_result)
    assert result.full_output is not None
```

---

## Extensibility

**Adding New Completion Mode** (example: "adaptive_summary_strategy"):

1. Add new strategy class in `completion_strategies.py`
2. Update `select_strategy()` decision tree
3. No changes to AgentLoop orchestration

```python
class AdaptiveSummaryStrategy(CompletionStrategy):
    """Generate adaptive summary based on goal complexity."""
    
    async def execute(self, goal, state, plan_result, category):
        # New logic here
        ...

# In CompletionStrategies.select_strategy():
if should_use_adaptive_summary(state, plan_result):
    return AdaptiveSummaryStrategy()
```

**Zero impact on AgentLoop core orchestration**.

---

## Migration Strategy

**IG-297 Implementation Plan**:

1. Create module structure (`completion/` directory)
2. Extract ResponseCategorizer (lines 343-377 from agent_loop.py)
3. Extract SynthesisExecutor (lines 419-489 from agent_loop.py)
4. Extract CompletionStrategies (lines 391-495 decision tree from agent_loop.py)
5. Create GoalCompletionModule orchestrator
6. Simplify agent_loop.py (replace ~200 lines with module call)
7. Add unit tests for each module
8. Run verification suite

**Preservation Guarantees**:
- ✅ IG-295 fix preserved (planner recommendation honored)
- ✅ IG-296 refactoring preserved (synthesis_policy module)
- ✅ No behavior changes (pure refactoring)
- ✅ All existing tests pass

---

## Success Criteria

- ✅ AgentLoop orchestration simplified (< 50 lines for goal completion)
- ✅ Each completion module unit-testable
- ✅ Clear separation of concerns (policy → execution → classification)
- ✅ Extensible strategy pattern
- ✅ All existing tests pass
- ✅ IG-295, IG-296 fixes preserved
- ✅ Verification suite passes (lint, format, tests)

---

## References

- RFC-201 §90-97: Adaptive final user response (original description)
- RFC-603: Synthesis phase (evidence-based triggers)
- IG-199: Final response policy implementation
- IG-295: Planner recommendation honored
- IG-296: Synthesis policy module refactoring
- Clean Architecture (Robert Martin): Separation of concerns, dependency rule