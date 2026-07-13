# IG-641 Continuation Simple Bootstrap and Single-Pass Plan Bias

## Context

Continuation turns classified as `simple` were routed directly to `plan_generate`.
This skipped the continuation discriminator path in `plan_assess`, so the loop
could not bootstrap a single execute step even when prior execution context was
already sufficient.

## Goals

- Route continuation+simple through `plan_assess` so `assess_continuation` can
  choose `bootstrap`.
- Keep continuation+complex behavior unchanged (forced full plan generation).
- Strengthen plan-generate instruction bias toward one-step waves when there is
  one actionable gap and projected prior context already covers prerequisites.

## Implementation

1. Update continuation branch routing for `IntakeLabel.SIMPLE` to `plan_assess`.
2. Update continuation first-plan logic to skip discriminator only for
   `IntakeLabel.COMPLEX`; allow `IntakeLabel.SIMPLE` to run discriminator.
3. Add explicit instruction in `PLAN_GENERATE` step-count guidance to emit
   exactly one step when a single actionable gap can be completed in one execute wave.
4. Update and add unit tests for continuation routing and bootstrap behavior.

## Validation Plan

- `packages/soothe/tests/unit/core/loop/orchestrator/test_route_by_intent.py`
- `packages/soothe/tests/unit/core/loop/orchestrator/test_loop_agent_continuation_planning.py`

