# IG-303: Plan-scoped step IDs (`<PLANID>-<model-step-id>`)

## Status

Complete.

## Goal

- Allocate a random **3-character uppercase** plan id (A–Z) per **new** plan.
- On `plan_action == "keep"`, reuse `LoopState.plan_id` when scoping steps from a fresh parsed decision.
- Preserve model-generated step ids (e.g. `001`, `002`); runtime ids become `KFA-001`, `KFA-002`.
- Remap in-plan `dependencies` to composite ids; external refs (e.g. prior-wave ids) unchanged (IG-346).

## Implementation

- `allocate_plan_id(decision, reserved_step_ids=…)` in `state/schemas.py`: try random plan ids until no composite `composite_step_id(step.id, plan_id)` collides with `reserved_step_ids` and composites are unique within the decision.
- `assign_plan_step_ids(decision, plan_id=…)` rewrites step ids (idempotent if already prefixed with this plan).
- `LoopState.plan_id: str | None` set when a plan is assigned in `AgentLoop` (`new` always allocates; `keep` without `current_decision` uses existing `plan_id` when present).
- Replaces per-step random 3-char assignment (IG-358) while preserving collision safety.

## Files

- `packages/soothe/src/soothe/core/agent_loop/state/schemas.py`
- `packages/soothe/src/soothe/core/agent_loop/core/agent_loop.py`
- `packages/soothe/tests/unit/core/agent_loop/state/test_schemas.py`
