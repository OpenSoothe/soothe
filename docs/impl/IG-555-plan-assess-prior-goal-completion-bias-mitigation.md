# IG-555: Plan-Assess Prior Goal Completion Bias Mitigation

**RFCs**: RFC-630 (two-pass intake), RFC-214 (ledger projection), RFC-226 (continuation routing)
**Created**: 2026-07-07
**Status**: Implemented
**Related**: IG-551 (continuation coordination), IG-540 (intent-classify ledger optimization), IG-554 (two-pass intake)
**Motivating observation**: Continuation goals with prior completion in Slice A produce undersized 1-step plans; execution succeeds → premature goal_done.

---

## Executive Summary

Prior `goal_completion` ledger units projected into plan-phase prompts anchor the planner on "Recommended next actions", producing undersized plans for multi-part continuation goals. Execution succeeds on the undersized plan → plan-assess returns `goal_progress="complete"` → premature goal termination.

**Solution**: Two complementary interventions:
1. **Projection boundary marker** — teach model prior completion is reference resolution, not plan template
2. **Structural guardrail** — enforce minimum 2 steps for complex intake at iter=0

---

## Problem Statement

### Failure Chain

```
User goal: "docker-build then start components and run e2e" (multi-part)
    ↓
Intake: complex (correct)
    ↓
Slice A projection: prior_goal_completion "Recommended: apply signature change"
    ↓
Plan-generate: anchors on prior recommendation → 1 step (undersized)
    ↓
Execute: 1 step succeeds
    ↓
Plan-assess: prior completion tone + success → goal_progress="complete"
    ↓
Premature goal_done (goal scope only partially addressed)
```

### Root Cause

Prior goal completion's "Recommended next actions" section is scoped for that goal's terminal report, not as a decomposition template for the new goal. Plan-generate treats it as ready-to-execute work unit instead of signal to re-decompose based on new goal scope.

### Why Not Addressed by Existing Guardrails

| Guardrail | Coverage | Gap |
|-----------|----------|-----|
| IG-551 P0 (complex intake → no bootstrap) | Continuation-assess routing | Doesn't affect plan-generate decomposition |
| `status="done"` at iter=0 rejection (plan_assess.py line 1436) | Assessment status field | `goal_progress="complete"` routing at line 432 bypasses this |
| Pass 1 no prior context (RFC-630) | Social/task decision | Pass 2 and plan-phases still see Slice A |

---

## Target Design

### 1. Projection Boundary Marker

Add semantic boundary before prior goal completion in Slice A projection:

```python
_GOAL_COMPLETION_CONTEXT_BOUNDARY = (
    "<PRIOR_GOAL_CONTEXT role=\"reference_resolution\">\n"
    "The following completed goal provides context for resolving user mentions.\n"
    "DO NOT use the recommended actions below as your plan template.\n"
    "Decompose the current goal independently based on its scope.\n"
)
```

**Application scope**:

| Projection path | Apply boundary | Reason |
|-----------------|----------------|--------|
| `project_planner_ledger` (plan-assess) | ✅ Yes | Anchoring risk in assessment |
| `project_planner_ledger` (plan-generate) | ✅ Yes | Primary target — planner decomposition |
| `project_continuation_assess_ledger` | ✅ Yes | Bootstrap vs plan_generate decision |
| `project_cross_goal_completion_tail` (execute Slice A) | ❌ No | Executor needs prior actions for grounding |
| `project_last_goal_completion_for_intake` (Pass 2) | ❌ No | Classifier needs prior for scope judgment |

### 2. Structural Guardrail

Minimum plan steps for complex intake at iter=0:

```python
def _plan_has_minimum_steps_for_intake(
    decision: AgentDecision | None,
    intake_label: IntakeLabel,
    state: LoopState,
) -> bool:
    """P0: Complex intake at iter=0 must produce multi-step plan."""
    if intake_label != IntakeLabel.COMPLEX:
        return True  # Simple/trivial can have 1 step
    if state.iteration > 0:
        return True  # Already executed; replan may consolidate
    if decision is None or not decision.steps:
        return False
    return len(decision.steps) >= 2  # Complex needs at least 2 steps
```

**Application points**:
1. `node_plan_assess` — before routing to execute, reject undersized plan
2. `node_plan_generate` (or `planner.py` post-processing) — force immediate replan if undersized

**Guardrail scope**: All complex intake at iter=0 (not just continuation goals).

---

## Implementation Phases

### Phase A — Projection Boundary Marker

| File | Change |
|------|--------|
| `prompts/plan_ledger_projection.py` | Add `_GOAL_COMPLETION_CONTEXT_BOUNDARY` constant |
| `prompts/plan_ledger_projection.py` | Modify `_compact_goal_completion_unit_for_projection` to prepend boundary |
| `prompts/plan_ledger_projection.py` | Apply in `project_planner_ledger` for planning modes |
| `prompts/plan_ledger_projection.py` | Apply in `project_continuation_assess_ledger` |
| `tests/unit/sloop/prompts/test_plan_ledger_projection*.py` | Assert boundary marker present in projected ledger |

**Implementation detail**:

```python
# In plan_ledger_projection.py

_GOAL_COMPLETION_CONTEXT_BOUNDARY = (
    "<PRIOR_GOAL_CONTEXT role=\"reference_resolution\">\n"
    "The following completed goal provides context for resolving user mentions.\n"
    "DO NOT use the recommended actions below as your plan template.\n"
    "Decompose the current goal independently based on its scope.\n"
)

def _compact_goal_completion_unit_for_projection(unit: list[BaseMessage]) -> list[BaseMessage]:
    """Rewrite goal_completion human envelopes with boundary marker for planning prompts."""
    out: list[BaseMessage] = []
    for msg in unit:
        copy_msg = _deep_copy_message(msg)
        if getattr(copy_msg, "phase", None) == "goal_completion" and _is_loop_human_message(copy_msg):
            # Prepend boundary marker to the compacted human content
            copy_msg = _set_message_content(
                copy_msg,
                _GOAL_COMPLETION_CONTEXT_BOUNDARY + "Prior goal completed. Details follow."
            )
        out.append(copy_msg)
    return out
```

