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
2. **Plan prompts** — plan-generate and gap analysis prefer one execute when a
   single CoreAgent wave can close the remaining gap; components may be 1–8.
   Pass 2 `multi_phase` still informs intake/terminal gates and prompt preference
   for ordered phases; it does **not** hard-require ≥2 plan steps.
3. **Wave cap** — plan-generate truncates / schema-caps at
   `DEFAULT_MAX_PLAN_STEPS_PER_WAVE` (10).

Anti-anchoring (reject terminal `done` for complex at iter=0 with no execute
evidence) is unchanged.

## Files

- `prompts/fragments/classifiers/intake_pass2_system.xml`
- `sloop/intention/pass2_classifier.py` (fail-safe)
- `sloop/cognition/plan_step_safety.py` (terminal / simple-intake gates)
- `sloop/stages/plan/generate_plan.py`, `assess.py`
- `prompts/fragments/instructions/plan_generate_instructions.xml`
- `prompts/fragments/instructions/plan_gap_analysis_instructions.xml`
- `prompts/user_message.py`
- Unit tests for Pass 2 fail-safe and CoreAgent-first plan preference

## Acceptance

- Pass 2 fail-open → `simple`
- Complex goals may emit a single CoreAgent step at iter=0 (including `multi_phase`)
- Plan/gap prompts encode CoreAgent-first single-execute preference
- Plans still capped at 10 steps per wave

## Cleanse (follow-up)

- Removed unused `adaptive_granularity` from `AgentDecision` / `PlanGeneration`
  (never read after `planning_utils` was deleted; wire still strips the token if
  an LLM emits it as a pseudo-step string).
- Dropped the IG-555 / IG-654 hard min-step (≥2) undersized replan/abort path from
  `plan_generate` / `plan_assess` / `plan_step_safety` (1-step plans are valid;
  max wave size remains 10).
- Dropped stale planner comments about the removed in-planner simple bypass prefix.
- Aligned Pass 2 fail-safe test fixtures with `simple` (not `complex`).
