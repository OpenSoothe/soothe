# Design: Reasoning Quality & Progressive Actions

**Date**: 2026-04-09
**Status**: Draft
**Scope**: Fix IG-143 Issues #2 and #3 + broader reasoning quality improvements

---

## Overview

Refactor the reasoning layer to ensure:
1. **Progressive actions** - Each iteration's action description becomes more specific, showing measurable progress toward the goal
2. **Comprehensive final reports** - Synthesis phase generates structured, detailed summaries instead of concatenating raw evidence
3. **Improved quality metrics** - Evidence-based confidence estimation and progress tracking

**Approach**: Incremental Enhancement - prompt engineering + post-processing + optional synthesis phase

---

## Problem Statement

### Issue #2: Progress NOT Progressive

Current behavior shows action descriptions regressing from specific back to generic:

```
Iteration 1: "Use file and shell tools..." (generic)
Iteration 2: "Use file and shell tools..." (repeated - NO PROGRESS)
Iteration 3: "List the root directory structure..." (specific - GOOD!)
Iteration 4: "Use file and shell tools..." (REGRESSED - BAD!)
```

**Root cause**: `soothe_next_action` field is LLM-generated with no post-processing or progression tracking.

### Issue #3: Final Report Insufficient

Current final report example:
```
✓ The Soothe project architecture has already been fully analyzed.
It's a Python-based system with ~18K lines across 338 files...
```

**Problems**:
- Says "already analyzed" instead of providing new synthesis
- Minimal detail (just line count and file count)
- No architecture breakdown
- No key components identified
- No design patterns explained

**Root cause**: `full_output` is just concatenated step results, not a synthesized summary.

### Quality Gaps

- Confidence estimation relies solely on LLM self-assessment
- Progress tracking doesn't account for actual step completion
- Decision reasoning often vague without evidence citations

---

## Solution Architecture

### Component Overview

```
Loop → Reason (enhanced) → Execute → Reason (enhanced) → ... → Done
                                                          ↓
                                                    Synthesis (optional)
                                                          ↓
                                                    Final Report
```

**Key Components**:

1. **Progressive Actions**: Enhanced prompts + post-processing for action specificity
2. **Synthesis Phase**: Optional final step for comprehensive summaries
3. **Quality Improvements**: Evidence-based confidence and progress calculations

### File Structure

```
src/soothe/cognition/agent_loop/
├── reason.py                    # Enhanced ReasonPhase
├── synthesis.py                 # NEW: SynthesisPhase
├── action_quality.py            # NEW: Post-processing for actions
└── schemas.py                   # Updated: Add new fields

src/soothe/core/prompts/fragments/
├── instructions/
│   ├── output_format.xml        # Enhanced: Progressive action guidance
│   └── synthesis_format.xml     # NEW: Synthesis output format

src/soothe/cognition/planning/
└── simple.py                    # Enhanced: Better confidence/progress

benchmarks/reasoning-quality/
├── README.md                    # Benchmark documentation
├── run-benchmarks.py            # Benchmark runner
├── 01-architecture-analysis.md
├── 02-code-investigation.md
├── 03-simple-lookup.md
├── ... (10 total benchmark files)
└── results.json                 # Generated benchmark results
```

---

## Component 1: Progressive Actions

### Goal
Ensure each iteration's `soothe_next_action` is more specific than the previous, showing measurable progress toward the goal.

### Implementation

#### 1.1 Prompt Enhancements

**File**: `src/soothe/core/prompts/fragments/instructions/output_format.xml`

Add new section:

```xml
<PROGRESSIVE_ACTIONS>
CRITICAL: Each iteration must show MORE SPECIFIC actions than before.

Rules:
- Reference what you learned in previous iterations (e.g., "Based on the file structure I found...")
- NEVER repeat identical action text from prior iterations
- Move from exploration → specific findings → synthesis stages
- If stuck or repeating, explicitly pivot strategy

Action Evolution Pattern:
- Iteration 1: Broad exploration ("List root directory to understand structure")
- Iteration 2: Targeted investigation ("Examine src/soothe/core/ to understand agent factory")
- Iteration 3: Deep analysis ("Analyze protocol implementations in backends/")
- Iteration 4+: Synthesis and validation

BAD: Repeating "Use file and shell tools..." across iterations
GOOD: "Examine the 3 key protocols I identified to understand their interfaces"
</PROGRESSIVE_ACTIONS>
```

