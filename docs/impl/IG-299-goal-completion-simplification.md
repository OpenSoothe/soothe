# IG-299: Goal Completion Module Simplification

**Status**: In Progress
**Date**: 2026-04-28
**RFC**: RFC-615
**Issue**: Verbosity, overdesign, and overlaps in goal completion/synthesis modules (8 files, 1,085 lines)

---

## Objective

Simplify goal completion architecture by consolidating decision and execution logic:
- Reduce from 8 files to 3 files (62% reduction)
- Reduce from 1,085 lines to ~400 lines (75% reduction)
- Eliminate 4-layer strategy pattern → 3-branch decision function
- Remove duplicate goal classification, evidence metrics, strategy selection
- Maintain IG-298 hybrid approach (LLM primary + execution heuristics)

---

## Current Architecture (Overdesigned)

### Files (8 total, 1,085 lines)
```
policies/goal_completion_policy.py     (162 lines) - Hybrid decision
policies/synthesis_policy.py           (259 lines) - Direct return + overlap checks
analysis/synthesis.py                  (156 lines) - SynthesisPhase (unused)

completion/
├── goal_completion.py                 (115 lines) - Orchestrator
├── response_categorizer.py            (101 lines) - Goal classification (duplicate)
├── synthesis_executor.py              (213 lines) - Streaming (duplicate)
├── completion_strategies.py           (279 lines) - Strategy pattern
└── __init__.py                        (15 lines)  - Exports
```

### Abstraction Layers (5 layers)
```
Policy → Planner → Orchestrator → Strategies → Executor → SynthesisPhase
```

### Issues

1. **Strategy Pattern Overkill**: 279 lines for 4 simple branches (skip/direct/synthesis/summary)
2. **Duplicate Classification**: Goal classification in both SynthesisPhase and ResponseCategorizer
3. **Duplicate Streaming**: SynthesisExecutor implements streaming when CoreAgent already handles it
4. **Unused Categorization**: ResponseCategorizer computes length category only for prompt guidance
5. **Mirror Decision Trees**: CompletionStrategies mirrors synthesis_policy decision logic

---

## Simplified Architecture (3 files, ~400 lines)

### Target Structure
```
policies/goal_completion_policy.py     (~150 lines) - Unified decision + selection
analysis/synthesis.py                  (~120 lines) - Classification + generation
completion/fallback_summary.py         (~30 lines)  - User-friendly fallback
```

### Responsibilities (3 layers)
```
Policy (decision): determine_completion_action() → (action, text)
Synthesis (execution): SynthesisGenerator.generate() → stream
Fallback (summary): generate_user_summary() → text
```

---

## Implementation Plan

### Step 1: Consolidate Decision Logic

**File**: `policies/goal_completion_policy.py`

**Merge**: synthesis_policy + goal_completion_policy + strategy selection

**New Function**:
```python
def determine_completion_action(
    state: LoopState,
    plan_result: PlanResult,
    mode: str = "adaptive",
    response_length_category: str | None = None,
) -> tuple[str, str | None]:
    """Single entry point for completion decision and action.

    Args:
        state: Loop state with execution history.
        plan_result: Plan result with planner's hybrid decision.
        mode: Final-response mode (adaptive, always_synthesize, always_last_execute).
        response_length_category: IG-268 category for richness check.

    Returns:
        (action, precomputed_text) where action in {"skip", "direct", "synthesize", "summary"}
        and precomputed_text is None for "synthesize" or reuse text for others.
    """
    # 1. Mode overrides
    if mode == "always_synthesize":
        return "synthesize", None

    if mode == "always_last_execute":
        assistant = (state.last_execute_assistant_text or "").strip()
        return "direct" if assistant else "summary", assistant

    # 2. Planner skip: trust hybrid decision (IG-298)
    if not plan_result.require_goal_completion:
        reuse = (state.last_execute_assistant_text or "").strip()
        return "skip", reuse

    # 3. Wave execution vetoes
    if state.last_execute_wave_parallel_multi_step:
        return "synthesize", None

    if state.last_wave_hit_subagent_cap:
        return "synthesize", None

    # 4. Direct return check: richness + overlap
    assistant = (state.last_execute_assistant_text or "").strip()
    if not assistant:
        return "synthesize", None

    if _can_return_directly(assistant, plan_result, response_length_category):
        return "direct", assistant

    # 5. Synthesis needed per planner + execution complexity
    return "synthesize", None


def _can_return_directly(
    assistant_text: str,
    plan_result: PlanResult,
    response_length_category: str | None,
) -> bool:
    """Check richness (word count/structure) + overlap with planner output.

    Args:
        assistant_text: Execute assistant output.
        plan_result: Plan result with full_output for overlap check.
        response_length_category: Length category for word floor.

    Returns:
        True if output is rich enough and aligned with planner.
    """
    # Richness check (IG-268)
    if not _is_rich_enough(assistant_text, response_length_category):
        return False

    # Overlap check (avoid unrelated chatter)
    return _overlaps_with_plan_output(assistant_text, plan_result)


# Keep existing helper functions:
# - _is_rich_enough() (from synthesis_policy)
# - _overlaps_with_plan_output() (from synthesis_policy)
# - _heuristic_requires_goal_completion() (hybrid fallback)
```

