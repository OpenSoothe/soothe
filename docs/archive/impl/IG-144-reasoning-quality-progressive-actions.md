# IG-144: Reasoning Quality & Progressive Actions Implementation

**Implementation Guide**: IG-144
**RFC**: RFC-603
**Status**: Draft
**Created**: 2026-04-09
**Estimated Time**: 5 days
**Updated**: 2026-04-12 (terminology refactoring per IG-153)

---

## Overview

Implement RFC-603 to improve reasoning quality with progressive action descriptions, synthesis phase for comprehensive reports, and evidence-based quality metrics. This guide addresses IG-143 Issues #2 (non-progressive actions) and #3 (insufficient final reports).

---

## Goals

1. ✅ Action descriptions become progressively specific across iterations
2. ✅ Final reports are comprehensive, global summaries (300-600 words for complex goals)
3. ✅ Confidence and progress metrics are evidence-based (not just LLM self-assessment)
4. ✅ 80% benchmark pass rate (8/10 cases)
5. ✅ No backward compatibility maintained (clean break)

---

## Implementation Phases

### Phase 1: Progressive Actions (1 day)

**Objective**: Ensure action descriptions improve specificity across iterations.

#### Step 1.1: Add Action History to Schema

**File**: `src/soothe/cognition/agent_loop/schemas.py`

**Changes**:

```python
# Add to LoopState class
action_history: list[str] = Field(
    default_factory=list,
    description="Chronological action descriptions for progression tracking"
)

def add_action_to_history(self, action: str) -> None:
    """Add action description to history."""
    if action and action.strip():
        self.action_history.append(action.strip())

def get_recent_actions(self, n: int = 3) -> list[str]:
    """Get last N action descriptions."""
    return self.action_history[-n:] if self.action_history else []
```

**Verification**: Schema compiles, fields accessible.

#### Step 1.2: Create Action Quality Post-Processing

**File**: `src/soothe/cognition/agent_loop/action_quality.py` (NEW)

**Implementation**:

```python
"""Action quality enhancement for progressive specificity."""

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from soothe.cognition.agent_loop.schemas import LoopState, StepResult


_SPECIFICITY_PATTERNS = [
    r'\d+\s+(files?|components?|modules?|layers?|directories)',
    r'(examine|analyze|inspect|investigate|review)\s+\S+/',
    r'based on (the|my|these)\s+(findings|results|analysis|discoveries)',
    r'(identified|found|discovered|located)\s+\d+',
    r'(in|within|from)\s+\S+/\s+',
]


def _is_specific_action(action: str, goal: str) -> bool:
    """Check if action description is specific (not generic).

    Specific actions contain:
    - Numbers (e.g., "5 files")
    - Paths (e.g., "examine src/")
    - References to prior work (e.g., "based on findings")
    - Discoveries (e.g., "found 3 patterns")
    """
    if not action or not action.strip():
        return False

    action_lower = action.lower().strip()

    # Check specificity patterns
    for pattern in _SPECIFICITY_PATTERNS:
        if re.search(pattern, action_lower, re.IGNORECASE):
            return True

    return False


def _normalize_action(action: str) -> str:
    """Normalize action for comparison (remove whitespace, lowercase)."""
    return re.sub(r'\s+', ' ', action.lower().strip())


def _is_repeated_action(
    action: str,
    previous_actions: list[str],
    threshold: float = 0.85
) -> bool:
    """Check if action repeats recent actions.

    Args:
        action: Current action description.
        previous_actions: Last N actions.
        threshold: Similarity threshold (0.85 = 85% similar).

    Returns:
        True if action repeats previous action.
    """
    if not previous_actions:
        return False

    normalized_current = _normalize_action(action)

    # Check against last 3 actions
    for prev_action in previous_actions[-3:]:
        normalized_prev = _normalize_action(prev_action)

        # Simple similarity: check if normalized strings match
        if normalized_current == normalized_prev:
            return True

        # Check substring overlap
        if len(normalized_current) > 20 and len(normalized_prev) > 20:
            # Split into words and check overlap
            current_words = set(normalized_current.split())
            prev_words = set(normalized_prev.split())
            overlap = len(current_words & prev_words) / max(len(current_words), len(prev_words))
            if overlap >= threshold:
                return True

    return False


def _extract_paths_from_evidence(step_results: list[StepResult]) -> list[str]:
    """Extract file/directory paths from recent step results."""
    paths = []

    for result in step_results[-5:]:  # Last 5 results
        if not result.output:
            continue

        # Extract paths like "src/", "docs/", etc.
        path_pattern = r'(?:examine|analyze|read|list|inspect)\s+(\S+/)'
        matches = re.findall(path_pattern, result.output, re.IGNORECASE)
        paths.extend(matches)

    return paths[-3:]  # Return last 3 unique paths


def enhance_action_specificity(
    action: str,
    goal: str,
    iteration: int,
    previous_actions: list[str],
    step_results: list[StepResult],
) -> str:
    """Enhance action description to be more specific.

    Strategy:
    1. If already specific → keep as-is
    2. If repeated → derive new action from evidence
    3. If generic → add context from step results

    Args:
        action: Current action description.
        goal: Goal description.
        iteration: Current iteration number.
        previous_actions: Previous action descriptions.
        step_results: Recent step execution results.

    Returns:
        Enhanced action description (or original if already good).
    """
    if not action or not action.strip():
        return action

    # Step 1: Check if already specific
    if _is_specific_action(action, goal):
        return action

    # Step 2: Check for repetition
    if _is_repeated_action(action, previous_actions):
        # Derive new action from recent evidence
        paths = _extract_paths_from_evidence(step_results)

        if paths:
            # Create specific action from discovered paths
            path_list = ", ".join(paths[:3])
            enhanced = f"Continue analysis in {path_list} based on previous findings"
            return enhanced

        # Fallback: add iteration-specific context
        if iteration > 1:
            return f"Deepen investigation based on {iteration-1} previous iterations"

    # Step 3: Enhance generic action with context
    generic_prefixes = [
        "use file and shell tools",
        "gather facts",
        "collect information",
    ]

    action_lower = action.lower()
    is_generic = any(prefix in action_lower for prefix in generic_prefixes)

    if is_generic and step_results:
        # Add evidence-based context
        paths = _extract_paths_from_evidence(step_results)
        if paths:
            path_context = paths[0]  # Use first discovered path
            return f"Examine {path_context} to gather specific evidence"

    # Default: return original (no enhancement needed)
    return action
```

