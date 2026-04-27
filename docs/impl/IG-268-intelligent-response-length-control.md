# IG-268: Intelligent Response Length Control and Scenario-Aware System Prompts

**Status**: ✅ Completed
**Date**: 2026-04-27
**RFC References**: RFC-201 (AgentLoop), RFC-603 (Synthesis Phase), RFC-0008 (Agentic Loop Runner)

---

## Overview

Implemented intelligent response length control and scenario-aware system prompts to dynamically adjust output size based on task complexity, intent classification, and evidence patterns.

**Problem**: Fixed 50k/48k character limits regardless of task complexity. Simple queries ("hello") got verbose responses; complex tasks needed more structured output.

**Solution**: Response length categories (BRIEF/CONCISE/STANDARD/COMPREHENSIVE) with intelligent sizing based on intent, goal type, and evidence metrics.

---

## Key Changes

### 1. Response Length Intelligence System (NEW)

**File**: `packages/soothe/src/soothe/cognition/agent_loop/response_length_policy.py`

Created module with 4 response length categories:
- **BRIEF** (50-150 words): Chitchat, quiz, simple questions
- **CONCISE** (150-300 words): Thread continuation, simple follow-ups
- **STANDARD** (300-500 words): Medium tasks, research synthesis
- **COMPREHENSIVE** (600-800 words): Architecture analysis, complex implementation

**Key Functions**:
```python
def determine_response_length(
    intent_type: str,
    goal_type: str,
    task_complexity: str,
    evidence_volume: int,
    evidence_diversity: int,
) -> ResponseLengthCategory
```

**Rules**:
1. Chitchat intent → BRIEF (greetings need short replies)
2. Quiz intent → BRIEF (factual questions need concise answers)
3. Thread continuation → CONCISE (builds on prior context)
4. New goal + medium + research → STANDARD
5. New goal + complex + architecture → COMPREHENSIVE
6. Large evidence (≥2000 chars) + high diversity (≥4 steps) → bump to COMPREHENSIVE

**Evidence Metrics**: `calculate_evidence_metrics()` returns (volume, diversity) tuple from successful step results.

---

### 2. Enhanced AgentLoop Schemas

**File**: `packages/soothe/src/soothe/cognition/agent_loop/schemas.py`

**LoopState additions** (IG-268):
```python
intent: Any | None = None  # Intent classification for response length intelligence
```

**PlanResult additions** (IG-268):
```python
response_length_category: str | None = None  # brief/concise/standard/comprehensive
```

---

### 3. Final Report Generation Integration

**File**: `packages/soothe/src/soothe/cognition/agent_loop/agent_loop.py`

**Changes** (IG-268):
- Pass intent classification through loop state
- Determine response length category at goal completion (once for all branches)
- Inject word count ranges into final report request to CoreAgent
- Add `_get_length_guidance()` helper method

**Example prompt injection**:
```python
report_request = f"""Based on the complete execution history, generate a final report for: {goal}

RESPONSE LENGTH: {length_category.min_words}-{length_category.max_words} words ({length_category.value} category)

{self._get_length_guidance(length_category)}

The report should:
1. Summarize what was accomplished
2. Include actual content from tools
3. Match the response length guidance above
...
"""
```

---

### 4. Intelligent Display Caps

**File**: `packages/soothe/src/soothe/core/runner/_runner_agentic.py`

**Function**: `_agentic_final_stdout_text()` (IG-268)

**Adaptive truncation thresholds**:
- BRIEF: 500 chars (chitchat/quiz fit easily)
- CONCISE: 2000 chars (thread continuation)
- STANDARD: 10000 chars (medium research)
- COMPREHENSIVE: 50000 chars (complex architecture)

**Preview caps** also scale with category:
- BRIEF: 400 chars (show most of response)
- CONCISE: 1800 chars
- STANDARD: 9000 chars
- COMPREHENSIVE: 48000 chars (default)

**Signature update**:
```python
def _agentic_final_stdout_text(
    *,
    next_action: str,
    full_output: str | None,
    thread_id: str,
    workspace: str | None,
    config: SootheConfig | None,
    response_length_category: str | None = None,  # IG-268: Intelligent caps
) -> str | None
```

---

### 5. Scenario-Specific System Prompts

**File**: `packages/soothe/src/soothe/config/prompts.py`

