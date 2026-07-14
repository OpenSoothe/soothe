# IG-399: Plan Pre-Generate Evidence Probe and Flat PlanGeneration

## Status
In Progress

## RFC Links
- RFC-220: LangGraph Agent Loop Orchestrator
- RFC-604: Reason Phase Robustness

## Goals
- Reduce plan hallucination when workspace grounding is weak by forcing a bounded pre-generate evidence probe.
- Remove progressive planning guidance that depends on long exploratory chains.
- Flatten `PlanGeneration` output fields so decision payload is no longer nested.

## Scope
- `packages/soothe/src/soothe/core/agent_loop/graph/`
- `packages/soothe/src/soothe/core/agent_loop/core/planner.py`
- `packages/soothe/src/soothe/core/agent_loop/state/schemas.py`
- `packages/soothe/src/soothe/core/prompts/fragments/`
- `packages/soothe/src/soothe/config/`
- `config/config.dev.yml`
- `docs/specs/`

## Design Notes
- Split current combined plan node into `plan_assess` and `plan_generate`, with `plan_pre_generate` in between.
- Keep pre-generate evidence gathering deterministic and capped to three read-only probes.
- Preserve `PlanResult` external behavior while adapting the internal `PlanGeneration` schema.

## Verification Plan
- Update graph topology, schema, planner, and prompt unit tests.
- Run `./scripts/verify_finally.sh`.