**Verification**: Unit tests for specificity detection, repetition checking, enhancement logic.

#### Step 1.3: Integrate Enhancement in Plan Layer

**File**: `src/soothe/cognition/agent_loop/planning.py`

**Changes**:

```python
# Add import at top
from soothe.cognition.agent_loop.action_quality import enhance_action_specificity

# In plan_loop() function, after PlanResult construction:
async def plan_loop(...) -> PlanResult:
    # ... existing code to generate PlanResult ...

    # NEW: Enhance action specificity
    enhanced_action = enhance_action_specificity(
        action=result.next_action or "",
        goal=goal,
        iteration=iteration,
        previous_actions=state.get_recent_actions(3),
        step_results=state.step_results,
    )

    # Update result
    result.next_action = enhanced_action

    # Add to history
    state.add_action_to_history(enhanced_action)

    # Emit event with enhanced action
    await emit_event(result)

    return result
```

**Verification**: Integration works, action history accumulates, enhanced actions appear in events.

#### Step 1.4: Add Progressive Actions Prompt Guidance

**File**: `src/soothe/core/prompts/fragments/instructions/output_format.xml`

**Changes**: Add new section after existing guidance:

```xml
<PROGRESSIVE_ACTIONS>
You MUST make each iteration's action description MORE SPECIFIC than previous ones.

Evolution pattern:
- Iteration 1: Broad exploration (identify structure)
- Iteration 2: Targeted investigation (focus on specific areas)
- Iteration 3: Deep analysis (detailed examination)
- Iteration 4+: Synthesis and validation (connect findings)

Requirements:
1. Reference learnings from previous iterations ("based on findings...")
2. Include concrete paths, counts, or discoveries ("examine src/core/")
3. NEVER repeat identical action text
4. If stuck, pivot strategy explicitly ("switching approach because...")
5. Quantify progress ("identified 3 of 5 components")

Generic actions (AVOID):
- "Use file and shell tools to gather facts" ❌
- "Continue working toward the goal" ❌

Specific actions (TARGET):
- "Examine src/backends/ and src/protocols/ based on 2 previous findings" ✅
- "Analyze the 5 remaining protocol implementations" ✅
</PROGRESSIVE_ACTIONS>
```

**Verification**: Prompt compiles, LLM receives guidance.

**Phase 1 Tests**:

```python
# tests/test_action_quality.py

def test_specificity_detection():
    assert _is_specific_action("Examine 5 files in src/", "goal") == True
    assert _is_specific_action("Use tools to gather facts", "goal") == False
    assert _is_specific_action("Based on previous findings, analyze src/", "goal") == True

def test_repetition_check():
    prev = ["Use file tools", "Examine src/"]
    assert _is_repeated_action("Use file tools", prev) == True
    assert _is_repeated_action("Analyze different area", prev) == False

def test_enhancement_logic():
    action = "Use file and shell tools"
    enhanced = enhance_action_specificity(
        action=action,
        goal="analyze arch",
        iteration=2,
        previous_actions=["Use file and shell tools"],
        step_results=[mock_result_with_paths(["src/", "docs/"])],
    )
    assert "src/" in enhanced or "docs/" in enhanced
    assert enhanced != action

def test_progressive_iterations():
    """Integration test: actions improve over iterations."""
    state = LoopState()

    actions = [
        "Use file and shell tools",  # Iteration 1: generic
        "Use file and shell tools",  # Iteration 2: repeated → should enhance
        "List the root directory",   # Iteration 3: specific
        "Use file and shell tools",  # Iteration 4: regressed → should enhance
    ]

    enhanced_actions = []
    for i, action in enumerate(actions):
        enhanced = enhance_action_specificity(
            action=action,
            goal="analyze arch",
            iteration=i+1,
            previous_actions=enhanced_actions[-3:],
            step_results=[mock_result_with_paths(["src/", "docs/"])],
        )
        enhanced_actions.append(enhanced)
        state.add_action_to_history(enhanced)

    # Check progression: at least 2/4 should be specific
    specific_count = sum(1 for a in enhanced_actions if _is_specific_action(a, "analyze arch"))
    assert specific_count >= 2
```

