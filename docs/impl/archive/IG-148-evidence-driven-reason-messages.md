# IG-148: Enhance Evidence-Driven Reason Phase Messages

**Implementation Guide**: IG-0148
**Title**: Enhance LLM input message composition for Layer 2 Reason phase
**Status**: Completed
**Created**: 2026-04-11
**Completed**: 2026-04-11
**RFC Reference**: RFC-207 (Message Type Separation), RFC-211 (Layer 2 Tool Result Optimization)
**Dependencies**: RFC-207, RFC-211, RFC-203 (Working Memory)

---

## Overview

Enhance LLM input message composition sent to Layer 2 Reason phase by:
1. Including CoreAgent input/output evidence (concrete work performed)
2. Removing redundant content (completed_steps duplicates evidence)
3. Reorganizing sections by reasoning priority (concrete evidence first)
4. Adding output summaries (first 300 + last 200 chars) to respect context window limits

---

## Problem Analysis

### Current State

Evidence in HumanMessage (builder.py:153-213):
- Generic summaries: "Read 150 lines" without showing what was found
- Missing CoreAgent input/output: No concrete content from Layer 1 execution
- Redundancy: completed_steps duplicates evidence; previous_reason duplicates prior conversation
- Poor ordering: Abstract summaries before concrete findings

### Impact

- LLM lacks concrete evidence for reasoning decisions
- Generic summaries don't inform replanning decisions
- Redundant content wastes context window
- Abstract summaries don't help determine next actions

---

## Solution Design

### 1. Capture CoreAgent Input/Output

Modify executor.py to store in outcome metadata:
- `step_input`: HumanMessage content sent to Layer 1 (what was requested)
- `output_summary`: Truncated AIMessage + ToolMessage content (concrete findings)
  - First 300 chars: Initial findings/approach
  - Last 200 chars: Final results/conclusions
- Preserves existing entities, success_indicators, size_bytes

### 2. Add Detailed Evidence String

New method in StepResult:
- `get_detailed_evidence_string()`: Includes input/output summary
- Existing `to_evidence_string()`: Keeps concise summaries (backward compatibility)

### 3. Refactor HumanMessage Construction

Reorganize builder.py `_build_human_message()`:
- Remove completed_steps section (redundant)
- Use detailed evidence strings (input/output)
- Reorder sections: concrete evidence → working memory → prior conversation → previous assessment
- Simplify previous_reason (status + next action only, not full summary)

### 4. Section Priority

Reasoning-focused ordering:
1. **Concrete evidence** (CoreAgent input/output) - actionable findings
2. **Working memory** - authoritative record
3. **Prior conversation** - only if referenced in goal
4. **Previous assessment** - brief status for continuity

---

## Implementation Steps

### Step 1: Enhance executor.py outcome metadata

File: `src/soothe/cognition/agent_loop/executor.py`

**Changes in `_stream_and_collect()` method**:
- Track HumanMessage input in `_execute_step_collecting_events()` and `_execute_sequential_chunk()`
- Add output summary extraction logic (first 300 + last 200 chars)
- Store in outcome metadata under "step_input" and "output_summary" keys

**Implementation locations**:
- `_execute_step_collecting_events()` (lines 511-633): Add step_input to outcome
- `_execute_sequential_chunk()` (lines 333-472): Add combined_description to outcomes
- `_stream_and_collect()` (lines 634-880): Add output_summary extraction logic

### Step 2: Add detailed evidence method to StepResult

File: `src/soothe/cognition/agent_loop/schemas.py`

**Add new method** after `to_evidence_string()` (line 165):
```python
def get_detailed_evidence_string(self) -> str:
    """Generate detailed evidence with CoreAgent input/output summary.
    
    Returns:
        Evidence string with:
        - Step ID and outcome type
        - Input: What was sent to CoreAgent (step description)
        - Output summary: First 300 + last 200 chars of execution output
        - Entities: Key files/functions/URLs discovered
    """
```

### Step 3: Add output summary utility

File: `src/soothe/utils/text_preview.py` (or create new utility)

**Add function**:
```python
def create_output_summary(content: str, first_chars: int = 300, last_chars: int = 200) -> dict[str, str]:
    """Create truncated output summary for evidence.
    
    Args:
        content: Full output content
        first_chars: Number of chars from beginning
        last_chars: Number of chars from end
        
    Returns:
        Dict with "first" and "last" keys
    """
```

