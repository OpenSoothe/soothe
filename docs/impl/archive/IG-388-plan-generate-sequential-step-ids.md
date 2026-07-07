# IG-388: Plan-generate goal-continuous local step ids

**Status:** Completed  
**Scope:** AgentLoop plan-generate path — local step tokens before `assign_plan_step_ids`.

## Problem

Models reliably emit `01`, `02`, … on every new plan wave. Within one goal, prior waves already used those numeric suffixes (as `PLAN-01`, `PLAN-02` after scoping). Restarting at `01` each time is confusing in logs, events, and cross-wave dependency references.

## Approach

1. Compute the maximum numeric suffix already seen on this goal from `LoopState.step_results`, `completed_step_ids`, and in-flight `current_decision` step ids (`PLAN-03` → 3, `step_004` → 4).
2. After each successful `PlanGeneration` with `plan_action == "new"`, renumber `decision.steps` in order to the next free integers (`03`, `04`, …), remapping in-plan `dependencies` only.
3. Optional plan-context hint on the generate-phase human when `next_start > 1` so the model can align prose; runtime renumbering remains authoritative.

## Files

- `packages/soothe/src/soothe/core/agent_loop/state/schemas.py` — helpers + `renumber_decision_local_step_ids_for_goal_continuation`
- `packages/soothe/src/soothe/core/agent_loop/core/planner.py` — apply renumber before `_combine_results`
- `packages/soothe/src/soothe/core/prompts/builder.py` — `<PLAN_STEP_ID_HINT>` for generate phase when continuing
- `packages/soothe/src/soothe/core/prompts/fragments/instructions/plan_generate_instructions.xml` — document continuation
- Tests under `packages/soothe/tests/unit/…`