#### 1.2 Action Post-Processing

**File**: `src/soothe/cognition/agent_loop/action_quality.py` (NEW)

```python
"""Post-processing to enhance action quality and prevent regression."""

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from soothe.cognition.agent_loop.schemas import StepResult


def enhance_action_specificity(
    action: str,
    goal: str,
    iteration: int,
    previous_actions: list[str],
    step_results: list[StepResult],
) -> str:
    """Score and enhance action specificity.
    
    Args:
        action: Original action text from LLM
        goal: User's goal
        iteration: Current iteration number
        previous_actions: List of actions from prior iterations
        step_results: Evidence from completed steps
    
    Returns:
        Original action if already specific, or enhanced version if generic.
    """
    # Skip if action is already specific
    if _is_specific_action(action, goal):
        return action
    
    # Check for repetition
    if _is_repeated_action(action, previous_actions):
        # Derive from recent evidence
        return _derive_action_from_evidence(step_results, goal, iteration)
    
    # Enhance with context if generic
    return _add_context_to_generic_action(action, step_results, iteration)


def _is_specific_action(action: str, goal: str) -> bool:
    """Check if action references specific artifacts, files, or findings."""
    # Specific patterns: mentions paths, findings, counts, concrete next steps
    specific_patterns = [
        r'\d+\s+(files?|components?|modules?|layers?)',  # "3 files"
        r'(examine|analyze|inspect|investigate)\s+\S+/',  # "examine src/"
        r'based on (the|my)\s+(findings|results|analysis)',  # reference prior work
        r'(identified|found|discovered)\s+\d+',  # "identified 5 protocols"
    ]
    return any(re.search(p, action, re.I) for p in specific_patterns)


def _is_repeated_action(action: str, previous_actions: list[str]) -> bool:
    """Check if action text duplicates a recent iteration (within 3 iterations)."""
    if not previous_actions:
        return False
    
    # Normalize for comparison
    normalized = _normalize_action_text(action)
    recent = [_normalize_action_text(a) for a in previous_actions[-3:]]
    
    return normalized in recent


def _normalize_action_text(action: str) -> str:
    """Normalize action for comparison (lowercase, remove extra spaces)."""
    return ' '.join(action.lower().split())


def _derive_action_from_evidence(
    step_results: list[StepResult],
    goal: str,
    iteration: int
) -> str:
    """Create specific action from recent step outputs."""
    if not step_results:
        return "Investigate the project structure systematically."
    
    # Extract key findings from recent steps
    recent_outputs = [r.output for r in step_results[-3:] if r.output]
    if not recent_outputs:
        return "Continue investigation based on available context."
    
    # Heuristic: find mentioned files/paths in evidence
    paths = _extract_paths_from_evidence("\n".join(recent_outputs))
    if paths:
        return f"Examine {paths[0]} and related files to deepen understanding."
    
    # Fallback: reference iteration count
    return f"Based on findings so far, explore the next logical component (iteration {iteration})."


def _extract_paths_from_evidence(evidence: str) -> list[str]:
    """Extract file paths mentioned in evidence."""
    # Find patterns like "src/soothe/core/agent.py" or "/path/to/file"
    path_pattern = r'(?:src/|/)[\w/.-]+\.(?:py|md|yml|json|toml)'
    paths = re.findall(path_pattern, evidence)
    return list(set(paths))[:3]  # Return top 3 unique paths


def _add_context_to_generic_action(
    action: str,
    step_results: list[StepResult],
    iteration: int
) -> str:
    """Add specificity to generic actions like 'Use file tools...'"""
    # Extract what was found
    findings = _summarize_recent_findings(step_results)
    if findings:
        return f"{action}, focusing on {findings}"
    return f"{action} (iteration {iteration})"


def _summarize_recent_findings(step_results: list[StepResult]) -> str | None:
    """Brief summary of recent discoveries."""
    if not step_results:
        return None
    
    # Simple heuristic: count files/components mentioned
    recent_text = ' '.join(r.output or '' for r in step_results[-2:])
    
    # Count specific indicators
    file_count = len(re.findall(r'\.py', recent_text))
    dir_count = len(re.findall(r'src/\w+', recent_text))
    
    if file_count > 5:
        return f"the {file_count}+ files discovered"
    elif dir_count > 2:
        return f"the {dir_count} key directories identified"
    
    return None
```

