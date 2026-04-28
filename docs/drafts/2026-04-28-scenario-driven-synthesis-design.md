# Scenario-Driven Goal Completion Synthesis Design

**Date**: 2026-04-28
**Status**: Design Draft
**Related**: RFC-603, RFC-615, IG-298, IG-299

## Overview

Refactor goal completion synthesis from keyword-driven, length-categorized system to scenario-driven, adaptive synthesis generation. The new system uses intent + execution patterns to determine appropriate deliverable structure, with LLM self-judging depth and detail level.

## Problem Statement

### Current Issues

1. **Artificial goal_type concept**: Uses keyword-based classification (`architecture_analysis`, `research_synthesis`, etc.) from evidence patterns - narrow and brittle
2. **Response length categories**: Enforces word count constraints (BRIEF/CONCISE/STANDARD/COMPREHENSIVE) that artificially limit synthesis depth
3. **Generic synthesis prompts**: "Summarize what was accomplished" approach doesn't match diverse user goals
4. **Keyword-based rules**: Heavily relies on regex patterns for goal classification, incompatible with general agent philosophy

### Desired Outcome

- **Scenario-driven synthesis**: Different deliverable structures for different goal types (architecture design vs travel plan vs research synthesis)
- **No keyword rules**: Intent + execution pattern determine scenario, not regex matching
- **Adaptive depth**: LLM judges appropriate detail level from goal + evidence, not artificial word count limits
- **Extensible**: Built-in templates for common scenarios + LLM-designed templates for novel cases
- **General agent compatible**: Works across diverse domains without domain-specific keyword logic

## Architecture

### Two-Phase System

**Phase 1 (Scenario Discovery)**: Fast model analyzes goal + execution → suggests scenario template with contextual focus
**Phase 2 (Content Generation)**: LLM generates synthesis following scenario template + contextual guidance

### Key Components

```
Goal Completion Flow:
┌─────────────────────┐
│ Execute Phase       │
│ (generates evidence)│
└─────────────────────┘
          ↓
┌─────────────────────┐
│ Plan Phase          │
│ (decides synthesis) │
└─────────────────────┘
          ↓
┌─────────────────────┐
│ Goal Completion     │
│ Decision            │
│ (skip/direct/synth) │
└─────────────────────┘
          ↓
┌─────────────────────────────────────┐
│ SynthesisGenerator                  │
│                                     │
│  1. ScenarioClassifier (Phase 1)   │
│     - Input: goal + intent +       │
│       execution_summary            │
│     - Output: scenario + sections  │
│       + contextual_focus           │
│                                     │
│  2. Build Prompt (Phase 2)         │
│     - Uses classification          │
│     - No length constraints        │
│                                     │
│  3. Stream via CoreAgent           │
│                                     │
└─────────────────────────────────────┘
          ↓
┌─────────────────────┐
│ Final Synthesis     │
│ Response            │
└─────────────────────┘
```

## Phase 1: ScenarioClassifier

### Location

Inside `SynthesisGenerator` class or separate module in `analysis/scenario_classifier.py`

### Model

Fast model from configuration (optimized for structured classification)

### Input Schema

```python
ScenarioClassifierInput = {
    "goal": str,                      # User's goal description
    "intent_type": str,               # chitchat/quiz/thread_continuation/new_goal
    "task_complexity": str,           # chitchat/quiz/medium/complex
    "execution_summary": {
        "total_steps": int,
        "successful_steps": int,
        "step_types": list[str],      # Outcome types from step results
        "tools_used": list[str],      # Aggregated from outcomes
        "evidence_volume": int        # Character count
    }
}
```

### Output Schema

```python
class ScenarioClassification(BaseModel):
    """Scenario classification result for synthesis generation."""

    scenario: str                     # Built-in name or "custom"
    sections: list[str]               # Section names for synthesis structure
    contextual_focus: list[str]       # 2-3 specific focus areas for this goal
    evidence_emphasis: str            # How to use execution evidence

    @model_validator(mode="after")
    def validate_sections(self) -> ScenarioClassification:
        """Ensure sections are provided."""
        if not self.sections:
            raise ValueError("sections must be provided")
        return self
```

### Built-in Scenario Templates

Minimal template structure (scenario name + sections only):

