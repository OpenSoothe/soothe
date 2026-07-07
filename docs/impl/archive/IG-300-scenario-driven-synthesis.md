# IG-300: Scenario-Driven Goal Completion Synthesis Implementation

**Status**: Draft
**Created**: 2026-04-28
**RFC**: RFC-616
**Related**: IG-298, IG-299

## Overview

Implement scenario-driven synthesis system replacing keyword-based classification and length categorization with intent + execution pattern matching and LLM-designed templates for novel cases.

## Implementation Tasks

### Task 1: Create ScenarioClassifier Module

**File**: `packages/soothe/src/soothe/cognition/agent_loop/analysis/scenario_classifier.py`

**Components**:
1. `ScenarioClassification` schema (Pydantic model)
2. `BUILTIN_SCENARIOS` constant dictionary
3. `classify_synthesis_scenario()` async function
4. `_build_classifier_prompt()` helper function
5. `_extract_execution_summary()` helper function

**Implementation Notes**:
- Use fast model from config (cheaper, faster classification)
- Structured output with Pydantic validation
- Fallback to `general_summary` on classification failure
- Execution summary aggregation from `state.step_results`

**Built-in Scenarios**:
```python
BUILTIN_SCENARIOS = {
    "code_architecture_design": ["Summary", "Component Analysis", "Key Findings", "Recommendations"],
    "code_implementation_design": ["Approach", "Implementation Details", "Code Examples", "Usage Guide"],
    "research_synthesis": ["Executive Summary", "Key Findings", "Source Analysis", "Conclusions"],
    "travel_activity_plan": ["Overview", "Itinerary", "Logistics", "Recommendations"],
    "tutorial_guide": ["Introduction", "Prerequisites", "Steps", "Tips"],
    "analysis_report": ["Executive Summary", "Metrics/Findings", "Trends", "Recommendations"],
    "investigation_summary": ["Problem Statement", "Investigation Process", "Findings", "Resolution"],
    "decision_analysis": ["Context", "Options", "Trade-offs", "Recommendation"],
    "content_draft": ["Introduction", "Body", "Conclusion"],
    "general_summary": ["Summary", "Key Points"]
}
```

**Execution Summary Extraction**:
```python
def _extract_execution_summary(state: LoopState) -> dict:
    """Extract execution metadata from state."""
    total_steps = len(state.step_results)
    successful_steps = sum(1 for r in state.step_results if r.success)

    step_types = []
    tools_used = []
    for result in state.step_results:
        outcome_type = result.outcome.get("type", "unknown")
        step_types.append(outcome_type)

        # Extract tools from outcome metadata
        tool_name = result.outcome.get("tool_name")
        if tool_name:
            tools_used.append(tool_name)

    evidence_volume = sum(
        len(result.to_evidence_string(truncate=False))
        for result in state.step_results
        if result.success
    )

    return {
        "total_steps": total_steps,
        "successful_steps": successful_steps,
        "step_types": step_types,
        "tools_used": tools_used,
        "evidence_volume": evidence_volume
    }
```

**Classification Function**:
```python
async def classify_synthesis_scenario(
    goal: str,
    state: LoopState,
    llm_client: BaseChatModel
) -> ScenarioClassification:
    """Classify synthesis scenario from goal + intent + execution."""
    # Extract intent
    intent_type = "new_goal"
    task_complexity = "medium"
    if state.intent and hasattr(state.intent, "intent_type"):
        intent_type = state.intent.intent_type
        task_complexity = getattr(state.intent, "task_complexity", "medium")

    # Extract execution summary
    execution_summary = _extract_execution_summary(state)

    # Build classifier prompt
    prompt = _build_classifier_prompt(goal, intent_type, task_complexity, execution_summary)

    # Call LLM with structured output
    try:
        response = await llm_client.ainvoke(prompt)
        classification = ScenarioClassification.parse_raw(response.content)
        return classification
    except Exception:
        logger.warning("Scenario classification failed, using fallback")
        return ScenarioClassification(
            scenario="general_summary",
            sections=BUILTIN_SCENARIOS["general_summary"],
            contextual_focus=["Provide concise summary of goal completion"],
            evidence_emphasis="Use any available tool results or AI responses"
        )
```

---

### Task 2: Refactor SynthesisGenerator

**File**: `packages/soothe/src/soothe/cognition/agent_loop/analysis/synthesis.py`

**Changes**:

1. **Remove**:
   - `_infer_goal_type_from_intent()` method (keyword-based logic)
   - `categorize_response_length()` method
   - `_get_length_guidance()` method
   - Keyword constants (`_MIN_DIRECTORIES_FOR_ARCHITECTURE`, etc.)
   - Regex import (`import re`)
   - ResponseLengthPolicy imports

2. **Add**:
   - Import `ScenarioClassification` from `scenario_classifier`
   - Import `classify_synthesis_scenario` from `scenario_classifier`
   - `_classify_scenario()` async method (wraps classifier)
   - `BUILTIN_SCENARIOS` constant (or import)

3. **Modify**:
   - `generate_synthesis()` signature - remove `length_category` parameter
   - `generate_synthesis()` flow - call classifier first, then build prompt
   - `_build_synthesis_prompt()` - use `ScenarioClassification` instead of goal_type/length_category

**New Flow**:
```python
async def generate_synthesis(
    self,
    goal: str,
    state: LoopState,
    plan_result: PlanResult,
) -> AsyncGenerator:
    """Generate synthesis via CoreAgent streaming."""
    _ = plan_result

    # Extract evidence
    evidence = self._extract_evidence(state)

    # Phase 1: Classify scenario
    classification = await self._classify_scenario(goal, state)

    # Phase 2: Build synthesis prompt from classification
    prompt = self._build_synthesis_prompt(goal, evidence, classification)

    # Create human message
    human_msg = LoopHumanMessage(...)

    logger.info(
        "Synthesis generator: scenario=%s sections=%d evidence_chars=%d",
        classification.scenario,
        len(classification.sections),
        len(evidence),
    )

    # Stream via CoreAgent
    async for chunk in self.core_agent.astream(...):
        yield ("goal_completion_stream", chunk)
```

**New Prompt Builder**:
```python
def _build_synthesis_prompt(
    self,
    goal: str,
    evidence: str,
    classification: ScenarioClassification,
) -> str:
    """Build synthesis prompt from scenario classification."""
    focus_items = "\n".join(f"- {focus}" for focus in classification.contextual_focus)

    return f"""Generate a {classification.scenario} synthesis for the goal: {goal}

SCENARIO STRUCTURE:
Sections: {', '.join(classification.sections)}

CONTEXTUAL FOCUS:
{focus_items}

EVIDENCE EMPHASIS:
{classification.evidence_emphasis}

EXECUTION EVIDENCE:
{evidence}

INSTRUCTIONS:
1. Follow the scenario structure - address each section purposefully
2. Focus on the contextual areas identified above
3. Judge appropriate depth and detail level based on the goal and evidence
4. Extract and present actual content from tool results (file contents, search results, etc.)
5. Be concrete and actionable - show findings, not just confirmations
6. Use the full execution history available in the conversation context"""
```

**Classifier Wrapper**:
```python
async def _classify_scenario(self, goal: str, state: LoopState) -> ScenarioClassification:
    """Wrap classifier with error handling."""
    try:
        return await classify_synthesis_scenario(goal, state, self.llm)
    except Exception:
        logger.warning("Classifier failed, using fallback")
        return ScenarioClassification(
            scenario="general_summary",
            sections=["Summary", "Key Points"],
            contextual_focus=["Provide concise summary"],
            evidence_emphasis="Use any available tool results"
        )
```

---

### Task 3: Delete Response Length Policy

**File**: `packages/soothe/src/soothe/cognition/agent_loop/policies/response_length_policy.py`

**Action**: **DELETE ENTIRE FILE**

**Removed Components**:
- `ResponseLengthCategory` enum
- `determine_response_length()` function
- `calculate_evidence_metrics()` function
- All related tests

---

### Task 4: Update AgentLoop Integration

**File**: `packages/soothe/src/soothe/cognition/agent_loop/core/agent_loop.py`

**Changes**:

1. **Remove**:
   - `synthesis_gen.categorize_response_length()` call (~lines 336-337)
   - `length_category` parameter from `synthesis_gen.generate_synthesis()` (~line 372-373)
   - Intent/complexity extraction for length categorization

2. **Simplify**:
   - Goal completion flow - no length categorization step
   - Pass only `goal, state, plan_result` to `generate_synthesis()`

