# IG-524: Goal-Synthesis Prompt Improvements

**IG**: 524
**Title**: Goal-Synthesis Prompt Improvements
**Status**: Implemented
**Created**: 2026-06-28
**Completed**: 2026-06-28
**RFCs**: RFC-616 (scenario-driven synthesis)
**Related**: IG-300 (scenario classifier), RFC-214 (loop message ledger)

## Overview

Improve goal-synthesis message construction to eliminate misleading signals, enable prompt caching, and improve LLM comprehension of execution evidence.

## Problem Analysis

Three issues identified from real execution case (loop 5dec):

### Issue 1: Empty EXECUTION SUMMARY Misleads Reasoning

**Evidence**:
```
EXECUTION SUMMARY:
- Total steps: 0          ← MISLEADING
- Successful: 0
- Step types: []
- Tools used: []
- Evidence volume: 0 chars

EVIDENCE:
WORK TRANSCRIPT:          ← ACTUAL CONTENT
  [Task] Execute: Discover and map daemon public API surface
  [Finding] I'll explore...
```

**Root cause**: `_extract_execution_summary()` reads `state.step_results` while evidence comes from `state.loop_messages`. Data sources diverge.

**Solution**: Remove EXECUTION SUMMARY entirely. LLM derives needed summary from EVIDENCE section.

### Issue 2: Static Content Prevents Prompt Caching

**Evidence**: `AVAILABLE BUILT-IN SCENARIOS` list (~300 tokens) identical for every request but placed in user message.

**Root cause**: Static instructions placed in dynamic message component.

**Solution**: Move scenario list to system prompt (`synthesis_report_system.xml`) for caching.

### Issue 3: Non-Standard Transcript Markers

**Evidence**:
```
[Task] Execute: Discover...
[Finding] I'll explore...
```

**Root cause**: `[Task]`/`[Finding]` are ad-hoc prefixes that disguise Human/AI turn structure.

**Solution**: Use standard `USER:`/`AI:` conversation markers that LLMs recognize instantly.

## Implementation Scope

### Files Modified

| File | Change Type | Description |
|------|-------------|-------------|
| `user_message.py` | Modify | Remove EXECUTION SUMMARY + AVAILABLE BUILT-IN SCENARIOS sections from synthesis message |
| `synthesis_report_system.xml` | Modify | Add AVAILABLE BUILT-IN SCENARIOS list to system prompt template |
| `synthesis_projection.py` | Modify | Change `[Task]`→`USER:` and `[Finding]`→`AI:` markers |
| `scenario_classifier.py` | No change | `_SCENARIO_DESCRIPTIONS` constant remains, accessed by system template |

### Files Unchanged

- `synthesis.py` - Generation logic unchanged
- `scenario_classifier.py` - Classification logic unchanged (but `_extract_execution_summary` no longer called from user message builder)

## Implementation Details

### Change 1: Remove EXECUTION SUMMARY (user_message.py)

**Location**: `packages/soothe/src/soothe/foundation/loop/prompts/user_message.py:358-373`

**Before**:
```python
exec_summary = _extract_execution_summary(state)

summary_lines = [
    f"- Total steps: {exec_summary['total_steps']}",
    f"- Successful: {exec_summary['successful_steps']}",
    f"- Step types: {exec_summary['step_types']}",
    f"- Tools used: {exec_summary['tools_used']}",
    f"- Evidence volume: {exec_summary['evidence_volume']} chars",
]
sections.append(("EXECUTION SUMMARY", "\n".join(summary_lines)))
```

**After**: Delete entire block. Import `_extract_execution_summary` can be removed from synthesis message scope.

**Rationale**: EVIDENCE section contains `_step_evidence_lines()` plus `_execute_transcript_lines()`. The LLM can derive any summary needed from that content.

### Change 2: Remove AVAILABLE BUILT-IN SCENARIOS (user_message.py)

**Location**: `packages/soothe/src/soothe/foundation/loop/prompts/user_message.py:375-380`

**Before**:
```python
scenarios_list = "\n".join(
    f"{i + 1}. {name} - {_SCENARIO_DESCRIPTIONS.get(name, 'General synthesis')}"
    for i, name in enumerate(BUILTIN_SCENARIOS.keys())
)
sections.append(("AVAILABLE BUILT-IN SCENARIOS", scenarios_list))
```

**After**: Delete entire block. Remove import of `_SCENARIO_DESCRIPTIONS` and `BUILTIN_SCENARIOS` from `build_synthesis_message()` scope.

**Rationale**: Scenario list moved to system prompt where it's cached once per session.

### Change 3: Add Scenarios to System Prompt (synthesis_report_system.xml)

**Location**: `packages/soothe/src/soothe/foundation/loop/prompts/fragments/instructions/synthesis_report_system.xml`

**Before**:
```xml
<SYNTHESIS_REPORT>
You are writing the final report for the person who submitted the request below.
Write only what they need: findings, outcomes, artifacts, and clear next steps when relevant.

Report style: {{ scenario }}

Required sections (use these headings):
{% for section in sections %}
- {{ section }}
{% endfor %}
...
</SYNTHESIS_REPORT>
```