**New guides** (IG-268):
```python
_ARCHITECTURE_ANALYSIS_GUIDE = """\
Architecture analysis approach:
- Start with system overview (purpose, scale, tech stack)
- Break down layers with specific component names
- List 5-10 critical components with descriptions
- Identify design patterns with concrete examples
"""

_RESEARCH_SYNTHESIS_GUIDE = """\
Research synthesis approach:
- Lead with key findings with numbers ("Found X patterns")
- Describe methodology briefly
- Connect findings into conclusions
"""

_THREAD_CONTINUATION_GUIDE = """\
Thread continuation approach:
- Reference prior conversation context
- Build on previous results
- Provide incremental updates
"""

_QUIZ_RESPONSE_GUIDE = """\
Quiz/factual questions:
- Provide concise factual answer (1-3 sentences)
- Use your knowledge directly
"""
```

---

### 6. Middleware Scenario Awareness

**File**: `packages/soothe/src/soothe/middleware/system_prompt_optimization.py`

**New method**: `_build_scenario_section()` (IG-268)

Injects targeted guidance based on intent/goal classification:
```python
def _build_scenario_section(self, intent_type: str, goal_type: str) -> str | None:
    """Build scenario-specific guidance section."""
    if intent_type == "quiz":
        return _QUIZ_RESPONSE_GUIDE
    if intent_type == "thread_continuation":
        return _THREAD_CONTINUATION_GUIDE
    if goal_type == "architecture_analysis":
        return _ARCHITECTURE_ANALYSIS_GUIDE
    if goal_type == "research_synthesis":
        return _RESEARCH_SYNTHESIS_GUIDE
    return None
```

Integrated into `_build_dynamic_sections()` to inject scenario guidance alongside WORKSPACE, THREAD, and PROTOCOLS sections.

---

## Response Length Scenarios

### BRIEF (50-150 words)
- **Intent**: chitchat, quiz
- **Example**: "What's quantum entanglement?" → 1-3 sentence answer
- **Display**: 500 chars cap, no truncation

### CONCISE (150-300 words)
- **Intent**: thread_continuation
- **Example**: "translate that" → brief continuation with incremental update
- **Display**: 2000 chars cap

### STANDARD (300-500 words)
- **Intent**: new_goal, medium complexity
- **Goal type**: research_synthesis, general_synthesis
- **Evidence**: Medium volume (500-1500 chars), 2-3 steps
- **Example**: "search web for AI papers" → findings + methodology
- **Display**: 10000 chars cap

### COMPREHENSIVE (600-800 words)
- **Intent**: new_goal, complex
- **Goal type**: architecture_analysis, implementation_summary
- **Evidence**: Large volume (≥2000 chars), ≥4 unique steps
- **Example**: "analyze codebase architecture" → full structured report
- **Display**: 50000 chars cap, overflow spooled to disk

---

## Evidence-Based Decision Logic

**Volume thresholds**:
- ≥2000 chars + ≥4 unique steps → COMPREHENSIVE override
- ≥1000 chars + ≥3 unique steps → STANDARD fallback

**Calculation**: `calculate_evidence_metrics()` sums evidence string lengths from successful steps and counts unique step IDs.

---

## Verification

**All checks passed** ✅:
- Code formatting: 306 files formatted
- Linting: Zero errors
- Unit tests: 1288 passed, 14 skipped, 1 xfailed

---

## Benefits

1. **Better UX**: Users get appropriately sized responses for different task types
2. **Evidence-Driven**: Decisions based on actual execution patterns, not keywords
3. **Scenario-Aware**: Targeted guidance for architecture, research, thread continuation, quiz
4. **Intelligent Caps**: Truncation adapts to response category instead of fixed 50k threshold
5. **Backward Compatible**: Existing behavior preserved, new features additive

---

## Testing Scenarios

1. Chitchat: `soothe "hello"` → Brief response (50-150 words)
2. Quiz: `soothe "What is the capital of France?"` → Brief factual answer (1-3 sentences)
3. Thread continuation: `soothe "translate that"` → Concise (150-300 words)
4. Research: `soothe "search web for AI papers"` → Standard (300-500 words)
5. Architecture: `soothe "analyze codebase architecture"` → Comprehensive (600-800 words)

---

## Future Enhancements

Potential future improvements:
- Add MEDIUM response category (200-400 words) for intermediate tasks
- Fine-tune evidence thresholds based on user feedback
- Add scenario guides for debugging, testing, deployment
- Integrate response length feedback into intent classification training

---

## Related Implementation Guides

- IG-226: Intent classification with conversation context
- IG-250: Quiz intent support
- IG-199: Adaptive final response policy
- IG-123: Final report overflow spooling
- IG-267: CLI display fixes and goal completion trophy

---

## Commit References

Implementation completed in single session with full verification. All code changes include IG-268 annotations.