**Before**:
```python
# 2. Categorize response length
intent_type = "new_goal"
task_complexity = "medium"
if state.intent and hasattr(state.intent, "intent_type"):
    intent_type = state.intent.intent_type
    task_complexity = getattr(state.intent, "task_complexity", "medium")

length_category = synthesis_gen.categorize_response_length(
    state, intent_type, task_complexity
)

# ... later ...

async for chunk in synthesis_gen.generate_synthesis(
    goal, state, plan_result, length_category
):
```

**After**:
```python
# No length categorization step

# ... later ...

async for chunk in synthesis_gen.generate_synthesis(
    goal, state, plan_result
):
```

---

### Task 5: Update PlanResult Schema

**File**: `packages/soothe/src/soothe/cognition/agent_loop/state/schemas.py`

**Changes**:

1. **Remove**:
   - `response_length_category` field from `PlanResult` (~line 132)

**Before**:
```python
class PlanResult(BaseModel):
    ...
    response_length_category: str | None = None
    """Response length category for synthesis. IG-268."""
```

**After**:
```python
class PlanResult(BaseModel):
    ...
    # response_length_category field removed
```

---

### Task 6: Update Analysis Package Exports

**File**: `packages/soothe/src/soothe/cognition/agent_loop/analysis/__init__.py`

**Changes**:

1. **Add**:
   - Import `ScenarioClassification` from `scenario_classifier`
   - Export `ScenarioClassification` in `__all__`

**Updated __init__.py**:
```python
"""Analysis and intelligence components."""

from .failure_analyzer import FailureAnalyzer
from .metadata_generator import generate_outcome_metadata
from .synthesis import SynthesisGenerator
from .scenario_classifier import ScenarioClassification

__all__ = [
    "FailureAnalyzer",
    "generate_outcome_metadata",
    "SynthesisGenerator",
    "ScenarioClassification",
]
```

---

## Testing Plan

### Unit Tests

**New**: `packages/soothe/tests/unit/cognition/agent_loop/analysis/scenario_classifier.py`

Test cases:
1. Mock execution summaries for each built-in scenario
2. Built-in matching (architecture goal + file_read → code_architecture_design)
3. Custom scenario generation (novel goal → custom sections)
4. Contextual_focus quality validation
5. Evidence_emphasis generation
6. Classifier failure fallback
7. Empty evidence handling

**Modified**: `packages/soothe/tests/unit/cognition/agent_loop/analysis/synthesis.py`

Test cases:
1. Prompt construction with classification
2. Evidence extraction (unchanged)
3. Classifier integration
4. Fallback handling

**Deleted**: All tests referencing:
- `ResponseLengthCategory`
- `determine_response_length()`
- `calculate_evidence_metrics()`
- `categorize_response_length()`

### Integration Tests

**Modified**: `packages/soothe/tests/integration/cognition/agent_loop/core/agent_loop.py`

Test scenarios:
1. Architecture goal → code_architecture_design scenario + sections
2. Research goal → research_synthesis scenario + source analysis
3. Travel planning → travel_activity_plan scenario + itinerary
4. Novel goal → custom scenario with appropriate sections
5. Empty evidence handling
6. Depth self-judgment quality

---

## Verification Checklist

After implementation:

1. **Code Quality**:
   - No linting errors (`make lint`)
   - Proper formatting (`make format-check`)
   - Type hints on all public functions
   - Google-style docstrings

2. **Tests**:
   - All unit tests pass (`make test-unit`)
   - Integration tests pass
   - No test failures referencing removed components

3. **Imports**:
   - No imports of deleted `response_length_policy`
   - Proper imports of new `scenario_classifier`
   - No unused imports

4. **Integration**:
   - `agent_loop.py` synthesis calls simplified
   - `PlanResult` schema updated
   - `SynthesisGenerator` methods removed/added correctly

5. **Logging**:
   - Classifier logs scenario + sections + evidence_chars
   - No logs referencing length_category

---

## Implementation Order

1. Create `scenario_classifier.py` with schema + constant + functions
2. Modify `synthesis.py` to remove old logic and integrate classifier
3. Delete `response_length_policy.py`
4. Update `agent_loop.py` integration
5. Update `schemas.py` PlanResult
6. Update `analysis/__init__.py` exports
7. Write/modify unit tests
8. Write/modify integration tests
9. Run `./scripts/verify_finally.sh`
10. Fix any lint/test failures

---

## Success Criteria

1. No keyword-based classification logic
2. No regex imports in synthesis.py
3. No length_category in synthesis calls
4. ScenarioClassifier produces valid classifications
5. Synthesis outputs match scenario structure
6. All tests pass
7. Linting passes with zero errors