```python
BUILTIN_SCENARIOS = {
    "code_architecture_design": [
        "Summary",
        "Component Analysis",
        "Key Findings",
        "Recommendations"
    ],
    "code_implementation_design": [
        "Approach",
        "Implementation Details",
        "Code Examples",
        "Usage Guide"
    ],
    "research_synthesis": [
        "Executive Summary",
        "Key Findings",
        "Source Analysis",
        "Conclusions"
    ],
    "travel_activity_plan": [
        "Overview",
        "Itinerary",
        "Logistics",
        "Recommendations"
    ],
    "tutorial_guide": [
        "Introduction",
        "Prerequisites",
        "Steps",
        "Tips"
    ],
    "analysis_report": [
        "Executive Summary",
        "Metrics/Findings",
        "Trends",
        "Recommendations"
    ],
    "investigation_summary": [
        "Problem Statement",
        "Investigation Process",
        "Findings",
        "Resolution"
    ],
    "decision_analysis": [
        "Context",
        "Options",
        "Trade-offs",
        "Recommendation"
    ],
    "content_draft": [
        "Introduction",
        "Body",
        "Conclusion"
    ],
    "general_summary": [
        "Summary",
        "Key Points"
    ]
}
```

### Classification Prompt Template

```
Analyze the goal and execution pattern to determine the most appropriate synthesis scenario.

GOAL: {goal}
INTENT: {intent_type} (complexity: {task_complexity})

EXECUTION SUMMARY:
- Total steps: {total_steps}
- Successful: {successful_steps}
- Step types: {step_types}
- Tools used: {tools_used}
- Evidence volume: {evidence_volume} chars

AVAILABLE BUILT-IN SCENARIOS:
1. code_architecture_design - System/module structure analysis
2. code_implementation_design - Concrete implementation patterns and examples
3. research_synthesis - Multi-source information gathering and findings
4. travel_activity_plan - Structured planning for trips, events, activities
5. tutorial_guide - Step-by-step instructional content
6. analysis_report - Data/metrics/trends analysis with recommendations
7. investigation_summary - Problem/troubleshooting investigation process
8. decision_analysis - Options comparison with trade-offs
9. content_draft - Blog, documentation, proposal, email drafts
10. general_summary - Simple summarization fallback

TASK:
1. Match goal + execution pattern to a built-in scenario if appropriate
2. If novel situation not covered above → return "custom" scenario with designed sections
3. Generate 2-3 contextual_focus areas specific to THIS goal (not generic)
4. Generate evidence_emphasis instruction for how to use execution results effectively

OUTPUT FORMAT (JSON):
{
    "scenario": "<scenario_name from above OR custom>",
    "sections": ["<section1>", "<section2>", "<section3>", ...],
    "contextual_focus": [
        "<specific focus area 1 for this goal>",
        "<specific focus area 2 for this goal>",
        "<specific focus area 3 for this goal>"
    ],
    "evidence_emphasis": "<instruction for using evidence>"
}

EXAMPLE OUTPUT:
{
    "scenario": "code_architecture_design",
    "sections": ["Summary", "Component Analysis", "Key Findings", "Recommendations"],
    "contextual_focus": [
        "Compare monolithic vs modular approach",
        "Highlight dependency bottlenecks",
        "Quantify component complexity metrics"
    ],
    "evidence_emphasis": "Include module relationship diagrams and code snippets showing key dependencies"
}

ANOTHER EXAMPLE (custom):
{
    "scenario": "custom",
    "sections": ["Recipe Overview", "Ingredient Analysis", "Cooking Instructions", "Recommendations"],
    "contextual_focus": [
        "Group recipes by cuisine and difficulty",
        "Identify common ingredient substitutions",
        "Provide time-based recommendations"
    ],
    "evidence_emphasis": "Include full recipe content, ingredient lists, and cooking times from web search results"
}
```

### Matching Logic

Classifier uses execution pattern as discriminative signal:

- **web_search + fetch_url** → Research Synthesis
- **file_read + grep + ls** → Code Architecture/Investigation (goal intent determines which)
- **execute + shell** → Implementation Design
- **subagent calls** → Complex scenarios (Investigation/Analysis)
- **No tools/light tools** → General Summary

Execution summary provides context without full evidence parsing, ideal for fast model.

## Phase 2: Synthesis Generation

### Modified Flow

