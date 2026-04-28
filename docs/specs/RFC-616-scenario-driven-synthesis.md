# RFC-616: Scenario-Driven Goal Completion Synthesis

**Status**: Draft
**Created**: 2026-04-28
**Related**: RFC-603, RFC-615, IG-298, IG-299

## Abstract

Refactor goal completion synthesis from keyword-driven, length-categorized system to scenario-driven, adaptive synthesis generation. The new system uses intent classification and execution patterns to determine appropriate deliverable structure, with LLM self-judging depth and detail level based on goal context and evidence.

## Motivation

### Current Limitations

1. **Artificial goal_type concept**: Uses keyword-based classification (`architecture_analysis`, `research_synthesis`, etc.) derived from evidence regex patterns - narrow, brittle, and domain-specific
2. **Response length constraints**: Enforces word count categories (BRIEF/CONCISE/STANDARD/COMPREHENSIVE) that artificially limit synthesis depth without understanding goal context
3. **Generic synthesis prompts**: "Summarize what was accomplished" approach produces uniform outputs regardless of goal type
4. **Keyword-based rules**: Heavily relies on regex pattern matching for goal classification, incompatible with general agent philosophy

### Proposed Solution

Replace keyword-based classification and length constraints with:

- **Scenario-driven synthesis**: Different deliverable structures for different goal types (architecture design vs travel plan vs research synthesis)
- **Intent + execution pattern matching**: Classification uses `IntentClassification` and execution metadata, not regex
- **Adaptive depth control**: LLM self-judges appropriate detail level from goal + evidence + scenario structure
- **Extensible scenario library**: Built-in templates for common scenarios + LLM-designed templates for novel cases
- **General agent compatible**: Works across diverse domains without domain-specific keyword logic

## Specification

### Core Components

#### 1. ScenarioClassifier (Phase 1)

**Purpose**: Determine appropriate synthesis scenario from goal + intent + execution pattern

**Model**: Fast model from configuration (optimized for structured classification)

**Input**:
- `goal`: User's goal description
- `intent_type`: Intent classification (chitchat/quiz/thread_continuation/new_goal)
- `task_complexity`: Task complexity level (chitchat/quiz/medium/complex)
- `execution_summary`: Execution metadata (total_steps, successful_steps, step_types, tools_used, evidence_volume)

**Output Schema**:
```python
class ScenarioClassification(BaseModel):
    scenario: str                 # Built-in scenario name or "custom"
    sections: list[str]           # Section names for synthesis structure
    contextual_focus: list[str]   # 2-3 specific focus areas for this goal
    evidence_emphasis: str        # How to use execution evidence
```

**Built-in Scenarios** (minimal templates):
1. `code_architecture_design` - ["Summary", "Component Analysis", "Key Findings", "Recommendations"]
2. `code_implementation_design` - ["Approach", "Implementation Details", "Code Examples", "Usage Guide"]
3. `research_synthesis` - ["Executive Summary", "Key Findings", "Source Analysis", "Conclusions"]
4. `travel_activity_plan` - ["Overview", "Itinerary", "Logistics", "Recommendations"]
5. `tutorial_guide` - ["Introduction", "Prerequisites", "Steps", "Tips"]
6. `analysis_report` - ["Executive Summary", "Metrics/Findings", "Trends", "Recommendations"]
7. `investigation_summary` - ["Problem Statement", "Investigation Process", "Findings", "Resolution"]
8. `decision_analysis` - ["Context", "Options", "Trade-offs", "Recommendation"]
9. `content_draft` - ["Introduction", "Body", "Conclusion"]
10. `general_summary` - ["Summary", "Key Points"]

**Matching Logic**: Execution pattern provides discriminative signal:
- web_search + fetch_url → Research Synthesis
- file_read + grep + ls → Code Architecture/Investigation (intent determines which)
- execute + shell → Implementation Design
- subagent calls → Complex scenarios (Investigation/Analysis)
- No tools/light tools → General Summary

#### 2. SynthesisGenerator (Phase 2)

**Modified Flow**:
1. Extract evidence from successful step results
2. Call ScenarioClassifier → get classification
3. Build synthesis prompt from classification (no length constraints)
4. Stream via CoreAgent

**Prompt Structure**:
```
Generate a {scenario} synthesis for the goal: {goal}

SCENARIO STRUCTURE:
Sections: {sections}

CONTEXTUAL FOCUS:
{contextual_focus (bullet list)}

EVIDENCE EMPHASIS:
{evidence_emphasis}

EXECUTION EVIDENCE:
{evidence}

INSTRUCTIONS:
1. Follow the scenario structure - address each section purposefully
2. Focus on the contextual areas identified above
3. Judge appropriate depth and detail level based on the goal and evidence
4. Extract and present actual content from tool results
5. Be concrete and actionable
6. Use the full execution history available in the conversation context
```

### Integration Architecture