#### 1.3 Integration

**File**: `src/soothe/cognition/agent_loop/reason.py`

```python
# In ReasonPhase.reason(), after getting result from loop_reasoner:

# Record action in history
state.add_action_to_history(result.soothe_next_action)

# Enhance action if needed
if result.soothe_next_action:
    result.soothe_next_action = enhance_action_specificity(
        action=result.soothe_next_action,
        goal=goal,
        iteration=state.iteration,
        previous_actions=state.get_recent_actions(n=3),
        step_results=state.step_results,
    )
```

---

## Component 2: Comprehensive Final Reports

### Goal
Generate structured, comprehensive summaries when `status="done"` instead of just concatenating step results.

### Implementation

#### 2.1 Synthesis Trigger Logic

**File**: `src/soothe/cognition/agent_loop/synthesis.py` (NEW)

```python
"""Synthesis phase for comprehensive final reports."""

import logging
from typing import TYPE_CHECKING

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel
    from soothe.cognition.agent_loop.schemas import LoopState, ReasonResult
    from soothe.protocols.planner import PlanContext

logger = logging.getLogger(__name__)

# Internal thresholds (not user-configurable)
_SYNTHESIS_MIN_EVIDENCE_LENGTH = 500  # chars
_SYNTHESIS_MIN_STEPS = 2
_SYNTHESIS_MIN_SUCCESS_RATE = 0.6
_SYNTHESIS_MAX_TOKENS = 1000


class SynthesisPhase:
    """Generate comprehensive final report from accumulated evidence."""
    
    def __init__(self, llm_client: BaseChatModel) -> None:
        """Initialize with LLM client for synthesis.
        
        Args:
            llm_client: Chat model for synthesis generation
        """
        self._llm = llm_client
    
    def should_synthesize(
        self,
        goal: str,
        state: LoopState,
        reason_result: ReasonResult,
    ) -> bool:
        """Determine if synthesis is beneficial based on evidence quality.
        
        Args:
            goal: User's goal
            state: Current loop state with evidence
            reason_result: Final reason result
        
        Returns:
            True if synthesis should run, False to use raw full_output.
        """
        # Criterion 1: Enough evidence to synthesize
        if len(state.step_results) < _SYNTHESIS_MIN_STEPS:
            logger.debug(
                "[Synthesis] Skipped: only %d steps (need %d)",
                len(state.step_results),
                _SYNTHESIS_MIN_STEPS,
            )
            return False
        
        # Criterion 2: High success rate (quality evidence)
        success_count = sum(1 for r in state.step_results if r.success)
        success_rate = success_count / len(state.step_results)
        
        if success_rate < _SYNTHESIS_MIN_SUCCESS_RATE:
            logger.debug(
                "[Synthesis] Skipped: low success rate %.0f%% (need %.0f%%)",
                success_rate * 100,
                _SYNTHESIS_MIN_SUCCESS_RATE * 100,
            )
            return False
        
        # Criterion 3: Sufficient evidence volume
        total_evidence_length = sum(len(r.output or "") for r in state.step_results)
        
        if total_evidence_length < _SYNTHESIS_MIN_EVIDENCE_LENGTH:
            logger.debug(
                "[Synthesis] Skipped: only %d chars evidence (need %d)",
                total_evidence_length,
                _SYNTHESIS_MIN_EVIDENCE_LENGTH,
            )
            return False
        
        # Criterion 4: Evidence complexity (multiple distinct findings)
        unique_step_ids = set(r.step_id for r in state.step_results if r.success)
        
        if len(unique_step_ids) < 2:
            logger.debug(
                "[Synthesis] Skipped: only %d unique steps (need 2+)",
                len(unique_step_ids),
            )
            return False
        
        # All criteria met - synthesis beneficial
        logger.info(
            "[Synthesis] Triggered: %d steps, %.0f%% success, %d chars evidence",
            len(state.step_results),
            success_rate * 100,
            total_evidence_length,
        )
        return True
    
    async def synthesize(
        self,
        goal: str,
        state: LoopState,
        context: PlanContext,
        reason_result: ReasonResult,
    ) -> str:
        """Generate comprehensive summary from all evidence.
        
        Args:
            goal: User's goal
            state: Loop state with all evidence
            context: Planning context
            reason_result: Final reason result
        
        Returns:
            Structured summary text suitable for final output.
        """
        # Determine synthesis type from goal characteristics
        synthesis_type = self._classify_goal(goal, state)
        
        # Build synthesis prompt
        messages = self._build_synthesis_messages(
            goal=goal,
            state=state,
            context=context,
            synthesis_type=synthesis_type,
        )
        
        # Call LLM for synthesis
        response = await self._llm.ainvoke(messages)
        synthesis_text = self._extract_synthesis(response.content)
        
        logger.info(
            "[Synthesis] Generated %d char report (type=%s)",
            len(synthesis_text),
            synthesis_type,
        )
        
        return synthesis_text
    
    def _classify_goal(self, goal: str, state: LoopState) -> str:
        """Classify goal type for template selection.
        
        Uses evidence characteristics, not keyword matching.
        
        Returns:
            One of: "architecture_analysis", "research_synthesis", 
                   "implementation_summary", "general_synthesis"
        """
        # Check evidence patterns
        evidence_text = ' '.join(r.output or '' for r in state.step_results)
        
        # Architecture indicators: multiple directories, layer mentions
        has_dirs = len(set(re.findall(r'src/\w+', evidence_text))) > 3
        has_architecture = any(
            term in evidence_text.lower()
            for term in ['layer', 'protocol', 'backend', 'module']
        )
        
        if has_dirs and has_architecture:
            return "architecture_analysis"
        
        # Research indicators: multiple sources, findings
        has_findings = len(re.findall(r'\d+\s+(files?|components?|modules?)', evidence_text)) > 2
        
        if has_findings:
            return "research_synthesis"
        
        # Implementation indicators: code patterns
        has_code = len(re.findall(r'def |class |import ', evidence_text)) > 5
        
        if has_code:
            return "implementation_summary"
        
        return "general_synthesis"
    
    def _build_synthesis_messages(
        self,
        goal: str,
        state: LoopState,
        context: PlanContext,
        synthesis_type: str,
    ) -> list[BaseMessage]:
        """Build synthesis-specific prompt messages."""
        from soothe.core.prompts.builder import PromptBuilder
        
        # Load synthesis format template
        prompt_builder = PromptBuilder()
        synthesis_format = prompt_builder._load_fragment(
            "instructions/synthesis_format.xml"
        )
        
        # Build system message
        system_content = synthesis_format.format(
            goal=goal,
            iteration_count=state.iteration,
            evidence_summary=state.evidence_summary[:2000],  # Truncate
            synthesis_type=synthesis_type,
        )
        
        # Build human message with evidence
        evidence_text = "\n\n".join(
            f"**Step {i+1}** ({r.step_id}):\n{r.output[:500]}"
            for i, r in enumerate(state.step_results[-10:])  # Last 10 steps
            if r.output
        )
        
        human_content = f"Goal: {goal}\n\nEvidence Collected:\n{evidence_text}"
        
        return [
            SystemMessage(content=system_content),
            HumanMessage(content=human_content),
        ]
    
    def _extract_synthesis(self, content: str) -> str:
        """Extract synthesis text from LLM response."""
        # Handle both string and list content
        if isinstance(content, str):
            return content.strip()
        elif isinstance(content, list):
            # Anthropic-style blocks
            text_parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
            return "\n".join(text_parts).strip()
        else:
            return str(content).strip()
```