**Keep**:
- `determine_goal_completion_needs()` (hybrid decision)
- `_heuristic_requires_goal_completion()` (execution complexity checks)
- `_word_count()`, `_min_word_floor()` (richness helpers)

**Delete**:
- synthesis_policy module (merged into this file)

---

### Step 2: Consolidate Execution Logic

**File**: `analysis/synthesis.py`

**Merge**: SynthesisPhase + ResponseCategorizer + SynthesisExecutor

**New Class**:
```python
class SynthesisGenerator:
    """Generate synthesis reports from execution evidence.

    Responsibilities:
    - Goal classification from evidence patterns
    - Response length categorization from metrics
    - LLM synthesis generation with streaming
    """

    def __init__(self, llm_client: BaseChatModel, core_agent: CoreAgent) -> None:
        """Initialize with LLM client for classification and CoreAgent for synthesis."""
        self.llm = llm_client
        self.core_agent = core_agent

    def classify_goal(self, evidence: str) -> str:
        """Classify goal type from evidence patterns.

        Args:
            evidence: Concatenated evidence from successful steps.

        Returns:
            Goal type: architecture_analysis, research_synthesis,
                      implementation_summary, general_synthesis.
        """
        # Keep existing regex patterns from SynthesisPhase._classify_goal_type()
        evidence_lower = evidence.lower()

        # Architecture analysis: Multiple directories + layer mentions
        directory_pattern = r"(src/|docs/|core/|backends/|protocols/|tools/)"
        directories = len(re.findall(directory_pattern, evidence_lower))
        layer_mentions = bool(re.search(r"layer|architecture|component|module", evidence_lower))

        if directories >= 3 and layer_mentions:
            return "architecture_analysis"

        # Research synthesis: Multiple findings
        findings_pattern = r"(found|identified|discovered|located)\s+\d+"
        findings_count = len(re.findall(findings_pattern, evidence_lower))

        if findings_count >= 3:
            return "research_synthesis"

        # Implementation summary: Code mentions
        code_pattern = r"(function|class|method|implementation|def |async def)"
        code_mentions = len(re.findall(code_pattern, evidence_lower))

        if code_mentions >= 5:
            return "implementation_summary"

        return "general_synthesis"

    def categorize_response_length(
        self,
        state: LoopState,
        intent_type: str = "new_goal",
        task_complexity: str = "medium",
    ) -> ResponseLengthCategory:
        """Determine response length from evidence metrics.

        Args:
            state: Loop state with step results.
            intent_type: Intent classification from state.intent.
            task_complexity: Task complexity from state.intent.

        Returns:
            ResponseLengthCategory with min_words, max_words bounds.
        """
        # Calculate metrics (from response_length_policy)
        evidence_volume, evidence_diversity = calculate_evidence_metrics(state.step_results)

        # Classify goal type
        evidence = "\n\n".join(
            r.to_evidence_string(truncate=False) for r in state.step_results if r.success
        )
        goal_type = self.classify_goal(evidence)

        # Determine length category
        return determine_response_length(
            intent_type=intent_type,
            goal_type=goal_type,
            task_complexity=task_complexity,
            evidence_volume=evidence_volume,
            evidence_diversity=evidence_diversity,
        )

    async def generate_synthesis(
        self,
        goal: str,
        state: LoopState,
        plan_result: PlanResult,
        length_category: ResponseLengthCategory,
    ) -> AsyncGenerator:
        """Generate synthesis via CoreAgent streaming.

        Args:
            goal: Goal description.
            state: Loop state with thread context.
            plan_result: Plan result (reserved for future hints).
            length_category: Response length guidance.

        Returns:
            Async generator yielding stream chunks.
        """
        # Extract evidence
        evidence = self._extract_evidence(state)

        # Classify goal type
        goal_type = self.classify_goal(evidence)

        # Build synthesis prompt (keep existing logic from synthesis_executor)
        prompt = self._build_synthesis_prompt(goal, evidence, goal_type, length_category)

        # Create human message
        human_msg = LoopHumanMessage(
            content=prompt,
            thread_id=state.thread_id,
            iteration=state.iteration,
            goal_summary=state.goal[:200] if state.goal else None,
            phase="goal_completion",
        )

        # Stream via CoreAgent (no custom accumulation - CoreAgent handles it)
        async for chunk in self.core_agent.astream(
            {"messages": [human_msg]},
            config={"configurable": {"thread_id": state.thread_id}},
            stream_mode=["messages"],
            subgraphs=False,
        ):
            yield ("goal_completion_stream", chunk)

    def _extract_evidence(self, state: LoopState) -> str:
        """Extract evidence from successful step results."""
        evidence_parts = []
        for result in state.step_results:
            if result.success:
                evidence_str = result.to_evidence_string(truncate=False)
                evidence_parts.append(evidence_str)
        return "\n\n".join(evidence_parts)

    def _build_synthesis_prompt(
        self,
        goal: str,
        evidence: str,
        goal_type: str,
        length_category: ResponseLengthCategory,
    ) -> str:
        """Build synthesis prompt with length guidance.

        Keep existing logic from synthesis_executor._build_synthesis_prompt().
        """
        # ... existing prompt building logic
```

