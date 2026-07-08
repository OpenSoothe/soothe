# IG-567: StrangeLoop Heuristic to Rules / Light-LLM Migration

**RFC**: RFC-630 (intake), RFC-624 (completion)
**Created**: 2026-07-08
**Status**: Implemented

## Summary

Replaced keyword/regex content-judgment heuristics across StrangeLoop with structured
light-LLM fields (Pass 1/2) and declarative config rules (`agent.loop.rules`).

## Changes

### Pass 1 (social / identity)

- Added `social_kind` to `IntakePass1LLMResult` and `IntentClassification`.
- `finalize_chitchat_response` uses `social_kind=identity` for deterministic
  identity rewrite instead of regex-only query matching.
- Vendor identity leaks rewrite to `build_canonical_identity_fallback` for identity turns;
  non-identity turns strip vendor markers instead of generic greeting fallback.
- Removed reasoning salvage regex from hot path; first Pass 1 call requires
  `social_kind` and retries with required `social_response` when social.
- Fixed double `finalize_chitchat_response` in `_runner_strange_loop`.

### Pass 2 (routing hints)

- Added `multi_phase` and `wire_subagent` to `IntakePass2LLMResult`.
- Replaced goal-regex multi-phase detection with Pass 2 ``multi_phase`` (wrapper removed).
- Replaced `infer_explicit_wire_subagent_from_goal` regex with `resolve_wire_subagent` (stub removed).

### Declarative rules config

- `StrangeLoopRulesConfig` under `agent.loop.rules` with completion, scenario,
  and plan_safety sections.
- Wired into `completion.py`, `scenario_classifier.py`, `plan_step_safety.py`.

### Failure intent

- LLM-first when enabled; keyword classifier is offline fallback only.

### Plan parsing

- `optimization.structured_plan.enabled` default `true`; regex fallback logs warning.

## Preserved (structural)

- `continue_keyword`, `structural_continuation`, checkpoint finalize gates.

## Removed legacy

- `is_identity_query` regex and `goal_has_explicit_multi_step_markers` wrapper.
- Pass 1 reasoning salvage and identity coalesce heuristics.

## Verification

- Loop 5d36 regression tests in `test_identity_query.py`.
- `./scripts/verify_finally.sh`
