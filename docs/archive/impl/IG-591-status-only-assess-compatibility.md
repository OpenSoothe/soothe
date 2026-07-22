# IG-591: Status-Only Assess Compatibility Restoration

**RFC**: RFC-604, RFC-640
**Created**: 2026-07-13
**Status**: Implemented

## Summary

Restore compatibility with status-only `StatusAssessment` outputs in plan-assess.
Recent planner changes treated status-only assess payloads as underspecified and
forced retries/coercion, which introduced noisy replan waves and repeated
end-stage verification behavior. This update reverts that behavior and keeps
`status` authoritative while deterministic post-processing derives progress and
terminal readiness from structural state.

## Problem

- Assess calls started rejecting status-only payloads (for example `{"status":"done"}`).
- Planner retried with a "return all fields" reminder and then coerced fields on failure.
- Coercion frequently produced low-confidence progress and extra generate/execute loops.
- This conflicted with existing deterministic derivation of progress from
  `status`, gap analysis, and execution evidence.

## Changes

### Planner assess flow

- Removed status-only underspecification helper from
  `packages/soothe/src/soothe/sloop/cognition/planner.py`.
- Removed retry prompt that required all `StatusAssessment` fields.
- Removed coercion fallback that injected synthetic reasoning/progress when
  assess remained status-only.

### Tests

- Updated
  `packages/soothe/tests/unit/core/loop/planning/test_planner_assess_raw_fallback.py`
  to assert status-only assess output is accepted as-is (single invocation, no
  retry/coercion).

## Expected Outcome

- Assess does not loop on field-completion retries for status-only output.
- Progress and terminal decisions remain governed by deterministic normalization
  and structural gating already present in plan-step safety and plan-assess routing.
- Fewer repetitive tail steps when a goal is near completion.

## Verification

- `pytest packages/soothe/tests/unit/core/loop/planning/test_planner_assess_raw_fallback.py`
