# IG-382: Remove `tools` executor hint from `StepAction`

## Goal

Remove the optional `tools` field from `StepAction` and stop wiring `soothe_step_tools` from the AgentLoop executor into CoreAgent config. Legacy plan JSON may still include a `tools` array; `agent_decision_from_dict` continues to map known subagent names from that array onto `subagent` only.

## Scope

- `packages/soothe/src/soothe/core/agent_loop/state/schemas.py` — drop `tools` on `StepAction`
- Executor, `ExecutionHintsMiddleware`, CoreAgent docs/logging
- Tests and plan-generate prompt fragment (`optional … tools` wording)
- RFCs: `RFC-000`, `RFC-100`, `RFC-201`, `RFC-207`, `RFC-214`, `RFC-217`, `RFC-605` — remove `soothe_step_tools` / per-step tool hints from normative examples and tables

## Status

Completed.