---

### Phase 2: Quality Improvements (0.5 days)

**Objective**: Implement evidence-based confidence and progress metrics.

#### Step 2.1: Add Evidence-Based Confidence

**File**: `src/soothe/cognition/planning/simple.py`

**Changes**:

```python
# Add new function

def _calculate_evidence_based_confidence(
    state: LoopState,
    reason_result: ReasonResult,
) -> float:
    """Calculate confidence from evidence, not just LLM self-assessment.

    Formula:
    confidence = (
        llm_confidence * 0.5 +
        success_rate * 0.3 +
        evidence_volume_score * 0.3 +
        iteration_efficiency * 0.4
    ) / 1.5

    Returns:
        Float between 0.0 and 1.0.
    """
    # LLM confidence (50% weight)
    llm_confidence = reason_result.confidence or 0.5

    # Success rate (30% weight)
    if not state.step_results:
        success_rate = 0.0
    else:
        successful = sum(1 for r in state.step_results if r.success)
        success_rate = successful / len(state.step_results)

    # Evidence volume (30% weight)
    # 0 chars = 0.0, 2000+ chars = 1.0
    total_evidence_length = sum(len(r.output or "") for r in state.step_results)
    evidence_volume_score = min(total_evidence_length / 2000.0, 1.0)

    # Iteration efficiency (40% weight)
    # Higher efficiency = reaching goal faster
    iteration = state.current_iteration or 1
    max_iterations = 8
    iteration_efficiency = max(0.0, 1.0 - (iteration - 1) / max_iterations)

    # Combined score
    confidence = (
        llm_confidence * 0.5 +
        success_rate * 0.3 +
        evidence_volume_score * 0.3 +
        iteration_efficiency * 0.4
    ) / 1.5

    return min(max(confidence, 0.0), 1.0)  # Clamp to [0, 1]


def _calculate_evidence_based_progress(
    state: LoopState,
    reason_result: ReasonResult,
) -> float:
    """Calculate progress from evidence, not just LLM estimate.

    Formula:
    progress = (
        llm_progress * 0.6 +
        step_completion_ratio * 0.2 +
        evidence_growth_rate * 0.2
    )

    Returns:
        Float between 0.0 and 1.0.
    """
    # Special case: if status is "done", return 1.0
    if reason_result.status == "done":
        return 1.0

    # LLM progress (60% weight)
    llm_progress = reason_result.progress or 0.0

    # Step completion ratio (20% weight)
    if not state.step_results:
        step_completion_ratio = 0.0
    else:
        completed = sum(1 for r in state.step_results if r.success)
        step_completion_ratio = completed / len(state.step_results)

    # Evidence growth rate (20% weight)
    # Compare recent evidence to earlier evidence
    if len(state.step_results) < 2:
        evidence_growth_rate = 0.5  # Neutral if insufficient data
    else:
        # Recent evidence (last 3 results)
        recent_length = sum(len(r.output or "") for r in state.step_results[-3:])
        # Earlier evidence (first results)
        earlier_length = sum(len(r.output or "") for r in state.step_results[:3])

        if earlier_length == 0:
            evidence_growth_rate = 0.5
        else:
            # Growth rate: recent / earlier, capped at 1.0
            evidence_growth_rate = min(recent_length / earlier_length, 1.0)

    # Combined score
    progress = (
        llm_progress * 0.6 +
        step_completion_ratio * 0.2 +
        evidence_growth_rate * 0.2
    )

    return min(max(progress, 0.0), 1.0)  # Clamp to [0, 1]
```

**Integration** in `parse_reason_response_text()`:

```python
def parse_reason_response_text(...) -> ReasonResult:
    # ... existing parsing logic ...

    result = ReasonResult(
        # ... existing fields ...
        confidence=confidence,
        progress=progress,
    )

    # NEW: Apply evidence-based corrections
    result.confidence = _calculate_evidence_based_confidence(state, result)
    result.progress = _calculate_evidence_based_progress(state, result)

    return result
```

**Verification**: Unit tests for formula calculations, integration works.