**Keep**:
- Goal classification regex patterns (consolidated)
- Response length categorization logic (moved from ResponseCategorizer)
- Prompt building with length guidance (from SynthesisExecutor)

**Delete**:
- SynthesisPhase class (merged into SynthesisGenerator)
- ResponseCategorizer module (merged into categorize_response_length method)
- SynthesisExecutor module (CoreAgent handles streaming)

---

### Step 3: Simplify Fallback Logic

**File**: `completion/fallback_summary.py`

**Purpose**: User-friendly summary when synthesis fails or no Execute output

**Function**:
```python
def generate_user_fallback_summary(
    state: LoopState,
    plan_result: PlanResult,
) -> str:
    """Generate user-friendly fallback summary (RFC-211 / IG-199).

    NEVER leak internal evidence_summary to users.
    Generate user-friendly completion summary instead.

    Args:
        state: Loop state with step_results.
        plan_result: Plan result with full_output or next_action.

    Returns:
        User-friendly summary text.
    """
    if plan_result.full_output:
        return plan_result.full_output

    if state.step_results:
        successful_count = sum(1 for r in state.step_results if r.success)
        total_count = len(state.step_results)
        return f"Completed {successful_count}/{total_count} steps successfully. {plan_result.next_action or ''}"

    return plan_result.next_action or "Goal achieved successfully"
```

**Delete**:
- goal_completion.py orchestrator (logic moved to policy + synthesis)
- completion_strategies.py (4 strategies → 3 branches in policy)
- response_categorizer.py (merged into synthesis)
- synthesis_executor.py (merged into synthesis)

---

### Step 4: Update Planner Integration

**File**: `core/planner.py`

**Changes**:
- No changes to planner (already calls `determine_goal_completion_needs()`)
- Planner sets `plan_result.require_goal_completion` (hybrid decision)
- Completion logic will call new `determine_completion_action()`

---

### Step 5: Update AgentLoop Integration

**File**: `agent_loop.py` (main loop)

**Current** (using GoalCompletionModule):
```python
completion_module = GoalCompletionModule(core_agent, planner_model, config)
plan_result, stream_gen = await completion_module.complete_goal(goal, state, plan_result)
```