```python
async def generate_synthesis(
    self,
    goal: str,
    state: LoopState,
    plan_result: PlanResult,
) -> AsyncGenerator:
    """Generate synthesis via CoreAgent streaming.

    Args:
        goal: Goal description.
        state: Loop state with thread context.
        plan_result: Plan result (reserved for future hints).

    Returns:
        Async generator yielding stream chunks.
    """
    _ = plan_result  # Reserved for future use

    # Extract evidence
    evidence = self._extract_evidence(state)

    # Phase 1: Classify scenario
    classification = await self._classify_scenario(goal, state)

    # Phase 2: Build synthesis prompt from classification
    prompt = self._build_synthesis_prompt(goal, evidence, classification)

    # Create human message
    human_msg = LoopHumanMessage(
        content=prompt,
        thread_id=state.thread_id,
        iteration=state.iteration,
        goal_summary=state.goal[:200] if state.goal else None,
        phase="goal_completion",
    )

    logger.info(
        "Synthesis generator: scenario=%s sections=%d evidence_chars=%d",
        classification.scenario,
        len(classification.sections),
        len(evidence),
    )

    # Stream via CoreAgent
    async for chunk in self.core_agent.astream(
        {"messages": [human_msg]},
        config={"configurable": {"thread_id": state.thread_id}},
        stream_mode=["messages"],
        subgraphs=False,
    ):
        yield ("goal_completion_stream", chunk)
```

### Simplified Prompt Template

```python
def _build_synthesis_prompt(
    self,
    goal: str,
    evidence: str,
    classification: ScenarioClassification,
) -> str:
    """Build synthesis prompt from scenario classification.

    Args:
        goal: Goal description.
        evidence: Concatenated evidence from successful steps.
        classification: Scenario classification from Phase 1.

    Returns:
        Complete synthesis prompt text.
    """
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
   - ToolMessage.content contains the actual file content, search results, etc.
   - For file reading: show the actual file content (with line numbers if applicable)
   - For web/research: show actual search results or fetched content
5. Be concrete and actionable - show findings, not just confirmations
6. Use the full execution history available in the conversation context"""
```

### Key Differences from Current System

**Removed**:
- `goal_type` parameter and keyword-based classification
- `length_category` parameter and word count constraints
- Length guidance sections (`_get_length_guidance()`)
- Evidence volume/diversity metrics for depth control

**Added**:
- `classification` parameter with scenario + sections + contextual_focus
- LLM self-judges depth from goal + evidence + scenario structure
- Structured focus areas guide synthesis content
- Evidence emphasis instruction tailored to scenario

## Integration Points

### File Changes

**1. `analysis/synthesis.py`**
- Remove: `_infer_goal_type_from_intent()`
- Remove: `categorize_response_length()`
- Remove: `_get_length_guidance()`
- Remove: keyword constants (`_MIN_DIRECTORIES_FOR_ARCHITECTURE`, etc.)
- Remove: regex imports (no `import re`)
- Add: `ScenarioClassifier` class or `_classify_scenario()` method
- Add: `ScenarioClassification` schema (or import from separate module)
- Add: `BUILTIN_SCENARIOS` constant dictionary
- Modify: `generate_synthesis()` signature (remove `length_category` parameter)
- Modify: `_build_synthesis_prompt()` signature and implementation

**2. `policies/response_length_policy.py`**
- **DELETE ENTIRE FILE**
  - Remove `ResponseLengthCategory` enum
  - Remove `determine_response_length()` function
  - Remove `calculate_evidence_metrics()` function

**3. `core/agent_loop.py`**
- Remove: `synthesis_gen.categorize_response_length()` call (lines ~336-337)
- Remove: `length_category` parameter from `synthesis_gen.generate_synthesis()` call (line ~372-373)
- Simplify: Goal completion flow (remove length categorization step)

**4. `state/schemas.py`**
- Remove: `response_length_category` field from `PlanResult` (line ~132)

**5. Optional: `analysis/scenario_classifier.py`**
- New file if separating classifier logic
- Contains `ScenarioClassification` schema
- Contains `classify_synthesis_scenario()` function
- Contains `BUILTIN_SCENARIOS` constant

### Import Updates

```python
# analysis/synthesis.py (after changes)
from soothe.cognition.agent_loop.state.schemas import LoopState, PlanResult
from soothe.cognition.agent_loop.utils.messages import LoopHumanMessage

# Removed imports:
# from soothe.cognition.agent_loop.policies.response_length_policy import (
#     ResponseLengthCategory,
#     calculate_evidence_metrics,
#     determine_response_length,
# )
# import re  # No longer needed

# Optional new import if separate module:
# from soothe.cognition.agent_loop.analysis.scenario_classifier import (
#     ScenarioClassification,
#     classify_synthesis_scenario,
# )
```

## Error Handling

### Edge Cases

**No intent classification available**:
```python
# Fallback values
intent_type = "new_goal"
task_complexity = "medium"
if state.intent and hasattr(state.intent, "intent_type"):
    intent_type = state.intent.intent_type
    task_complexity = getattr(state.intent, "task_complexity", "medium")
```

**Empty evidence**:
```python
evidence = self._extract_evidence(state)
if not evidence:
    evidence = "No execution evidence available (goal completed without tools)"
```