#### 2.2 Synthesis Prompt Template

**File**: `src/soothe/core/prompts/fragments/instructions/synthesis_format.xml` (NEW)

```xml
<SYNTHESIS_FORMAT>
You are generating the FINAL comprehensive report for a completed goal.

Context:
- Goal: {goal}
- Completed iterations: {iteration_count}
- Evidence collected: {evidence_summary}
- Report type: {synthesis_type}

Your task: Synthesize ALL evidence into a structured, comprehensive report.

CRITICAL REQUIREMENTS:
1. Do NOT say "already analyzed" or "I've already..." - provide NEW synthesis
2. Be specific with numbers, names, and concrete findings from the evidence
3. Structure the report appropriately for the goal type
4. Use markdown headers (##), bullet points, and concise paragraphs
5. Length: 300-600 words for architecture/research, shorter for simpler goals

For Architecture Analysis goals, include:

## System Overview
- What is this system? (purpose, scale, tech stack)
- Key statistics (lines of code, files, modules)

## Architecture Layers
- For EACH major layer: purpose, key components, responsibilities
- How layers interact

## Key Components
- List 5-10 most important files/modules with descriptions
- What each component does

## Design Patterns
- What architectural patterns are used?
- How do they benefit the system?

## Dependencies
- External dependencies and why they're used

## Notable Features
- What makes this system unique or interesting?

---

For Research Synthesis goals, include:

## Key Findings
- Main discoveries from research
- Supporting evidence

## Methodology
- How the investigation was conducted

## Conclusions
- Synthesis of findings
- Implications

---

For Implementation Summary goals, include:

## What Was Built
- Components created/modified

## Implementation Details
- Key technical decisions
- How it works

## Usage
- How to use the implementation

---

For General Synthesis:
- Structure appropriately based on goal type
- Include overview, key points, and conclusions

---

Return ONLY the synthesis report, no JSON or other formatting.
Make it comprehensive, specific, and valuable to the user.
</SYNTHESIS_FORMAT>
```

