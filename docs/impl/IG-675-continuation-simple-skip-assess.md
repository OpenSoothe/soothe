# IG-675 Continuation Simple Skip Assess

## Context

Loop `cbe1` goal 1 (Pass2 `simple`) spent ~4 minutes before first plan:
continuation-assess LLM (~144s) + schema repair retry + lightweight generate (~57s).

`trivial` ≠ `simple` (Pass2 / RFC-630): trivial skips planning; simple needs
lightweight `plan_generate`. Continuation+simple still ran `assess_continuation`,
but `_apply_continuation_intake_guardrails` forbids bootstrap for SIMPLE — so the
assess LLM cannot change the route and was pure latency.

## Goals

- Skip `assess_continuation` for continuation+`simple` (same early-return as COMPLEX).
- Keep continuation+`trivial` on the assess discriminator (bootstrap allowed).
- Coerce invalid `goal_progress` prose to `none` so structured bind does not burn
  a repair retry on remaining assess schemas.

## Superseded routing note

IG-676 routes all mid-loop goals (including simple) through `gather_evidence` →
`evaluate` rather than preprocess → evaluate. The skip-assess behavior for simple
still lives in evaluate (`mid_loop_skip_continuation_assess`).

## Out of scope

- Restoring fresh-loop `simple` to lightweight generate (today collapsed onto
  trivial 1-step inject) — separate product change.
- Pass1/Pass2 model latency.

## Validation

- Unit: continuation+simple → `continue_generate`, assess LLM not called
- Unit: continuation+trivial bootstrap still works
- Unit: `goal_progress` prose coerces on ContinuationAssessment / StatusAssessment / PlanResult
- `./scripts/verify_finally.sh`