**Classifier fails**:
```python
try:
    classification = await self._classify_scenario(goal, state)
except Exception:
    logger.warning("Scenario classification failed, using fallback")
    classification = ScenarioClassification(
        scenario="general_summary",
        sections=["Summary", "Key Points"],
        contextual_focus=["Provide concise summary of goal completion"],
        evidence_emphasis="Use any available tool results or AI responses"
    )
```

**Novel scenario design fails**:
- Classifier should always return valid sections
- Pydantic validator ensures `sections` list is non-empty
- Fallback to `general_summary` if validation fails

## Testing Strategy

### Unit Tests

**ScenarioClassifier tests** (`tests/unit/cognition/agent_loop/analysis/scenario_classifier.py`):
- Mock execution summaries for each built-in scenario type
- Test built-in scenario matching (architecture goal + file_read → code_architecture_design)
- Test custom scenario generation (novel goal → custom sections)
- Test contextual_focus quality (specific to goal, not generic)
- Test evidence_emphasis generation

**SynthesisGenerator tests** (`tests/unit/cognition/agent_loop/analysis/synthesis.py`):
- Test prompt construction with classification
- Test evidence extraction (unchanged)
- Test fallback handling (classifier failure → general_summary)

### Integration Tests

**End-to-end synthesis** (`tests/integration/cognition/agent_loop/core/agent_loop.py`):
- Architecture goals → code_architecture_design scenario + proper sections
- Research goals → research_synthesis scenario + source analysis
- Travel planning → travel_activity_plan scenario + itinerary
- Novel goals → custom scenario generation with appropriate sections
- Empty evidence handling
- Depth self-judgment quality (varying evidence volume)

### Removed Tests

- **DELETE**: All tests for `ResponseLengthCategory`
- **DELETE**: All tests for `determine_response_length()`
- **DELETE**: All tests for `calculate_evidence_metrics()`
- **DELETE**: All tests for `categorize_response_length()`

## Migration Plan

### Phase 1: Preparation

1. Create `analysis/scenario_classifier.py` with classifier logic
2. Add `BUILTIN_SCENARIOS` constant
3. Add `ScenarioClassification` schema
4. Write unit tests for classifier

### Phase 2: Integration

1. Modify `SynthesisGenerator` to use classifier
2. Remove length categorization logic
3. Update synthesis prompt template
4. Update `agent_loop.py` to remove length_category

### Phase 3: Cleanup

1. Delete `policies/response_length_policy.py`
2. Remove `response_length_category` from `PlanResult`
3. Remove related tests
4. Update imports across codebase
5. Run full verification suite

### Phase 4: Validation

1. Run integration tests with diverse goals
2. Validate scenario matching accuracy
3. Validate synthesis quality (sections + depth)
4. Compare outputs with current system (should be more structured and scenario-appropriate)

## Success Criteria

1. **No keyword rules**: Classification uses intent + execution pattern, not regex
2. **Scenario-appropriate outputs**: Architecture goals → architecture design structure, research → research synthesis structure
3. **Adaptive depth**: LLM self-judges detail level based on goal + evidence
4. **Novel scenario handling**: Goals outside built-in library get custom-designed templates
5. **Quality improvement**: Synthesis outputs more structured and actionable than current generic prompts
6. **General agent compatibility**: Works across domains without domain-specific logic

## Risks and Mitigations

**Risk 1**: Classifier matches wrong scenario for ambiguous goals
- **Mitigation**: Execution pattern provides discriminative signal, classifier designed to use both intent + execution
- **Test**: Integration tests with ambiguous goals (e.g., "analyze codebase" → architecture vs investigation)

**Risk 2**: Custom scenario designs are poor quality
- **Mitigation**: Classifier uses fast model with structured output, Pydantic validation ensures sections present
- **Test**: Unit tests for custom scenario generation quality

**Risk 3**: LLM depth self-judgment inconsistent
- **Mitigation**: Contextual focus areas + evidence emphasis provide guidance, goal context constrains interpretation
- **Test**: Integration tests varying evidence volume, compare depth quality

**Risk 4**: Breaking existing synthesis behavior
- **Mitigation**: `general_summary` fallback maintains simple summarization capability
- **Test**: Comparison testing with current system outputs

## Future Enhancements

1. **Plugin-defined scenarios**: Allow plugins to register custom scenario templates
2. **User preferences**: Learn preferred synthesis styles per user/goal type
3. **Multi-scenario synthesis**: Complex goals with multiple deliverable components
4. **Section-level templates**: Richer guidance per section (beyond names)
5. **Quality metrics**: Measure synthesis quality (structure adherence, evidence usage, actionability)