**New** (using consolidated functions):
```python
# Import consolidated modules
from soothe.cognition.agent_loop.policies.goal_completion_policy import (
    determine_completion_action,
)
from soothe.cognition.agent_loop.analysis.synthesis import SynthesisGenerator
from soothe.cognition.agent_loop.completion.fallback_summary import (
    generate_user_fallback_summary,
)

# 1. Decision: determine action
synthesis_gen = SynthesisGenerator(planner_model, core_agent)
length_category = synthesis_gen.categorize_response_length(state)
action, precomputed_text = determine_completion_action(
    state, plan_result, config.final_response_mode, length_category.value
)

# 2. Execution: based on action
stream_gen = None
final_output = None

if action == "skip":
    final_output = precomputed_text
elif action == "direct":
    final_output = precomputed_text
elif action == "synthesize":
    stream_gen = synthesis_gen.generate_synthesis(goal, state, plan_result, length_category)
    # Collect stream to get final text (CoreAgent accumulation)
    final_output = await _collect_stream_final_text(stream_gen)
elif action == "summary":
    final_output = generate_user_fallback_summary(state, plan_result)

# 3. Update PlanResult
updated_result = plan_result.model_copy(
    update={
        "full_output": final_output,
        "response_length_category": length_category.value,
    }
)

# 4. Return stream (if synthesis) or empty generator
return updated_result, stream_gen or _empty_generator()
```

---

### Step 6: Delete Unused Modules

**Files to Delete**:
```
completion/goal_completion.py          (orchestrator - logic moved)
completion/response_categorizer.py     (merged into synthesis)
completion/synthesis_executor.py       (merged into synthesis)
completion/completion_strategies.py    (merged into policy)
completion/__init__.py                 (update exports)
```

**Files to Update**:
```
completion/__init__.py  → export generate_user_fallback_summary only
analysis/synthesis.py   → replace SynthesisPhase with SynthesisGenerator
policies/goal_completion_policy.py → add determine_completion_action()
policies/synthesis_policy.py → DELETE (merged into goal_completion_policy)
```

---

### Step 7: Update Tests

**Delete**:
- `tests/unit/cognition/agent_loop/completion/test_response_categorizer.py`
- `tests/unit/cognition/agent_loop/completion/test_synthesis_executor.py`
- `tests/unit/cognition/agent_loop/completion/test_completion_strategies.py`
- `tests/unit/cognition/agent_loop/policies/test_synthesis_policy.py`

**Add**:
- `tests/unit/cognition/agent_loop/policies/test_goal_completion_policy.py` (extend with action tests)
- `tests/unit/cognition/agent_loop/analysis/test_synthesis_generator.py` (new generator tests)
- `tests/unit/cognition/agent_loop/completion/test_fallback_summary.py` (new fallback tests)

**Update**:
- `tests/unit/cognition/agent_loop/completion/test_goal_completion_module.py` → delete (module removed)

---

### Step 8: Verification

```bash
./scripts/verify_finally.sh
```

Expected results:
- Code formatting: pass
- Linting: 0 errors
- Unit tests: 900+ tests pass (reduced from deletions, added new tests)

---

## Success Criteria

- ✅ 8 files → 3 files (62% reduction)
- ✅ 1,085 lines → ~400 lines (75% reduction)
- ✅ 5 layers → 3 layers (clear responsibility)
- ✅ No duplicate goal classification
- ✅ No duplicate streaming logic
- ✅ Strategy pattern removed
- ✅ IG-298 hybrid approach maintained
- ✅ All tests pass
- ✅ Decision logic unit-testable in policy module
- ✅ Execution logic unit-testable in synthesis module

---

## Benefits

**Simplicity**: 3 clear modules vs 8 interdependent ones
**Performance**: Fewer object allocations, less abstraction overhead
**Testability**: Single decision function, single generator class, single fallback
**Maintainability**: No mirror decision trees, no duplicate regex patterns
**Clarity**: Policy decides → Synthesis executes → Fallback summarizes

---

## References

- RFC-615: Goal Completion Module Architecture
- IG-298: Hybrid decision policy (LLM primary + execution heuristics)
- IG-297: Goal completion module (current overdesigned implementation)
- IG-296: Synthesis policy module (merged into goal_completion_policy)
- RFC-211: Goal completion fallback summary (never leak evidence_summary)