### Step 4: Refactor builder.py HumanMessage construction

File: `src/soothe/core/prompts/builder.py`

**Modify `_build_human_message()` method** (lines 153-213):
- Remove completed_steps section (lines 186-193)
- Use `get_detailed_evidence_string()` instead of `to_evidence_string()` (line 184)
- Reorder sections: evidence → working memory → prior conversation → previous_reason
- Simplify previous_reason section (lines 205-211): status + progress + next_action only

### Step 5: Update outcome metadata generation

File: `src/soothe/tools/metadata_generator.py`

**Enhance `generate_outcome_metadata()` function**:
- Add step_input parameter
- Add output_summary parameter
- Store in outcome dict

---

## Testing Strategy

### Unit Tests

**Test enhanced evidence strings**:
- Verify `get_detailed_evidence_string()` includes input/output
- Verify output summary truncation (first 300 + last 200 chars)
- Verify backward compatibility with `to_evidence_string()`

**Test message construction**:
- Verify HumanMessage includes detailed evidence
- Verify completed_steps removed
- Verify section ordering
- Verify previous_reason simplified

### Integration Tests

**Test Reason phase execution**:
- Run agentic loop with enhanced messages
- Verify LLM receives concrete evidence
- Verify reasoning decisions improved
- Verify context window not exceeded

### Verification

Run `./scripts/verify_finally.sh`:
- Format check passes
- Linting passes (zero errors)
- All 900+ unit tests pass

---

## Context Window Analysis

### Token Cost Estimation

**Before enhancement**:
- Generic evidence: ~80 chars per step
- Completed steps: ~80 chars per step (duplicate)
- Previous reason: ~200 chars
- Total per iteration (3 steps): ~500 chars

**After enhancement**:
- Detailed evidence (input + output summary): ~500 chars per step
- Removed completed_steps: -240 chars (3 steps)
- Simplified previous_reason: ~100 chars (reduced from 200)
- Total per iteration (3 steps): ~1600 chars (net +1100 chars)

**Impact**: ~1.1k additional chars per iteration, well within context window budget

---

## Backward Compatibility

### Preserved Interfaces

- `to_evidence_string()`: Existing method unchanged (concise summaries)
- `outcome` metadata: Existing keys preserved (type, tool_name, entities, etc.)
- Message structure: SystemMessage/HumanMessage separation unchanged (RFC-207)

### New Interfaces

- `get_detailed_evidence_string()`: New method for Reason phase only
- `step_input`, `output_summary`: New keys in outcome metadata

---

## Success Criteria

1. ✅ CoreAgent input/output captured in outcome metadata
2. ✅ Detailed evidence strings include concrete findings
3. ✅ Completed_steps section removed from HumanMessage
4. ✅ Section ordering: evidence → working memory → prior conversation → previous assessment
5. ✅ Output summary truncation (first 300 + last 200 chars)
6. ✅ Previous_reason simplified (status + progress + next_action only)
7. ✅ All tests pass (900+)
8. ✅ Linting passes (zero errors)
9. ✅ Format check passes
10. ✅ Context window impact minimal (< 2k chars per iteration)

---

## Future Considerations

### Potential Follow-up Work

1. **Dynamic truncation**: Adjust summary length based on step importance
2. **Evidence ranking**: Rank evidence by relevance to current goal
3. **Cross-iteration synthesis**: Synthesize evidence across iterations
4. **Evidence compression**: More aggressive compression for long-running goals

---

## Implementation Log

**2026-04-11**: Implementation guide created
**2026-04-11**: Implementation completed
  - Added `create_output_summary()` utility in text_preview.py
  - Enhanced executor.py to capture CoreAgent input/output in outcome metadata
  - Added `get_detailed_evidence_string()` method to StepResult
  - Refactored builder.py HumanMessage construction with new ordering and simplified sections
  - All verification checks passed (format, lint, 1589 unit tests)

**Status**: Completed ✅

---

## Related Documents

- RFC-207: Message Type Separation
- RFC-211: Layer 2 Tool Result Optimization
- RFC-203: Working Memory Integration
- IG-135: Prompt Architecture Implementation
- RFC-603: Action Specificity Enhancement