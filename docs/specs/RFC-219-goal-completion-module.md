# RFC-219: Goal Completion Module Architecture

**RFC**: 219
**Title**: Goal Completion Module Architecture
**Status**: Implemented
**Kind**: Architecture Design
**Created**: 2026-04-28
**Dependencies**: RFC-201, RFC-603
**Related**: IG-199, IG-295, IG-296, IG-355, IG-400

---

## Abstract

This RFC defines a modular architecture for StrangeLoop goal completion logic, extracting the complex decision tree from monolithic orchestration code into a dedicated GoalCompletionModule with clear separation of concerns. The module encapsulates all decisions and execution logic for producing user-visible goal completion responses, making StrangeLoop orchestration simpler, testable, and extensible.

**Runner wire:** The `goal_completion` node sets **`skip_goal_completion_wire_duplicate`** on the `completed` payload when streamed **`synthesize`** already delivered `phase=goal_completion` on **`messages`**. The agentic runner emits **`loop_assistant_messages_chunk(..., phase="goal_completion")`** when the flag is **false** — including **`ledger_direct`**, because headless mode suppresses execute-phase lines and needs this replay for stdout (RFC-500 / IG-343). TUI routing for loop-tagged AI is defined in **RFC-500**.

---

## Problem Statement

**Current Issues** (RFC-201 §90-97):

1. **Monolithic Logic**: ~200 lines of goal completion code embedded in `strange_loop.py:run_with_progress()` main orchestration method
2. **Mixed Concerns**: Response categorization, synthesis policy decisions, LLM calls, and prompt construction all intertwined
3. **Hard to Test**: Complex branching logic (planner_skip → direct → synthesis → summary) requires mocking entire StrangeLoop
4. **Hard to Maintain**: Multiple decision points, nested conditionals, scattered state access
5. **Hard to Extend**: Adding new completion modes requires modifying core orchestration loop

**Current Architecture** (lines 329-523 in strange_loop.py):

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

This violates **separation of concerns** (RFC-001 §28) and makes StrangeLoop orchestration harder to reason about.

---

## Architecture Design

### Module Structure

Extract goal completion logic into dedicated module hierarchy:

```
packages/soothe/src/soothe/core/
├── strange_loop/
│   ├── policies/goal_completion_policy.py   # DEPRECATED → migrated to PlanManager
│   ├── core/plan_dag.py                     # Unified DAG of all planned steps
│   ├── core/plan_manager.py                 # Plan orchestration + completion strategy
│   ├── analysis/synthesis.py                # synthesis helper(s)
│   ├── core/strange_loop.py                   # invokes goal-completion flow
│   ├── core/plan_phase.py
│   └── core/executor.py
└── runner/                                  # wires StrangeLoop + streaming (e.g. _runner_strange_loop)
```
*(Historical draft showed `cognition/strange_loop/completion/`; implementation lives under `core/` per IG consolidation.)*

### PlanDAG: Unified Plan DAG

`PlanDAG` (plan_dag.py) merges all steps from every plan (including replans) into a single DAG keyed by step ID.

```python
@dataclass
class PlanDAG:
    nodes: dict[str, PlanNode] = field(default_factory=dict)
    _plan_ids: set[str] = field(default_factory=set)

    def ingest_plan(self, plan_result: PlanResult, plan_id: str | None, iteration: int) -> None
    def mark_completed(self, step_id: str, outcome: StepResult) -> None
    def mark_failed(self, step_id: str, outcome: StepResult) -> None

    @property def total_steps(self) -> int
    @property def completed_steps(self) -> int
    @property def failed_steps(self) -> int
    @property def remaining_steps(self) -> int
    @property def has_dag_dependencies(self) -> bool
    @property def max_chain_depth(self) -> int   # BFS-based longest chain
    @property def plan_count(self) -> int        # Number of distinct plans (replan detection)
    @property def success_rate(self) -> float
    @property def used_subagents(self) -> bool
```