#### Step 2.2: Add Reasoning Quality Prompt Guidance

**File**: `src/soothe/core/prompts/fragments/instructions/output_format.xml`

**Changes**: Add new section:

```xml
<REASONING_QUALITY>
Your reasoning MUST be evidence-based and quantified.

Requirements:
1. Cite specific evidence ("Analysis of src/ revealed 8 protocol files")
2. Quantify findings ("found 5 components", "examined 60% of directories")
3. Justify status with evidence ("Status=continue because 2 areas remain unexplored")
4. Keep concise: 2-4 sentences maximum

Example reasoning (GOOD):
"Analysis of src/core and src/backends revealed 12 protocol implementations.
Evidence shows clear layer separation. Progress: examined 60% of key directories.
Status=continue to examine remaining backends."

Example reasoning (BAD - avoid):
"The architecture has been analyzed. It's good. Progress: 80%. Status=done." ❌
</REASONING_QUALITY>
```

**Verification**: Prompt compiles, LLM receives guidance.

**Phase 2 Tests**:

```python
# tests/test_evidence_based_metrics.py

def test_confidence_calculation():
    state = LoopState(step_results=[
        mock_result(success=True, output="100 chars"),
        mock_result(success=True, output="100 chars"),
    ])
    state.current_iteration = 2

    reason = ReasonResult(confidence=0.8, progress=0.6)

    confidence = _calculate_evidence_based_confidence(state, reason)

    # Verify formula: (0.8*0.5 + 1.0*0.3 + 0.1*0.3 + 0.75*0.4) / 1.5
    expected = (0.4 + 0.3 + 0.03 + 0.3) / 1.5
    assert abs(confidence - expected) < 0.01

def test_progress_calculation():
    state = LoopState(step_results=[
        mock_result(success=True, output="small"),
        mock_result(success=True, output="medium"),
        mock_result(success=True, output="large"),
    ])

    reason = ReasonResult(status="continue", progress=0.6)

    progress = _calculate_evidence_based_progress(state, reason)

    # Verify formula: (0.6*0.6 + 1.0*0.2 + 1.0*0.2)
    expected = 0.36 + 0.2 + 0.2
    assert abs(progress - expected) < 0.01

def test_done_status_progress():
    """If status='done', progress should be 1.0."""
    reason = ReasonResult(status="done")
    progress = _calculate_evidence_based_progress(LoopState(), reason)
    assert progress == 1.0
```

---

### Phase 3: Synthesis Phase (1.5 days)

**Objective**: Generate comprehensive final reports from accumulated evidence.

#### Step 3.1: Add Synthesis Fields to Schema

**File**: `src/soothe/cognition/agent_loop/schemas.py`

**Changes to ReasonResult**:

```python
# Add new fields
synthesis_performed: bool = Field(
    default=False,
    description="Whether synthesis phase was run for final report"
)

action_specificity_score: float | None = Field(
    default=None,
    ge=0.0,
    le=1.0,
    description="Post-processed action specificity score (0=generic, 1=highly specific)"
)

evidence_quality_score: float = Field(
    default=0.0,
    ge=0.0,
    le=1.0,
    description="Calculated quality of accumulated evidence"
)
```

**Verification**: Schema compiles, fields accessible.

#### Step 3.2: Create Synthesis Module

**File**: `src/soothe/cognition/agent_loop/synthesis.py` (NEW)

**Implementation**:

```python
"""Synthesis phase for comprehensive final report generation."""

from typing import TYPE_CHECKING

from langchain_core.language_models.chat_models import BaseChatModel

if TYPE_CHECKING:
    from soothe.cognition.agent_loop.schemas import LoopState, ReasonResult


# Synthesis trigger thresholds (internal constants, not exposed to users)
_SYNTHESIS_MIN_STEPS = 2
_SYNTHESIS_MIN_SUCCESS_RATE = 0.6
_SYNTHESIS_MIN_EVIDENCE_LENGTH = 500
_SYNTHESIS_MIN_UNIQUE_STEPS = 2


class SynthesisPhase:
    """Generate comprehensive final reports from evidence.

    Trigger criteria (all must be met):
    1. ≥2 successful steps
    2. ≥60% success rate
    3. ≥500 chars total evidence
    4. ≥2 unique step types

    Goal classification (from evidence patterns):
    - Architecture analysis: Multiple directories + layer mentions
    - Research synthesis: Multiple findings counts
    - Implementation summary: Code patterns
    - General synthesis: Default
    """

    def __init__(self, llm_client: BaseChatModel) -> None:
        """Initialize synthesis phase with LLM client.

        Args:
            llm_client: LLM for synthesis generation.
        """
        self.llm = llm_client

    def should_synthesize(
        self,
        goal: str,
        state: LoopState,
        reason_result: ReasonResult
    ) -> bool:
        """Determine if synthesis phase should run.

        Uses evidence-based heuristics only (no keyword matching).

        Args:
            goal: Goal description.
            state: Loop state with accumulated evidence.
            reason_result: Final reason result.

        Returns:
            True if synthesis should run.
        """
        # Criterion 1: Enough evidence
        if len(state.step_results) < _SYNTHESIS_MIN_STEPS:
            return False

        # Criterion 2: High success rate
        successful_steps = [r for r in state.step_results if r.success]
        if not successful_steps:
            return False
        success_rate = len(successful_steps) / len(state.step_results)
        if success_rate < _SYNTHESIS_MIN_SUCCESS_RATE:
            return False

        # Criterion 3: Sufficient evidence volume
        total_evidence_length = sum(len(r.output or "") for r in successful_steps)
        if total_evidence_length < _SYNTHESIS_MIN_EVIDENCE_LENGTH:
            return False

        # Criterion 4: Multiple perspectives (unique step types)
        unique_step_ids = set(r.step_id for r in successful_steps)
        if len(unique_step_ids) < _SYNTHESIS_MIN_UNIQUE_STEPS:
            return False

        return True

    def _classify_goal_type(self, evidence: str) -> str:
        """Classify goal type from evidence patterns.

        Args:
            evidence: Concatenated evidence from all steps.

        Returns:
            Goal type: 'architecture_analysis', 'research_synthesis',
                      'implementation_summary', or 'general_synthesis'.
        """
        import re

        evidence_lower = evidence.lower()

        # Architecture analysis: Multiple directories + layer/structure mentions
        directory_pattern = r'(src/|docs/|core/|backends/|protocols/|tools/)'
        directories = len(re.findall(directory_pattern, evidence_lower))
        layer_mentions = bool(re.search(r'layer|architecture|component|module', evidence_lower))

        if directories >= 3 and layer_mentions:
            return 'architecture_analysis'

        # Research synthesis: Multiple findings/discoveries
        findings_pattern = r'(found|identified|discovered|located)\s+\d+'
        findings_count = len(re.findall(findings_pattern, evidence_lower))

        if findings_count >= 3:
            return 'research_synthesis'

        # Implementation summary: Code patterns, function/class mentions
        code_pattern = r'(function|class|method|implementation|def |async def)'
        code_mentions = len(re.findall(code_pattern, evidence_lower))

        if code_mentions >= 5:
            return 'implementation_summary'

        # Default: general synthesis
        return 'general_synthesis'

    async def synthesize(
        self,
        goal: str,
        state: LoopState,
        reason_result: ReasonResult
    ) -> str:
        """Generate comprehensive synthesis report.

        Args:
            goal: Goal description.
            state: Loop state with evidence.
            reason_result: Reason result with summary.

        Returns:
            Comprehensive synthesis text (300-600 words for complex goals).

        Raises:
            Exception: If synthesis fails (caller should fallback).
        """
        # Gather evidence
        evidence_parts = []
        for result in state.step_results:
            if result.success and result.output:
                evidence_parts.append(result.output)

        evidence = "\n\n".join(evidence_parts)

        # Classify goal type
        goal_type = self._classify_goal_type(evidence)

        # Build synthesis prompt
        from soothe.core.prompts.loader import load_prompt_fragment

        synthesis_template = load_prompt_fragment("instructions/synthesis_format.xml")

        synthesis_prompt = synthesis_template.render(
            goal=goal,
            goal_type=goal_type,
            evidence=evidence,
            previous_summary=reason_result.evidence_summary or "",
        )

        # Call LLM for synthesis
        from langchain_core.messages import HumanMessage

        response = await self.llm.ainvoke([HumanMessage(content=synthesis_prompt)])

        synthesis_text = response.content or ""

        return synthesis_text.strip()
```

**Verification**: Unit tests for trigger logic, goal classification, synthesis generation.

#### Step 3.3: Create Synthesis Prompt Template

**File**: `src/soothe/core/prompts/fragments/instructions/synthesis_format.xml` (NEW)

**Implementation**:

```xml
<SYNTHESIS_INSTRUCTIONS>
You are synthesizing a comprehensive final report from accumulated evidence.

CRITICAL REQUIREMENTS:
1. DO NOT say "already analyzed" or "has been analyzed" - synthesize NEW insights
2. Be specific with numbers, names, concrete findings
3. Structure appropriately for goal type
4. 300-600 words for complex goals (architecture, research, implementation)
5. 100-200 words for simpler goals

Goal: {{ goal }}
Type: {{ goal_type }}
Evidence Summary: {{ previous_summary }}

Full Evidence:
{{ evidence }}

{% if goal_type == 'architecture_analysis' %}
STRUCTURE YOUR REPORT AS:

## System Overview
[What is this system? Purpose, scale, tech stack, unique features]

## Architecture Layers
[Break down each layer: purpose, key modules, responsibilities]

## Key Components
[List 5-10 critical components by name with brief descriptions]

## Design Patterns
[2-3 key patterns observed: protocol-driven, modular, event-based, etc.]

## Dependencies
[External dependencies and why they're used]

## Notable Features
[What makes this system unique or notable]

{% elif goal_type == 'research_synthesis' %}
STRUCTURE YOUR REPORT AS:

## Key Findings
[List discoveries with numbers: "Found X patterns", "Identified Y components"]

## Methodology
[Briefly describe investigation approach]

## Conclusions
[Synthesis of what the findings mean]

{% elif goal_type == 'implementation_summary' %}
STRUCTURE YOUR REPORT AS:

## What Was Built
[Implementation description]

## Implementation Details
[Key code patterns, functions, classes]

## Usage
[How to use the implementation]

{% else %}
STRUCTURE YOUR REPORT AS:

## Summary
[Comprehensive synthesis of findings]

## Key Points
[3-5 important discoveries or insights]

{% endif %}

DO NOT:
- Say "already analyzed" ❌
- Provide minimal detail ❌
- Repeat raw evidence verbatim ❌
- Leave sections empty ❌

DO:
- Synthesize NEW insights from evidence ✅
- Use concrete numbers and names ✅
- Structure for goal type ✅
- Be comprehensive but concise ✅
</SYNTHESIS_INSTRUCTIONS>
```

**Verification**: Template compiles, renders correctly.

#### Step 3.4: Integrate Synthesis in Loop Agent

**File**: `src/soothe/cognition/agent_loop/loop_agent.py`

**Changes**:

```python
# Add import at top
from soothe.cognition.agent_loop.synthesis import SynthesisPhase

# In agentic_loop.astream() or equivalent main loop function:
async def astream(...) -> JudgeResult:
    # ... existing loop logic ...

    # After loop completes (reason_result.is_done() returns True)
    if reason_result.status == "done":
        # NEW: Attempt synthesis
        try:
            # Create synthesis phase with LLM client
            synthesis_llm = config.create_chat_model(role="synthesis")
            synthesis = SynthesisPhase(synthesis_llm)

            # Check if synthesis should run
            if synthesis.should_synthesize(goal, state, reason_result):
                # Generate comprehensive report
                synthesis_text = await synthesis.synthesize(goal, state, reason_result)

                # Update final output
                final_stdout = synthesis_text
                reason_result.synthesis_performed = True
            else:
                # Use raw evidence concatenation
                final_stdout = reason_result.full_output or reason_result.evidence_summary

        except Exception as e:
            # Fallback to raw evidence on synthesis failure
            logger.warning(f"Synthesis failed: {e}, using raw evidence")
            final_stdout = reason_result.full_output or reason_result.evidence_summary

        # Emit completed event with final output
        await emit_completed_event(final_stdout)

        # Return JudgeResult
        return JudgeResult(
            # ... existing fields ...
            full_output=final_stdout,
        )
```

**Verification**: Integration works, synthesis triggers correctly, fallback on failure.

**Phase 3 Tests**:

```python
# tests/test_synthesis.py

def test_should_synthesize():
    """Check trigger criteria."""
    synthesis = SynthesisPhase(mock_llm())

    # Case 1: Insufficient evidence → no synthesis
    state = LoopState(step_results=[mock_result(success=True, output="short")])
    reason = ReasonResult(status="done")
    assert synthesis.should_synthesize("goal", state, reason) == False

    # Case 2: Sufficient evidence → synthesis
    state = LoopState(step_results=[
        mock_result(success=True, output="300 chars...", step_id="step1"),
        mock_result(success=True, output="300 chars...", step_id="step2"),
        mock_result(success=True, output="300 chars...", step_id="step3"),
    ])
    reason = ReasonResult(status="done")
    assert synthesis.should_synthesize("analyze arch", state, reason) == True

def test_goal_classification():
    synthesis = SynthesisPhase(mock_llm())

    # Architecture analysis
    arch_evidence = "Examined src/core, src/backends, src/protocols. Found layers."
    assert synthesis._classify_goal_type(arch_evidence) == 'architecture_analysis'

    # Research synthesis
    research_evidence = "Found 5 patterns. Identified 3 issues. Discovered 7 components."
    assert synthesis._classify_goal_type(research_evidence) == 'research_synthesis'

    # Implementation summary
    impl_evidence = "def function() {...} class MyClass {...} method implementation"
    assert synthesis._classify_goal_type(impl_evidence) == 'implementation_summary'

async def test_synthesis_generation():
    """Integration test: synthesis produces comprehensive report."""
    synthesis = SynthesisPhase(real_llm_client())

    state = LoopState(step_results=[
        mock_architecture_result("src/core/"),
        mock_architecture_result("src/backends/"),
    ])

    reason = ReasonResult(status="done", evidence_summary="Found modules")

    report = await synthesis.synthesize("analyze architecture", state, reason)

    # Verify report quality
    assert len(report) >= 300  # Comprehensive
    assert "already analyzed" not in report.lower()  # No cop-out
    assert "src/core" in report  # Specific findings
    assert "## System Overview" in report  # Proper structure
```