**After**:
```xml
<SYNTHESIS_REPORT>
You are writing the final report for the person who submitted the request below.
Write only what they need: findings, outcomes, artifacts, and clear next steps when relevant.

Available report formats:
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

Report style: {{ scenario }}

Required sections (use these headings):
{% for section in sections %}
- {{ section }}
{% endfor %}
...
</SYNTHESIS_REPORT>
```

**Rationale**: Static content in system prompt enables caching; LLM sees scenario options as instructions, not request data.

### Change 4: Standardize Transcript Markers (synthesis_projection.py)

**Location**: `packages/soothe/src/soothe/foundation/loop/engine/synthesis_projection.py:87-94`

**Before**:
```python
if isinstance(msg, LoopHumanMessage):
    text = flatten_execute_human_content(...)
    if text:
        lines.append(f"[Task] {text}")
elif isinstance(msg, LoopAIMessage):
    text = extract_text_from_message_content(msg.content).strip()
    if text:
        lines.append(f"[Finding] {text}")
```

**After**:
```python
if isinstance(msg, LoopHumanMessage):
    text = flatten_execute_human_content(...)
    if text:
        lines.append(f"USER: {text}")
elif isinstance(msg, LoopAIMessage):
    text = extract_text_from_message_content(msg.content).strip()
    if text:
        lines.append(f"AI: {text}")
```

**Rationale**: `USER:`/`AI:` are universal conversation markers. LLM recognizes them instantly as turn boundaries, improving comprehension without changing the flattening approach.

## Expected User Message After Changes

```text
GOAL:
Rewrite RFC-450 and remove RFC-460. Then impl the new RFC-450

INTENT:
agentic (complexity: complex)

CONTEXTUAL FOCUS:
- Summarize result for: Rewrite RFC-450 and remove RFC-460. Then impl the new RFC-450

EVIDENCE EMPHASIS:
Present the single step outcome directly

EVIDENCE:
STEP SUMMARIES:
  [Step S1] Comprehensive API map produced

WORK TRANSCRIPT:
  USER: Discover and map daemon public API surface
  AI: I'll explore the daemon's public API comprehensively. Let me start by...
  USER: Analyze and review API design quality
  AI: I'll perform a structured design review...
  USER: Deep-dive WebSocket request-submit API surface
  AI: Let me start by reading the router, client-side encoding...

TASK:
1. Write a final report for the person who submitted the request
2. Use only the execution evidence provided — do not invent results
3. Organize by theme, not chronologically
4. Include the required sections for the matched scenario
```

**Changes visible**:
1. No EXECUTION SUMMARY section
2. No AVAILABLE BUILT-IN SCENARIOS section
3. `USER:`/`AI:` markers instead of `[Task]`/`[Finding]`

## Testing Requirements

### Unit Tests

1. **`test_user_message.py`**:
   - Verify `build_synthesis_message()` no longer includes EXECUTION SUMMARY
   - Verify no AVAILABLE BUILT-IN SCENARIOS in output
   - Verify sections count matches expected (5 sections vs. 7 before)

2. **`test_synthesis_projection.py`**:
   - Verify transcript uses `USER:` for LoopHumanMessage
   - Verify transcript uses `AI:` for LoopAIMessage
   - Verify excluded phases still filtered

3. **`test_synthesis_report_system.py`**:
   - Verify system template includes scenario list
   - Verify template renders correctly with classification

### Integration Tests

1. **Empty `step_results` with populated `loop_messages`**:
   - Execute synthesis on loop with this state
   - Verify no misleading "0 steps" in prompt
   - Verify evidence content correctly projected

2. **Prompt cache efficiency**:
   - Compare synthesis call token usage before/after
   - Verify system prompt cache hit rate improvement

3. **Output quality comparison**:
   - Run synthesis on same goal before/after
   - Compare comprehension markers (USER/AI vs Task/Finding)
   - Evaluate LLM response quality

## Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| LLM loses summary context | Low | EVIDENCE section contains same information in structured form |
| Scenario list too long in system prompt | Low | ~300 tokens; acceptable for system instructions |
| USER/AI markers confuse synthesis format | Low | Standard conversation markers; LLMs recognize universally |
| Regression in synthesis output quality | Low | Evidence unchanged; only presentation format differs |

## Success Criteria

1. **No misleading empty summaries** — Synthesis prompts never show "Total steps: 0" when evidence exists
2. **Prompt cache hits** — System prompt cached once per session, reducing per-synthesis token cost
3. **Standard conversation format** — Transcript uses USER:/AI: markers for Human/AI turns
4. **Output quality maintained** — Synthesis reports maintain same quality or improve

## Implementation Checklist

- [x] Delete EXECUTION SUMMARY block from `user_message.py:build_synthesis_message()`
- [x] Delete AVAILABLE BUILT-IN SCENARIOS block from `user_message.py:build_synthesis_message()`
- [x] Remove unused imports (`_extract_execution_summary`, `BUILTIN_SCENARIOS`, `_SCENARIO_DESCRIPTIONS`)
- [x] Add scenario list to `synthesis_report_system.xml`
- [x] Change `[Task]` → `USER:` in `synthesis_projection.py`
- [x] Change `[Finding]` → `AI:` in `synthesis_projection.py`
- [x] Update unit tests
- [x] Run synthesis-related tests (35 passed)
- [x] Update RFC-616 with amendment documenting changes