#### 2.3 Integration into Loop Agent

**File**: `src/soothe/cognition/agent_loop/loop_agent.py`

```python
# In agentic_loop() generator, after reason returns status="done":

if reason_result.is_done():
    # Initialize synthesis phase (lazy, only when needed)
    from soothe.cognition.agent_loop.synthesis import SynthesisPhase
    
    # Create synthesis client
    synthesis_llm = config.create_chat_model("synthesis")
    synthesis = SynthesisPhase(llm_client=synthesis_llm)
    
    # Check if synthesis is beneficial
    if synthesis.should_synthesize(goal=state.goal, state=state, reason_result=reason_result):
        logger.info("[Synthesis] Generating comprehensive final report")
        
        try:
            synthesis_output = await synthesis.synthesize(
                goal=state.goal,
                state=state,
                context=context,
                reason_result=reason_result,
            )
            # Replace full_output with synthesis
            reason_result = reason_result.model_copy(
                update={
                    "full_output": synthesis_output,
                    "synthesis_performed": True,
                }
            )
        except Exception as e:
            logger.warning("[Synthesis] Failed, using raw evidence: %s", e)
            # Fall back to original full_output (evidence concatenation)
            reason_result = reason_result.model_copy(
                update={"synthesis_performed": False}
            )
    else:
        # Mark synthesis as skipped
        reason_result = reason_result.model_copy(
            update={"synthesis_performed": False}
        )
    
    # Emit completed event
    yield (
        "completed",
        {
            "result": reason_result,
            "step_results_count": len(state.step_results),
        },
    )
    return
```

---

## Component 3: Quality Improvements

### Goal
Improve confidence estimation and progress tracking to be more accurate and evidence-based.

### Implementation

#### 3.1 Enhanced Confidence Estimation

**File**: `src/soothe/cognition/planning/simple.py`

Add new function:

```python
def _calculate_evidence_based_confidence(
    state: LoopState,
    reason_result: ReasonResult,
) -> float:
    """Calculate confidence from evidence quality, not just LLM estimate.
    
    Args:
        state: Current loop state
        reason_result: Reason result from LLM
    
    Returns:
        Confidence score 0.0-1.0 based on evidence strength.
    """
    base_confidence = reason_result.confidence
    
    # Factor 1: Success rate of steps (weight: 30%)
    if state.step_results:
        success_rate = sum(1 for r in state.step_results if r.success) / len(state.step_results)
        evidence_confidence = success_rate * 0.3
    else:
        evidence_confidence = 0.0
    
    # Factor 2: Evidence volume (weight: 30%)
    # More evidence = higher confidence
    total_evidence = sum(len(r.output or "") for r in state.step_results)
    # Scale: 0 chars = 0.0, 2000+ chars = 0.3
    volume_score = min(total_evidence / 2000.0, 1.0) * 0.3
    
    # Factor 3: Iteration efficiency (weight: 40%)
    # Fewer iterations for same progress = higher confidence
    if state.iteration > 0:
        progress_per_iteration = reason_result.goal_progress / state.iteration
        # Scale: 0.0 progress/iter = 0.0, 0.5+ progress/iter = 0.4
        efficiency_score = min(progress_per_iteration / 0.5, 1.0) * 0.4
    else:
        efficiency_score = 0.2  # Default for first iteration
    
    # Combine: LLM estimate (50%) + evidence factors (50%)
    final_confidence = (
        base_confidence * 0.5 +  # LLM's estimate
        evidence_confidence +     # Success rate (already weighted 0.3)
        volume_score +            # Evidence volume (already weighted 0.3)
        efficiency_score          # Iteration efficiency (already weighted 0.4)
    ) / 1.5  # Normalize to 0.0-1.0 range
    
    return min(max(final_confidence, 0.0), 1.0)
```

**Integration** (in `simple.py`):

In `parse_reason_response_text()` function, after line ~380 where `ReasonResult` is constructed:

```python
# After constructing ReasonResult from parsed JSON:
result = ReasonResult(
    status=status,
    plan_action=plan_action,
    decision=decision,
    reasoning=decision.reasoning if decision else "",
    user_summary=user_summary,
    soothe_next_action=soothe_next_action,
    progress_detail=progress_detail,
    confidence=confidence,
    goal_progress=goal_progress,
    evidence_summary=evidence_summary,
)

# Apply evidence-based quality improvements
result.confidence = _calculate_evidence_based_confidence(state, result)
result.goal_progress = _calculate_evidence_based_progress(state, result)
```

#### 3.2 Improved Progress Tracking

**File**: `src/soothe/cognition/planning/simple.py`

Add new function:

```python
def _calculate_evidence_based_progress(
    state: LoopState,
    reason_result: ReasonResult,
) -> float:
    """Calculate progress from step completion, not just LLM estimate.
    
    Args:
        state: Current loop state
        reason_result: Reason result from LLM
    
    Returns:
        Progress score 0.0-1.0 based on tangible completion signals.
    """
    base_progress = reason_result.goal_progress
    
    # If LLM says done, trust it
    if reason_result.status == "done":
        return 1.0
    
    # Factor 1: Step completion ratio (weight: 20%)
    if state.current_decision:
        total_steps = len(state.current_decision.steps)
        completed_steps = len(state.completed_step_ids)
        completion_ratio = completed_steps / total_steps if total_steps > 0 else 0.0
    else:
        completion_ratio = 0.0
    
    # Factor 2: Evidence accumulation rate (weight: 20%)
    if len(state.step_results) >= 2:
        recent_evidence_len = sum(len(r.output or "") for r in state.step_results[-2:])
        earlier_evidence_len = sum(len(r.output or "") for r in state.step_results[:-2])
        
        # If evidence is still growing rapidly, we're not done
        if earlier_evidence_len > 0:
            growth_rate = recent_evidence_len / earlier_evidence_len
            if growth_rate > 1.5:
                evidence_progress = 0.3  # Still gathering
            elif growth_rate < 0.5:
                evidence_progress = 0.7  # Evidence stabilizing
            else:
                evidence_progress = 0.5  # Steady state
        else:
            evidence_progress = 0.3  # Early stage
    else:
        evidence_progress = 0.2
    
    # Combine: LLM estimate (60%) + objective factors (40%)
    final_progress = (
        base_progress * 0.6 +
        completion_ratio * 0.2 +
        evidence_progress * 0.2
    )
    
    return min(max(final_progress, 0.0), 1.0)
```

**Integration** (in `simple.py`):

Same location as confidence - in `parse_reason_response_text()`, after constructing ReasonResult:

```python
# Apply evidence-based quality improvements (after ReasonResult construction)
result.confidence = _calculate_evidence_based_confidence(state, result)
result.goal_progress = _calculate_evidence_based_progress(state, result)
```

#### 3.3 Better Decision Reasoning

