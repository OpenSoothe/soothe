# IG-358: Replan step ID collision and planner readiness

## Problem

When replanning with sequential numeric ids (`"1"`, `"2"`, …), new steps could reuse ids already present in `dependency_completion_ids()` from prior successful `step_results`. `get_ready_steps` then treated those steps as already done → **no ready steps** and a wasted Plan/Execute cycle.

## Fix

- `assign_plan_step_ids(decision, reserved_ids=…)` assigns unique **3-character** random ids (see `PLAN_STEP_ID_LENGTH` in `state/schemas.py`) from `a-z` + `0-9`, avoiding collision with `reserved_ids` and within the new decision.
- In `AgentLoop`, on `plan_action == "new"`, reserved ids are `dependency_completion_ids()`. On `plan_action == "keep"` with no `current_decision`, assign once against the same reserved set.

## References

- `LoopState.dependency_completion_ids` (IG-346)
- `_allocate_plan_step_id`, `assign_plan_step_ids` (`state/schemas.py`)
