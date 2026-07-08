# Draft: Plan-Assess Prior Goal Completion Bias Mitigation

**Status**: Draft
**Created**: 2026-07-07
**Authors**: (analysis draft)
**Related**: RFC-630, IG-551, IG-540, docs/drafts/2026-07-06-two-pass-intake-classification.md
**Motivating observation**: Plan-assess early termination on continuation goals that require further waves, correlated with prior goal completion projection in Slice A.

---

## 1. Problem Statement

### 1.1 Prior Goal Completion Framing

Prior `goal_completion` ledger units carry a "completed successfully" narrative. When projected into plan-assess prompts (Slice A via `_project_planner_ledger_mid_goal_isolated`), this framing can:

1. **Bias toward wrap-up tone** — "Ok, now apply the fix" after a completed goal sees prior completion + acknowledgment, triggering "user confirming wrap-up" pattern-match.
2. **Leak completion semantics** — The prior goal's `status="done"` and `goal_progress="complete"` fields are visible in the projected ledger, even though they describe a different goal.

### 1.2 Early Termination Mechanism

`plan_assess.py` lines 432-481 routes to goal completion when `assessment.goal_progress == "complete"`:

```python
if assessment.goal_progress == "complete":
    # Routes directly to goal completion
    return {"plan_route": PLAN_ROUTE_GOAL_DONE}
```

This bypass does NOT verify:
- Execution state for the **current** goal (step_results, iteration count)
- Intake classification (complex goals need multiple waves)
- Remaining plan steps (has_remaining_steps)

### 1.3 Interaction with Intake Classification

RFC-630's two-pass architecture removes prior context from Pass 1 (social/task decision). However:
- **Pass 2** still receives prior projection (needed for reference resolution)
- **Plan-assess** on iter > 0 uses Slice A (prior goal completions)
- **Continuation-assess** uses the same projection

The bias is therefore present at:
- Pass 2 scope classification (context for "apply it")
- Plan-assess status assessment (mid_goal projection)
- Continuation-assess discriminator

---

## 2. Root Cause Analysis

### 2.1 Semantic Overlap

| Prior Goal Completion Content | Current Goal Perception |
|------------------------------|------------------------|
| "Goal completed successfully" | Signals "completion mode" |
| "Recommended next actions: ..." | Could be interpreted as "already suggested" |
| Terminal report tone | Matches "done" pattern |

When the user says "Ok, now X", the model sees:
- Prior: "Goal completed successfully"
- Current: "Ok, now X"

The "Ok" acknowledgment + prior completion reinforcement creates false wrap-up signal.

### 2.2 Slice A Composition

`_project_planner_ledger_mid_goal_isolated`:

```python
slice_a = project_cross_goal_completion_tail(loop_messages, k=exec_cfg.cross_goal_completion_tail)
seg_start = _current_goal_segment_start(loop_messages)
current_segment = [m for m in loop_messages[seg_start:] if phase in _MID_GOAL_CURRENT_PHASES]
combined = [*slice_a, *current_segment]
```

Slice A contains prior `goal_completion` Human/AI pairs. The current_segment contains `intent_classify`, `plan_generate`, `execute_step` for the current goal.

**Problem**: Slice A's completion tone is adjacent to current goal's early-phase messages. No semantic boundary separates them.

### 2.3 Goal Progress Routing

The `goal_progress == "complete"` routing was designed for:
- Goals that genuinely finished mid-wave (tool output indicates completion)
- Goals where prior execution achieved the objective

But the **assessment LLM** may return `goal_progress="complete"` due to:
- Pattern-matching prior completion tone
- Interpreting acknowledgment phrases as wrap-up
- Missing execution evidence for the current goal (iter=0, no step_results)

---

## 3. Proposed Architecture

### 3.1 Principle: Prior Goals Are Context, Not Directive

Prior goal completions should:
- Provide reference resolution ("apply it" → what is "it")
- Inform continuation depth (follow-up to complex work often complex)
- Supply recommended next actions as suggestions

Prior goal completions should NOT:
- Determine current goal completion status
- Bias plan-assess toward "done"
- Trigger early termination without execution evidence

### 3.2 Projection Boundary Marker

**Option A**: Inject semantic boundary before prior goal completions in projected ledger:

```
[PRIOR_GOAL_COMPLETION_BOUNDARY]
The following messages describe PRIOR goals (already completed).
They provide context for reference resolution only.
Current goal assessment should NOT use prior goal status as evidence.
---

<goal_completion phase messages>
```

This teaches the model to treat prior completions as background, not directive.

**Option B**: Compact prior goal completions to metadata-only:

```python
_compact_goal_completion_unit_for_projection(unit) → 
  "Prior goal: {goal_text[:50]} (completed). Recommended next: {next_actions[:100]}"
```

Removes completion narrative, keeps reference context.

### 3.3 Plan-Assess Projection Exclusion

**Option C**: Exclude prior goal completions from plan-assess projection entirely:

```python
# In project_planner_ledger for mode="mid_goal":
# Use prior_progress digest instead of Slice A goal_completion units
if kind == "assess":
    # prior_progress digest provides execution context
    # No prior goal_completion projection
```

Pros:
- Clean separation — plan-assess sees only current goal ledger
- prior_progress digest (RFC-227) provides wave-level context without completion tone

Cons:
- Loses reference resolution ("apply it" ambiguity)
- Continuation goals lose recommended next actions

### 3.4 Structural Guardrails (IG-551-style)

Add P0 hard constraint in plan_assess.py:

```python
# Early termination guard (P0)
if assessment.goal_progress == "complete":
    # Verify execution evidence exists for current goal
    if state.iteration == 0 and not state.step_results:
        logger.warning("[Plan] Reject premature 'complete' at iter=0 no execution")
        assessment.status = "replan"
        assessment.goal_progress = "medium"
        return {"assess_route": "continue_generate"}

    # Verify intake classification permits single-wave completion
    intake_label = intake_label_from_state(state)
    if intake_label == IntakeLabel.COMPLEX and not state.has_remaining_steps():
        logger.warning("[Plan] Reject 'complete' for complex intake with no steps executed")
        # Force replan with evidence-gather path

    # Verify execution occurred (not just pattern-matched prior completion)
    if len(state.step_results) < min_steps_for_goal(state):
        logger.warning("[Plan] Reject 'complete' with insufficient execution evidence")
```

---

## 4. Comparison of Options

| Aspect | Option A (Boundary) | Option B (Compact) | Option C (Exclude) | Option D (Guardrails) |
|--------|---------------------|--------------------|--------------------|------------------------|
| Semantic clarity | Adds boundary marker | Removes narrative | Clean separation | Post-hoc check |
| Reference resolution | Preserved | Partial | Lost | N/A (guardrail) |
| Prior action hints | Preserved | Condensed | Lost | N/A |
| Implementation | Prompt edit | Projection edit | Projection logic | plan_assess.py |
| Risk | Model may ignore boundary | Over-condensation | Continuation quality loss | Guardrail misses edge cases |

---

## 5. Recommended Combination

**Combine Options A + D**:

1. **Projection Boundary Marker** (Option A) — Teach model to treat prior completions as context
2. **Structural Guardrails** (Option D) — Enforce minimum execution evidence before "complete"

Why not Option C (Exclude):
- Continuation goals need recommended next actions from prior completions
- Reference resolution requires prior goal context
- prior_progress digest is wave-level; prior goal completion is goal-level

---

## 6. Implementation Phases

### Phase A — Projection Boundary Marker

1. Edit `_compact_goal_completion_unit_for_projection` to add boundary text:
   ```python
   _GOAL_COMPLETION_CONTEXT_BOUNDARY = (
       "[PRIOR_GOAL_CONTEXT]\n"
       "The following describes a prior goal (already completed). "
       "Use for reference resolution and recommended actions. "
       "DO NOT use prior goal status as evidence for current goal completion.\n"
   )
   ```
2. Wire into `project_planner_ledger` for mid_goal mode
3. Unit tests: prior completion projection includes boundary marker

### Phase B — Plan-Assess Execution Evidence Guard

1. Add guard in `node_plan_assess` before `goal_progress == "complete"` routing:
   ```python
   if assessment.goal_progress == "complete":
       if state.iteration == 0 and not state.step_results:
           # Reject premature completion
       if intake_label == IntakeLabel.COMPLEX and len(state.step_results) < 1:
           # Complex goals need at least one wave
   ```
2. Log rejection for observability
3. Unit tests: guard rejects "complete" on new complex goals

### Phase C — Prior Goal Completion Context Tuning

1. Evaluate `cross_goal_completion_tail` default value (currently 1-2)
2. Consider reducing to 1 for plan-assess, 2 for execute-step (where reference resolution matters more)
3. Integration tests: continuation goals still route correctly

---

## 7. Success Criteria

| Criterion | Target |
|-----------|--------|
| Premature "complete" rejection | Log warning when iter=0 + no step_results |
| Complex intake early termination | Guard forces replan when intake=complex + no execution |
| Prior completion boundary | 100% of Slice A projections include boundary marker |
| Continuation reference resolution | "apply it" still resolves to prior goal context |
| Latency | No measurable change (prompt edit only) |

---

## 8. Open Questions

1. **Prior progress digest vs Slice A** — Should plan-assess use prior_progress digest exclusively (no Slice A goal_completion)?
2. **Continuation-assess projection** — Same boundary marker needed for continuation discriminator?
3. **Intake Pass 2 prior context** — Should Pass 2 receive compacted prior completion (metadata only)?

---

## 9. References

- RFC-630: Start-Phase LLM Intake and Branch Routing
- IG-551: Mid-Loop Continuation Planning Coordination
- IG-540: Intent-Classify Prompt Ledger Optimization
- RFC-227: Prior Progress Digest
- `plan_ledger_projection.py`: Slice A projection logic
- `plan_assess.py`: Early termination routing