**File**: `src/soothe/core/prompts/fragments/instructions/output_format.xml`

Add to existing prompt:

```xml
<REASONING_QUALITY>
The "reasoning" field is INTERNAL ONLY (not shown to user) but must be HIGH QUALITY.

Requirements:
1. Cite specific evidence: "Step 2 found 5 key files in src/core/"
2. Quantify findings: "Identified 3 protocols, 2 backends, 8 tools"
3. Justify status choice with evidence
4. Be concise but specific (2-4 sentences)

GOOD reasoning:
"Analysis of src/ revealed 8 protocol files and 12 backend implementations. 
Evidence shows a layered architecture with clear separation. 
Progress: examined 60% of key directories. 
Status=continue to examine remaining backends."

BAD reasoning:
"Making good progress. Will continue working on the goal."
</REASONING_QUALITY>
```

---

## Schema Updates

### ReasonResult Updates

**File**: `src/soothe/cognition/agent_loop/schemas.py`

```python
class ReasonResult(BaseModel):
    """Single Reason-phase output: assessment plus optional new plan (ReAct Layer 2)."""
    
    status: Literal["continue", "replan", "done"]
    evidence_summary: str = ""
    goal_progress: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)
    reasoning: str = ""
    user_summary: str = ""
    soothe_next_action: str = ""
    progress_detail: str | None = None
    plan_action: Literal["keep", "new"] = "new"
    decision: AgentDecision | None = None
    next_steps_hint: str | None = None
    full_output: str | None = None
    
    # NEW FIELDS:
    synthesis_performed: bool = Field(
        default=False,
        description="Whether synthesis phase was run to generate full_output"
    )
    action_specificity_score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Post-processed specificity score for soothe_next_action"
    )
    evidence_quality_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Calculated quality of accumulated evidence"
    )
```

### LoopState Updates

**File**: `src/soothe/cognition/agent_loop/schemas.py`

```python
class LoopState(BaseModel):
    """Runtime state for a single Layer 2 ReAct loop."""
    
    iteration: int = 0
    max_iterations: int
    goal: str
    step_results: list[StepResult] = Field(default_factory=list)
    evidence_summary: str = ""
    current_decision: AgentDecision | None = None
    completed_step_ids: set[str] = Field(default_factory=set)
    previous_reason: ReasonResult | None = None
    working_memory: Any = None
    workspace: Path | None = None
    thread_id: str = ""
    
    # Tracking for execution metrics
    total_duration_ms: int = 0
    last_wave_tool_call_count: int = 0
    last_wave_subagent_task_count: int = 0
    last_wave_hit_subagent_cap: bool = False
    
    # NEW: Action history for progressive improvement
    action_history: list[str] = Field(
        default_factory=list,
        description="Chronological list of soothe_next_action values across iterations"
    )
    
    def add_action_to_history(self, action: str) -> None:
        """Record action for progression tracking."""
        if action and action.strip():
            self.action_history.append(action.strip())
    
    def get_recent_actions(self, n: int = 3) -> list[str]:
        """Get last N actions for deduplication/enhancement."""
        return self.action_history[-n:] if self.action_history else []
```

---

## Implementation Plan

### Phase 1: Progressive Actions (1 day)
1. Update `schemas.py`: Add `action_history` to `LoopState`
2. Update `output_format.xml`: Add progressive action guidance
3. Create `action_quality.py`: Implement post-processing functions
4. Modify `reason.py`: Integrate action enhancement
5. Add unit tests for action post-processing

### Phase 2: Quality Improvements (0.5 days)
1. Modify `simple.py`: Add `_calculate_evidence_based_confidence()`
2. Modify `simple.py`: Add `_calculate_evidence_based_progress()`
3. Update `output_format.xml`: Add reasoning quality guidance
4. Add unit tests for quality calculations

### Phase 3: Synthesis Phase (1.5 days)
1. Update `schemas.py`: Add synthesis fields to `ReasonResult`
2. Create `synthesis_format.xml`: Synthesis prompt template
3. Create `synthesis.py`: Implement SynthesisPhase class
4. Modify `loop_agent.py`: Integrate synthesis trigger
5. Add unit tests for synthesis logic