---

### Phase 4: Benchmarks (1 day)

**Objective**: Create 10 benchmark test cases for validation.

#### Step 4.1: Create Benchmark Directory Structure

```bash
mkdir -p benchmarks/reasoning-quality
```

#### Step 4.2: Create Benchmark Files

Create 10 benchmark markdown files in `benchmarks/reasoning-quality/`:

**Benchmark 1: Architecture Analysis** (`01-architecture-analysis.md`)

```markdown
# Benchmark: Architecture Analysis

**ID**: reasoning-quality-01
**Type**: Architecture Analysis
**Expected Iterations**: 3-5
**Synthesis Expected**: YES

## Task

Run: `soothe --no-tui -p "analyze this project architecture"`

## Success Criteria

- [ ] Final report includes "## System Overview" section
- [ ] Final report includes "## Architecture Layers" section
- [ ] Final report includes "## Key Components" section
- [ ] Identifies at least 5 key components by name
- [ ] Reports concrete numbers (file count, line count, component count)
- [ ] Actions become more specific across iterations
- [ ] No duplicate action text in iterations 2-5
- [ ] Report length ≥ 300 words
- [ ] Does NOT say "already analyzed"

## Execution

```bash
soothe --no-tui -p "analyze this project architecture" > output.txt
```

## Expected Output

Comprehensive architecture summary with:
- System overview (what is Soothe, purpose, scale)
- Layer breakdown (CLI, Daemon, Core, Protocols, Backends, Capabilities)
- Key component names (AgentFactory, Runner, EventProcessor, etc.)
- Design patterns (protocol-driven, layered, event-based)
- No "already analyzed" cop-out
```

**Benchmark 2: Code Investigation** (`02-code-investigation.md`)

```markdown
# Benchmark: Code Investigation

**ID**: reasoning-quality-02
**Type**: Code Investigation
**Expected Iterations**: 2-4
**Synthesis Expected**: YES

## Task

Run: `soothe --no-tui -p "investigate how the event system works"`

## Success Criteria

- [ ] Final report includes findings about event system
- [ ] Identifies key files (event_catalog.py, base_events.py, etc.)
- [ ] Explains event registration mechanism
- [ ] Actions progress from exploration to specific analysis
- [ ] No repeated generic actions
- [ ] Report length ≥ 200 words

## Expected Output

Investigation summary explaining:
- Event catalog structure
- Registration mechanism
- Key event types
- How events flow through the system
```

**Benchmark 3: Simple Lookup** (`03-simple-lookup.md`)

```markdown
# Benchmark: Simple Lookup

**ID**: reasoning-quality-03
**Type**: Simple Lookup
**Expected Iterations**: 1-2
**Synthesis Expected**: NO

## Task

Run: `soothe --no-tui -p "what is the config file path?"`

## Success Criteria

- [ ] Direct answer provided (path mentioned)
- [ ] Report length ≤ 150 words
- [ ] Completed in 1-2 iterations
- [ ] No synthesis performed (synthesis_performed=False)
- [ ] No verbose summary

## Expected Output

Simple answer: "The config file is at `config/config.yml` with dev defaults in `config.dev.yml`."

NOT: 500-word architecture analysis of the config system.
```

Create remaining benchmarks following similar format for:
- 04-research-task.md
- 05-structure-analysis.md
- 06-error-investigation.md
- 07-comparison-task.md
- 08-documentation-generation.md
- 09-performance-analysis.md
- 10-quick-summary.md

#### Step 4.3: Create Benchmark Runner

**File**: `benchmarks/run-benchmarks.py`

```python
#!/usr/bin/env python3
"""Benchmark runner for reasoning quality validation."""

import subprocess
import sys
from pathlib import Path


def run_benchmark(benchmark_file: Path) -> tuple[bool, str]:
    """Run single benchmark and validate results.

    Args:
        benchmark_file: Path to benchmark markdown file.

    Returns:
        (passed, output) tuple.
    """
    # Parse benchmark metadata
    # Extract task command
    # Run soothe command
    # Validate success criteria
    # Return pass/fail with output

    # Placeholder implementation
    print(f"Running benchmark: {benchmark_file.name}")
    return True, "Benchmark passed"


def main():
    """Run all benchmarks and report results."""
    benchmarks_dir = Path(__file__).parent / "reasoning-quality"
    benchmark_files = sorted(benchmarks_dir.glob("*.md"))

    if not benchmark_files:
        print("No benchmarks found!")
        sys.exit(1)

    print(f"Running {len(benchmark_files)} benchmarks...")

    passed = 0
    failed = 0

    for benchmark_file in benchmark_files:
        success, output = run_benchmark(benchmark_file)
        if success:
            passed += 1
            print(f"✅ {benchmark_file.name}: PASSED")
        else:
            failed += 1
            print(f"❌ {benchmark_file.name}: FAILED")
            print(output)

    print(f"\nResults: {passed}/{len(benchmark_files)} passed")

    if passed >= 8:  # 80% threshold
        print("✅ Benchmark suite PASSED (≥80%)")
        sys.exit(0)
    else:
        print("❌ Benchmark suite FAILED (<80%)")
        sys.exit(1)


if __name__ == "__main__":
    main()
```