### PlanManager: Plan Orchestration + Completion Strategy

`PlanManager` (plan_manager.py) wraps `PlanDAG` and provides goal completion decision logic. It subsumes the functionality previously in `goal_completion_policy.py`.

```python
class CompletionStrategy(str, Enum):
    LEDGER_DIRECT = "ledger_direct"    # Return ledger text directly
    SYNTHESIZE = "synthesize"          # LLM synthesis required
    SUMMARY = "summary"                # Fallback summary

@dataclass
class PlanManager:
    goal: str
    dag: PlanDAG = field(default_factory=PlanDAG)
    plan_history: list[PlanResult] = field(default_factory=list)

    def ingest_plan(self, plan_result: PlanResult, plan_id: str | None, iteration: int) -> None
    def record_step_outcomes(self, step_results: list[StepResult]) -> None
    def determine_goal_completion_needs(llm_decision, state, mode) -> bool
    def determine_completion_strategy(state, plan_result, mode) -> CompletionStrategy
```

**Completion strategy decision flow** (`determine_completion_strategy`):
1. Mode override: `always_synthesize` → `SYNTHESIZE`
2. Planner says no synthesis + simple execution → `LEDGER_DIRECT`
3. DAG complexity vetoes (replan, failures, subagents, deep chains) → `SYNTHESIZE`
4. Ledger richness check (rich + overlaps with plan) → `LEDGER_DIRECT`
5. Default → `SYNTHESIZE`

**Heuristic checks** (`_heuristic_requires_goal_completion`):
- `parallel_multi_step` wave execution
- `subagent_cap` hit
- Failed steps with low success rate (< 60%)
- DAG dependencies ≥ 3 on current plan

---

### Module Responsibilities

| Module | Responsibility | Dependencies |
|--------|----------------|--------------|
| `PlanManager` | Plan orchestration + completion strategy | PlanDAG, state schemas |
| `PlanDAG` | Unified DAG of all planned steps | State schemas |
| `ResponseCategorizer` | Determine length category, goal type | response_length_policy, synthesis (classification only) |
| `SynthesisExecutor` | Execute LLM synthesis, accumulate stream | CoreAgent, stream_normalize |
| `CompletionStrategies` | Implement planner_skip, direct, synthesis, summary | State, PlanResult |

### Clean Architecture Principles

**Separation of Concerns** (RFC-001 §28):
- **Policy Layer**: `strange_loop/core/plan_manager.py` (PlanManager, CompletionStrategy enum) and config (`SootheConfig.agentic.final_response`)
- **Execution / synthesis**: `strange_loop/analysis/synthesis.py`, `strange_loop/core/strange_loop.py`, runner modules under `core/runner/`
- **Plan DAG**: `strange_loop/core/plan_dag.py` (PlanDAG data structure)
- *(Historical draft referenced `cognition/strange_loop/completion/*`; code now lives under `packages/soothe/src/soothe/core/`.)*

**Dependency Rule** (Clean Architecture):
- Orchestration → PlanManager → PlanDAG → State schemas
- Classification → Policy (no execution dependencies)
- Policy → State schemas (no execution dependencies)

---

## Module APIs

### PlanManager (Plan Orchestration + Completion Strategy)

```python
class CompletionStrategy(str, Enum):
    LEDGER_DIRECT = "ledger_direct"
    SYNTHESIZE = "synthesize"
    SUMMARY = "summary"

@dataclass
class PlanManager:
    """Manages the DAG of all planned steps for a single goal across iterations."""

    goal: str
    dag: PlanDAG
    plan_history: list[PlanResult]

    def ingest_plan(self, plan_result: PlanResult, plan_id: str | None, iteration: int) -> None:
        """Called from plan_assess / plan_generate after finalize_plan_result."""

    def record_step_outcomes(self, step_results: list[StepResult]) -> None:
        """Called from record_iteration after execute."""

    def determine_goal_completion_needs(
        self, llm_decision: bool, state: Any, mode: str = "llm_only",
    ) -> bool:
        """Decide whether goal-completion synthesis/reporting is required.

        Modes: llm_only | heuristic_only | hybrid
        """

    def determine_completion_strategy(
        self, state: LoopState, plan_result: PlanResult,
        mode: FinalResponseMode = "adaptive",
    ) -> CompletionStrategy:
        """Determine goal completion strategy from the full DAG + history."""
```

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
        # (Move prompt construction logic from strange_loop.py)
        ...