### Phase 4: Benchmark Suite (1 day)
1. Create `benchmarks/reasoning-quality/` directory
2. Write 10 benchmark markdown files
3. Implement `run-benchmarks.py` runner
4. Run all benchmarks and validate
5. Document results

### Phase 5: Testing & Documentation (1 day)
1. Run real-world test: `soothe --no-tui -p "analyze this project arch"`
2. Verify progressive actions improve across iterations
3. Verify comprehensive final reports for synthesis-triggered goals
4. Update RFC documentation if needed
5. Update IG-143 with new success criteria

**Total Estimated Time**: 5 days

---

## Breaking Changes

**No backward compatibility** - clean improvements:

- **Remove `full_output` fallback**: Always use synthesis or fail clearly
- **Remove old confidence/progress**: Replace entirely with evidence-based calculations
- **Remove generic action tolerance**: Require specific actions (enhance if needed)

**Benefits**:
- Simpler code (no fallback logic)
- Consistent quality (all paths use new system)
- Easier testing (fewer code paths)

---

## Benchmark Suite

### Structure
```
benchmarks/reasoning-quality/
├── README.md
├── run-benchmarks.py
├── 01-architecture-analysis.md
├── 02-code-investigation.md
├── 03-simple-lookup.md
├── 04-research-task.md
├── 05-structure-analysis.md
├── 06-error-investigation.md
├── 07-comparison-task.md
├── 08-documentation-generation.md
├── 09-performance-analysis.md
└── 10-quick-summary.md
```

### Benchmark Format
Each benchmark includes:
- Metadata (ID, type, expected iterations, synthesis expected)
- Task (user query to execute)
- Success criteria (checkboxes for validation)
- Execution instructions
- Expected output description

### Success Criteria

| Metric | Target | Rationale |
|--------|--------|-----------|
| Overall Pass Rate | ≥ 80% | 8/10 cases pass |
| Progressive Actions | ≥ 85% of relevant cases | Actions improve in 6/7 multi-step cases |
| Synthesis Quality | ≥ 90% of triggered cases | Comprehensive reports in synthesis cases |
| Iteration Efficiency | Within expected ranges | No runaway loops or premature termination |

---

## Testing Strategy

### Unit Tests
- `test_action_quality.py`: Specificity detection, repetition checking, enhancement logic
- `test_synthesis.py`: Trigger logic, output structure
- `test_quality_improvements.py`: Confidence and progress calculations

### Integration Tests
- `test_progressive_actions.py`: Multi-step actions become progressive
- `test_synthesis.py`: Architecture analysis produces comprehensive report

### Manual Verification
```bash
soothe --no-tui -p "analyze this project arch"
```

Expected:
- Actions: Iteration 1 → 2 → 3 show increasing specificity
- Final report: Structured with Overview, Layers, Components, etc.
- Line count: Still ~20-30 (suppression maintained)

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Synthesis adds latency | Skip synthesis for simple goals (evidence heuristics) |
| Post-processing over-corrects | Only enhance when `_is_repeated_action()` or generic |
| LLM ignores progressive action prompts | Post-processing is safety net |
| Quality heuristics inaccurate | Conservative thresholds, log for tuning |
| Synthesis quality poor | Strong prompt template + fallback to raw evidence |

---

## Success Metrics

**Before**:
- Actions: Generic and repeated across iterations
- Final report: "already analyzed" with minimal details (100 words)
- Confidence: LLM self-assessment only
- Progress: LLM estimate only

**After**:
- Actions: Progressive specificity increase (0% → 80%+ specific)
- Final report: Structured, comprehensive (300-600 words)
- Confidence: Evidence-based (success rate + volume + efficiency)
- Progress: Step completion + evidence growth

**Measured via**: Benchmark suite (≥80% pass rate)

---

## Future Enhancements

Potential follow-ups after this implementation:

1. **Template Library**: Goal-type-specific synthesis templates
2. **Action Memory**: Track actions across sessions to prevent repetition
3. **Quality ML**: Train models to predict synthesis benefit
4. **Streaming Synthesis**: Show synthesis progress in real-time
5. **Multi-Model Synthesis**: Use specialized models for different synthesis types

---

**Design Complete - Ready for Implementation**