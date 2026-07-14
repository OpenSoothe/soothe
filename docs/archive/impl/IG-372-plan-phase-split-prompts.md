# IG-372: Plan-assess vs plan-generate split prompts

## Status

Completed (verify_finally.sh passed).

## Goal

- Align system instructions with RFC-604 two-call planner: **assess** uses instructions that match `StatusAssessment` only; **generate** keeps full plan/step policy (`PlanGeneration` + `AgentDecision`).
- Reduce token load on `plan-assess` (drop the old combined plan/execute instruction block from the assess system prompt).
- Compact plan-context human when `iteration > 0` and tighten prior-conversation intro.

## Scope

- `packages/soothe/src/soothe/core/prompts/builder.py`
- `packages/soothe/src/soothe/core/prompts/fragments/` (new assess fragment, export)
- `packages/soothe/src/soothe/core/agent_loop/core/planner.py` (build assess vs generate message lists; retry uses last invoked payload)
- Unit tests under `packages/soothe/tests/unit/core/agent_loop/core/`

## Non-goals

- Changing `StatusAssessment` / `PlanGeneration` schemas.
- Config YAML changes.

## Verification

`./scripts/verify_finally.sh`
