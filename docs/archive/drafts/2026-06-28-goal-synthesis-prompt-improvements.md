# Goal-Synthesis Prompt Design Improvements

**Status**: Draft
**Date**: 2026-06-28
**Author**: Analysis from real execution case (loop 5dec)

## Problem Statement

The goal-synthesis user message construction has three design issues that degrade LLM reasoning quality and token efficiency:

1. **Empty EXECUTION SUMMARY misleads reasoning** — Summary reads from `step_results` but synthesis evidence comes from `loop_messages`, creating contradictory signals (zero steps vs. rich transcript)
2. **Static content in dynamic user message** — AVAILABLE BUILT-IN SCENARIOS is identical for every request but appears in user message, preventing prompt cache reuse
3. **Non-standard transcript markers** — `[Task]`/`[Finding]` prefixes disguise Human/AI turn structure, forcing LLM to parse log format instead of recognizing conversation patterns

## Evidence from Real Case (Loop 5dec)

```
GOAL:
Rewrite RFC-450 and remove RFC-460. Then impl the new RFC-450

EXECUTION SUMMARY:
- Total steps: 0
- Successful: 0
- Step types: []
- Tools used: []
- Evidence volume: 0 chars      ← MISLEADING: suggests nothing happened

EVIDENCE:
WORK TRANSCRIPT:
  [Task] Execute: Discover and map daemon public API surface
  [Finding] I'll explore the daemon's public API comprehensively...
  [Task] Execute: Analyze and review API design quality
  [Finding] I'll perform a structured design review...
  ...                          ← ACTUAL EVIDENCE: substantial work done
```

The LLM receives contradictory signals: "0 steps" vs. "[Task] ... [Finding] ..." content.

## Analysis

### Issue 1: EXECUTION SUMMARY Data Source Mismatch

**Current implementation** (`user_message.py:358-373`):

```python
exec_summary = _extract_execution_summary(state)  # reads from state.step_results
summary_lines = [
    f"- Total steps: {exec_summary['total_steps']}",
    f"- Successful: {exec_summary['successful_steps']}",
    ...
]
sections.append(("EXECUTION SUMMARY", "\n".join(summary_lines)))
```

**Root cause**: `_extract_execution_summary()` reads from `state.step_results`, but synthesis evidence is projected from `state.loop_messages` (`synthesis_projection.py:64-96`). These are different data sources that may diverge.

**Impact**: LLM must choose between trusting summary (wrong) or evidence (correct), causing confused reasoning.

### Issue 2: Static Content Placement

**Current implementation** (`user_message.py:375-380`):

```python
scenarios_list = "\n".join(
    f"{i + 1}. {name} - {_SCENARIO_DESCRIPTIONS.get(name, '...')}"
    for i, name in enumerate(BUILTIN_SCENARIOS.keys())
)
sections.append(("AVAILABLE BUILT-IN SCENARIOS", scenarios_list))
```

**Analysis**:
- `BUILTIN_SCENARIOS` is a constant dict (`scenario_classifier.py:28-86`)
- Identical for every synthesis request
- Placed in user message → not cached, ~300 tokens paid per synthesis call

**Best practice**: Static instructions belong in system prompt (cached once per session).

### Issue 3: Transcript Marker Design

**Current implementation** (`synthesis_projection.py:87-94`):

```python
if isinstance(msg, LoopHumanMessage):
    lines.append(f"[Task] {text}")
elif isinstance(msg, LoopAIMessage):
    lines.append(f"[Finding] {text}")
```

**Analysis**:
- `[Task]`/`[Finding]` are ad-hoc log-style prefixes
- Disguise the underlying Human/AI conversation structure
- LLM must parse log format instead of recognizing conversation turns
- Standard conversation markers (`USER:`/`AI:`) are universally recognized

## Proposed Solution

### Change 1: Remove EXECUTION SUMMARY

**Rationale**: The EVIDENCE section already contains step summaries (`_step_evidence_lines`) plus work transcript. The LLM can derive any summary it needs from evidence. Removing eliminates data source mismatch and contradictory signals.

**Implementation**: Delete lines 358-373 from `user_message.py:build_synthesis_message()`.

### Change 2: Move Scenarios to System Prompt

**Rationale**: Scenario list is static instruction content. Placing in system prompt enables caching and reduces per-request token cost by ~300 tokens.

**Implementation**:
1. Add scenario list to `synthesis_report_system.xml`
2. Remove lines 375-380 from `user_message.py:build_synthesis_message()`

### Change 3: Standardize Transcript Markers

**Rationale**: `USER:`/`AI:` are universal conversation markers that LLMs recognize instantly, improving comprehension without changing the flattening approach needed for synthesis report generation.

**Implementation**: Modify `synthesis_projection.py:87-94` to use `USER:`/`AI:` prefixes.

## Design Comparison

| Aspect | Before | After |
|--------|--------|-------|
| EXECUTION SUMMARY | In user message, misleading zeros | Removed (LLM derives from EVIDENCE) |
| BUILTIN SCENARIOS | In user message (dynamic) | In system prompt (cached) |
| Transcript markers | `[Task]`/`[Finding]` (ad-hoc) | `USER:`/`AI:` (standard) |
| Token cost per synthesis | ~300 extra for scenarios | Cached scenarios |
| LLM comprehension | Parse log format | Recognize conversation structure |

## Files Affected

| File | Change |
|------|--------|
| `user_message.py` | Remove EXECUTION SUMMARY and AVAILABLE BUILT-IN SCENARIOS sections |
| `synthesis_report_system.xml` | Add AVAILABLE BUILT-IN SCENARIOS to system prompt |
| `synthesis_projection.py` | Change transcript markers to USER:/AI: |

## Risk Assessment

**Low risk**: Changes are localized to prompt construction, not runtime logic.

- Removing EXECUTION SUMMARY: EVIDENCE section contains same information; no functional impact
- Moving scenarios to system prompt: Static content relocation; LLM behavior unchanged
- Changing markers: cosmetic format change; comprehension improves

## Testing Requirements

1. Run synthesis on loop with empty `step_results` but populated `loop_messages` → verify no misleading zeros
2. Compare synthesis output quality before/after marker change on same goal
3. Verify prompt cache hit rate improvement after scenarios move to system prompt

## References

- RFC-616: Synthesis phase design
- RFC-214: Loop message ledger
- IG-300: Scenario classifier implementation
- `synthesis_projection.py`: Evidence projection
- `user_message.py`: Synthesis user message builder