```

### CompletionStrategies (Enum-Based Strategy)

The completion strategy is now an enum (`CompletionStrategy`) resolved by `PlanManager.determine_completion_strategy()` rather than a protocol-based class hierarchy.

```python
class CompletionStrategy(str, Enum):
    LEDGER_DIRECT = "ledger_direct"     # Direct return from ledger
    SYNTHESIZE = "synthesize"           # LLM synthesis required
    SUMMARY = "summary"                 # Fallback summary
```

**Strategy selection** (in `PlanManager._dag_requires_synthesis`):
- Replan detected (`plan_count >= 2`) → `SYNTHESIZE`
- Failed steps → `SYNTHESIZE`
- Subagents used → `SYNTHESIZE`
- Deep chain (`max_chain_depth >= 3`) → `SYNTHESIZE`
- Subagent cap hit → `SYNTHESIZE`
- Parallel multi-step wave → `SYNTHESIZE`
- Low success rate with failures → `SYNTHESIZE`
- DAG dependencies on current plan → `SYNTHESIZE`
- Simple execution → `LEDGER_DIRECT` (if ledger rich enough)

**Simple execution check** (`_is_simple_execution`):
```python
def _is_simple_execution(self) -> bool:
    return (
        self.dag.plan_count <= 1
        and not self.dag.has_dag_dependencies
        and self.dag.failed_steps == 0
        and self.dag.total_steps <= 2
    )
```

---

## Integration with StrangeLoop

### Simplified strange_loop.py

```python
# In strange_loop.py:run_with_progress()
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
- ✅ StrangeLoop orchestration is simple and readable (10 lines vs 200)
- ✅ Goal completion logic is encapsulated and testable
- ✅ Strategies are extensible (add new strategy without touching StrangeLoop)
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
3. No changes to StrangeLoop orchestration

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

**Zero impact on StrangeLoop core orchestration**.

---

## Migration Strategy

**IG-297 Implementation Plan** (original goal completion extraction):

1. Create module structure (`completion/` directory)
2. Extract ResponseCategorizer (lines 343-377 from strange_loop.py)
3. Extract SynthesisExecutor (lines 419-489 from strange_loop.py)
4. Extract CompletionStrategies (lines 391-495 decision tree from strange_loop.py)
5. Create GoalCompletionModule orchestrator
6. Simplify strange_loop.py (replace ~200 lines with module call)
7. Add unit tests for each module
8. Run verification suite

**IG-400 Implementation Plan** (PlanManager/PlanDAG architecture):

1. Create `plan_dag.py` with PlanDAG dataclass (nodes keyed by step.id)
2. Create `plan_manager.py` with PlanManager dataclass + CompletionStrategy enum
3. Move `determine_goal_completion_needs` from `goal_completion_policy.py` into PlanManager
4. Migrate heuristic checks into PlanManager methods
5. Delete `goal_completion_policy.py` (functionality fully migrated)
6. Update imports in `policies/__init__.py` and graph nodes
7. Align tests with step.id-based keys (not composite IDs)
8. Verify all 300+ tests pass

**Preservation Guarantees**:
- ✅ IG-295 fix preserved (planner recommendation honored)
- ✅ IG-296 refactoring preserved (synthesis_policy module)
- ✅ No behavior changes (pure refactoring)
- ✅ All existing tests pass

---

## Success Criteria

- ✅ StrangeLoop orchestration simplified (< 50 lines for goal completion)
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