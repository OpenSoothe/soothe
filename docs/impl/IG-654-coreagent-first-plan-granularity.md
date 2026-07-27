# IG-654: CoreAgent-First Plan Granularity

## Goal

Stop StrangeLoop from inventing trivial multi-step plans when CoreAgent can finish
the deliverable in a single execute run.

## Motivation

CoreAgent already owns tools, `write_todos`, and `task` inside one execute step.
Low/medium work that is one coherent deliverable should stay on the `trivial` /
`simple` intake path (or a single complex step), not be split into discover → edit
→ verify StrangeLoop steps.

## Design

1. **Pass 2 intake** — widen `simple`; multi-file alone ≠ `complex`; prefer
   `simple` when one CoreAgent execute can discover+edit+verify. Fail-safe to
   `simple` (lightweight plan) instead of `complex`.
2. **IG-555 min-step guard** — enforce ≥2 steps only when Pass 2 `multi_phase`
   is true (explicit ordered phases). Non-phased `complex` may emit one step.
3. **Plan prompts** — plan-generate and gap analysis prefer one execute when a
   single CoreAgent wave can close the remaining gap; components may be 1–8.

Anti-anchoring (reject terminal `done` for complex at iter=0 with no execute
evidence) is unchanged.

## Files

- `prompts/fragments/classifiers/intake_pass2_system.xml`
- `sloop/intention/pass2_classifier.py` (fail-safe)
- `sloop/cognition/plan_step_safety.py`
- `sloop/nodes/plan_generate.py`, `plan_assess.py`
- `prompts/fragments/instructions/plan_generate_instructions.xml`
- `prompts/fragments/instructions/plan_gap_analysis_instructions.xml`
- `prompts/user_message.py`
- Unit tests for Pass 2 fail-safe, min-step guard, continuation undersized replan

## Acceptance

- Pass 2 fail-open → `simple`
- Non-`multi_phase` complex 1-step plans accepted at iter=0
- `multi_phase` complex still rejects undersized 1-step and forces replan
- Plan/gap prompts encode CoreAgent-first single-execute preference

## Cleanse (follow-up)

- Removed unused `adaptive_granularity` from `AgentDecision` / `PlanGeneration`
  (never read after `planning_utils` was deleted; wire still strips the token if
  an LLM emits it as a pseudo-step string).
- Deduped min-step unit tests into `test_plan_step_safety.py` (removed from
  ledger-projection suite).
- Dropped stale planner comments about the removed in-planner simple bypass prefix.
- Aligned Pass 2 fail-safe test fixtures with `simple` (not `complex`).