**Note**: The boundary marker is prepended to the **human envelope** of the goal_completion unit. The AI response (completion body) remains unchanged.

### Phase B — Structural Guardrail

| File | Change |
|------|--------|
| `orchestrator/nodes/plan_assess.py` | Guard before `goal_progress=complete` routing; uses shared helper |
| `orchestrator/nodes/plan_generate.py` | Guard post-processing; wired replan via `route_after_plan` |
| `orchestrator/routing.py` | `route_after_plan` loops to `plan_generate` on undersized replan |
| `orchestrator/builder.py` | Self-edge on `plan_generate` for replan loop |
| `cognition/plan_step_safety.py` | Shared `plan_has_minimum_steps_for_intake` helper |
| `tests/unit/core/prompts/test_plan_ledger_projection_ig380.py` | Boundary + helper tests |
| `tests/unit/core/loop/orchestrator/nodes/test_plan_assess_ig555_guardrail.py` | Assess routing guardrail |
| `tests/unit/core/loop/orchestrator/nodes/test_plan_generate_ig555_guardrail.py` | Generate replan guardrail |
| `tests/integration/core/test_loop_agent_continuation_planning.py` | Replan + boundary integration |

**Implementation in `node_plan_assess.py`**:

```python
# In plan_assess.py, before line 432 (goal_progress == "complete" routing)

def _plan_has_minimum_steps_for_intake(
    decision: AgentDecision | None,
    intake_label: IntakeLabel,
    state: LoopState,
) -> bool:
    """P0: Complex intake at iter=0 must produce multi-step plan."""
    if intake_label != IntakeLabel.COMPLEX:
        return True
    if state.iteration > 0:
        return True
    if decision is None or not decision.steps:
        return False
    return len(decision.steps) >= 2

# Before goal_progress routing:
if assessment.goal_progress == "complete":
    intake_label = intake_label_from_state(state)
    if not _plan_has_minimum_steps_for_intake(state.current_decision, intake_label, state):
        logger.warning(
            "[Plan] Reject goal_progress=complete: undersized plan (%d step) for complex intake at iter=0",
            len(state.current_decision.steps) if state.current_decision else 0,
        )
        assessment.goal_progress = "medium"
        return {"assess_route": "continue_generate"}
    # ... proceed to goal completion routing
```

### Phase C — Verification

| Test | Assert |
|------|--------|
| Unit: boundary marker in projection | `_compact_goal_completion_unit_for_projection` output starts with `<PRIOR_GOAL_CONTEXT` |
| Unit: guardrail rejects undersized plan | Complex intake + iter=0 + 1-step plan → `assess_route: continue_generate` |
| Unit: guardrail allows valid plan | Complex intake + iter=0 + 2-step plan → routes to goal_done |
| Unit: guardrail skips at iter>0 | iter=1 + 1-step plan → routes normally |
| Integration: continuation complex goal | Produces ≥ 2 steps, does not prematurely terminate |

---

## Observability

- Log when guardrail activates: `[Plan] Reject undersized plan (%d step) for complex intake at iter=0, forcing replan`
- Log when boundary marker applied: Debug-level in `_compact_goal_completion_unit_for_projection`
- Telemetry: guardrail activation rate per goal (tuning signal for threshold adjustment)

---

## Success Criteria

| Criterion | Target |
|-----------|--------|
| Complex intake undersized plan rate | Near-zero (guardrail catches 100%) |
| Boundary marker presence | All planning-phase Slice A projections include marker |
| Continuation goal step count | ≥ 2 for complex intake at iter=0 |
| Regression: simple/trivial intake | Still produces 1-step plans (no false rejection) |
| Regression: iter>0 replan | Can produce 1-step consolidation (guardrail skips) |

---

## Files Changed

```
packages/soothe/src/soothe/foundation/sloop/prompts/plan_ledger_projection.py
packages/soothe/src/soothe/foundation/sloop/cognition/plan_step_safety.py
packages/soothe/src/soothe/foundation/sloop/orchestrator/nodes/plan_assess.py
packages/soothe/src/soothe/foundation/sloop/orchestrator/nodes/plan_generate.py
packages/soothe/src/soothe/foundation/sloop/orchestrator/routing.py
packages/soothe/src/soothe/foundation/sloop/orchestrator/builder.py
packages/soothe/tests/unit/core/prompts/test_plan_ledger_projection_ig380.py
packages/soothe/tests/unit/core/loop/orchestrator/nodes/test_plan_assess_ig555_guardrail.py
packages/soothe/tests/unit/core/loop/orchestrator/nodes/test_plan_generate_ig555_guardrail.py
packages/soothe/tests/integration/core/test_loop_agent_continuation_planning.py
```

---

## References

- RFC-630: Start-Phase LLM Intake and Branch Routing
- RFC-214: Loop Message Surface (ledger phases)
- RFC-226: Continuation-Aware plan_assess
- IG-551: Mid-Loop Continuation Planning Coordination
- IG-540: Intent-Classify Prompt Ledger Optimization
- IG-554: Two-Pass Intake Classification Implementation
- Design draft: `docs/drafts/2026-07-07-plan-assess-prior-goal-bias-mitigation.md`