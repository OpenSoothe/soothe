# IG-358: Replan step ID collision and planner readiness

> **Update (IG-303)**: Collision avoidance now uses a random uppercase **plan id** plus model step suffixes (`KFA-001`) instead of independent random 3-char step ids. Reserved-set checks still apply to full composite step ids.

## Problem

When replanning with sequential numeric ids (`"1"`, `"2"`, …), new steps could reuse ids already present in `dependency_completion_ids()` from prior successful `step_results`. `get_ready_steps` then treated those steps as already done → **no ready steps** and a wasted Plan/Execute cycle.

## Fix (historical; see IG-303)

- ~~`assign_plan_step_ids(decision, reserved_ids=…)` assigned unique **3-character** random step ids~~ — superseded by IG-303 (`allocate_plan_id` + scoped ``<PLAN>-<model>`` ids).
- In `AgentLoop`, on `plan_action == "new"`, reserved ids are `dependency_completion_ids()`. On `plan_action == "keep"` with no `current_decision`, assign once with inherited or fresh `plan_id`.

## References

- `LoopState.dependency_completion_ids` (IG-346)
- `allocate_plan_id`, `assign_plan_step_ids` (`state/schemas.py`, IG-303)