```
Goal Completion Flow:
Execute Phase → generates evidence
    ↓
Plan Phase → decides synthesis needed
    ↓
Goal Completion Decision → skip/direct/synthesize
    ↓
SynthesisGenerator:
    Phase 1: ScenarioClassifier
        - Input: goal + intent + execution_summary
        - Output: scenario + sections + contextual_focus
    
    Phase 2: Build Prompt + Stream
        - Uses classification
        - No length constraints
    ↓
Final Synthesis Response
```

### Removal of Legacy Components

**Deleted**:
- `policies/response_length_policy.py` (entire file)
- `ResponseLengthCategory` enum
- `determine_response_length()` function
- `calculate_evidence_metrics()` function (moved to classifier input)
- `_infer_goal_type_from_intent()` method
- `categorize_response_length()` method
- `_get_length_guidance()` method
- Keyword constants (`_MIN_DIRECTORIES_FOR_ARCHITECTURE`, etc.)
- `response_length_category` field from `PlanResult`

**Modified**:
- `SynthesisGenerator.generate_synthesis()` - remove `length_category` parameter
- `SynthesisGenerator._build_synthesis_prompt()` - use classification instead of goal_type/length_category
- `agent_loop.py` - remove length categorization call

## Implementation Details

### File Structure

**New**:
- `analysis/scenario_classifier.py` - ScenarioClassifier implementation + ScenarioClassification schema + BUILTIN_SCENARIOS constant

**Modified**:
- `analysis/synthesis.py` - Remove keyword classification, integrate classifier
- `core/agent_loop.py` - Remove length categorization step
- `state/schemas.py` - Remove response_length_category from PlanResult

**Deleted**:
- `policies/response_length_policy.py` - Entire file

### Error Handling

**Classifier Failure**:
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

**No Intent Available**:
```python
intent_type = "new_goal"
task_complexity = "medium"
if state.intent and hasattr(state.intent, "intent_type"):
    intent_type = state.intent.intent_type
    task_complexity = getattr(state.intent, "task_complexity", "medium")
```

**Empty Evidence**:
```python
evidence = self._extract_evidence(state)
if not evidence:
    evidence = "No execution evidence available (goal completed without tools)"
```

## Testing Requirements

### Unit Tests

**ScenarioClassifier**:
- Mock execution summaries for each built-in scenario type
- Built-in scenario matching (architecture goal + file_read → code_architecture_design)
- Custom scenario generation (novel goal → custom sections)
- Contextual_focus quality (specific to goal, not generic)
- Evidence_emphasis generation

**SynthesisGenerator**:
- Prompt construction with classification
- Evidence extraction (unchanged behavior)
- Fallback handling (classifier failure → general_summary)

### Integration Tests

**End-to-end Synthesis**:
- Architecture goals → code_architecture_design scenario + proper sections
- Research goals → research_synthesis scenario + source analysis
- Travel planning → travel_activity_plan scenario + itinerary
- Novel goals → custom scenario generation with appropriate sections
- Empty evidence handling
- Depth self-judgment quality (varying evidence volume)

### Removed Tests

Delete all tests for:
- `ResponseLengthCategory` enum
- `determine_response_length()` function
- `calculate_evidence_metrics()` function
- `categorize_response_length()` method

## Migration Path

1. **Phase 1: Preparation**
   - Create `analysis/scenario_classifier.py` with classifier logic
   - Add `BUILTIN_SCENARIOS` constant
   - Add `ScenarioClassification` schema
   - Write unit tests for classifier

2. **Phase 2: Integration**
   - Modify `SynthesisGenerator` to use classifier
   - Remove length categorization logic
   - Update synthesis prompt template
   - Update `agent_loop.py` to remove length_category

3. **Phase 3: Cleanup**
   - Delete `policies/response_length_policy.py`
   - Remove `response_length_category` from `PlanResult`
   - Remove related tests
   - Update imports across codebase
   - Run full verification suite

4. **Phase 4: Validation**
   - Run integration tests with diverse goals
   - Validate scenario matching accuracy
   - Validate synthesis quality (sections + depth)
   - Compare outputs with current system

## Success Criteria

1. **No keyword rules**: Classification uses intent + execution pattern, not regex matching
2. **Scenario-appropriate outputs**: Architecture goals → architecture design structure, research → research synthesis structure
3. **Adaptive depth**: LLM self-judges detail level based on goal + evidence
4. **Novel scenario handling**: Goals outside built-in library get custom-designed templates
5. **Quality improvement**: Synthesis outputs more structured and actionable than current generic prompts
6. **General agent compatibility**: Works across domains without domain-specific logic

## Future Extensions

1. **Plugin-defined scenarios**: Allow plugins to register custom scenario templates
2. **User preferences**: Learn preferred synthesis styles per user/goal type
3. **Multi-scenario synthesis**: Complex goals with multiple deliverable components
4. **Section-level templates**: Richer guidance per section (beyond names)
5. **Quality metrics**: Measure synthesis quality (structure adherence, evidence usage, actionability)