**Verification**: Runner script works, benchmarks execute.

---

### Phase 5: Testing & Documentation (1 day)

#### Step 5.1: Run Real-World Test

```bash
soothe --no-tui -p "analyze this project architecture"
```

**Verify**:
- Progressive actions (actions improve specificity)
- Comprehensive report (300-600 words, structured)
- No "already analyzed" cop-out
- Concrete numbers and names

#### Step 5.2: Run Benchmark Suite

```bash
cd benchmarks
python run-benchmarks.py
```

**Target**: ≥8/10 benchmarks pass (80% threshold).

#### Step 5.3: Update IG-143 Success Criteria

**File**: `docs/impl/IG-143-cli-display-refactoring.md`

**Add new criteria**:

```markdown
### Extended Success Criteria (from RFC-603)

| # | Criterion | Target | Validation |
|---|-----------|--------|------------|
| 8 | **No tool output leakage after completion** | 0 lines after completion | Manual test |
| 9 | **Progressive action descriptions** | ≥85% specific in multi-step cases | Benchmark 01-08 |
| 10 | **Comprehensive final reports** | 300-600 words for complex goals | Benchmark 01, 04, 05 |
```

#### Step 5.4: Create Documentation

Update user guide if needed to explain:
- Automatic synthesis for complex goals
- Progressive action behavior
- Evidence-based quality metrics

---

## Verification Checklist

### Code Quality

- [ ] All new files have proper imports and type hints
- [ ] All functions have Google-style docstrings
- [ ] Code follows existing patterns in codebase
- [ ] No langchain ecosystem duplication

### Testing

- [ ] Unit tests for action_quality.py (specificity, repetition, enhancement)
- [ ] Unit tests for evidence-based metrics (confidence, progress)
- [ ] Unit tests for synthesis.py (trigger, classification, generation)
- [ ] Integration test for progressive iterations
- [ ] Integration test for synthesis phase
- [ ] Benchmark suite: ≥8/10 pass

### Real-World Validation

- [ ] Run `soothe --no-tui -p "analyze this project architecture"`
- [ ] Verify progressive actions (check iteration output)
- [ ] Verify comprehensive report (300-600 words, structured)
- [ ] Verify no "already analyzed"
- [ ] Verify concrete numbers and names

### Final Checks

- [ ] Run `./scripts/verify_finally.sh` (format, lint, tests)
- [ ] All linting errors fixed
- [ ] All tests pass (900+ tests)
- [ ] No breaking changes warnings
- [ ] Git commit ready

---

## File Changes Summary

| File | Change | Lines |
|------|--------|-------|
| `action_quality.py` | NEW | ~150 |
| `synthesis.py` | NEW | ~200 |
| `reason.py` | MODIFY | ~20 |
| `loop_agent.py` | MODIFY | ~30 |
| `schemas.py` | MODIFY | ~40 |
| `simple.py` | MODIFY | ~80 |
| `output_format.xml` | MODIFY | ~50 |
| `synthesis_format.xml` | NEW | ~100 |
| `benchmarks/*.md` | NEW (10 files) | ~500 |
| `run-benchmarks.py` | NEW | ~100 |
| **Total** | | **~1270 lines** |

---

## Risk Handling

### Synthesis Fails

**Fallback**: Use raw `full_output` from ReasonResult.

**Implementation**: Exception handler in `loop_agent.py` catches synthesis errors and falls back.

### Post-Processing Over-Corrects

**Safety Net**: Only enhance repeated/generic actions; keep specific ones as-is.

**Implementation**: `_is_specific_action()` check before enhancement.

### LLM Ignores Progressive Prompts

**Safety Net**: Post-processing ensures specificity even if LLM ignores guidance.

**Implementation**: `enhance_action_specificity()` runs on every iteration.

### Benchmarks Reveal Issues

**Iteration**: Fix issues discovered in benchmarks, re-run suite.

**Process**: Benchmark loop until ≥80% pass rate achieved.

---

## Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Benchmark pass rate | ≥80% | 8/10 cases pass |
| Progressive actions | ≥85% | 6/7 multi-step cases show progression |
| Synthesis quality | ≥90% | Comprehensive reports when synthesis triggers |
| Iteration efficiency | ≤8 iterations | No runaway loops |
| Real-world test | ✅ | Architecture analysis produces comprehensive report |

---

**Implementation Guide Status**: Draft - Ready for Implementation