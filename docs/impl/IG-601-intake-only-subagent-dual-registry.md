# IG-601: Intake-Only Subagent Dual Registry (True Invisibility)

**Created**: 2026-07-14
**Status**: Implemented
**Related**: [RFC-630](../specs/RFC-630-start-phase-llm-intake-and-branch-routing.md), [IG-599](IG-599-pass2-wired-subagent-direct-route.md), [IG-600](IG-600-intake-only-wire-subagent-exposure.md)

---

## Executive Summary

Make intake-only specialists (`browser_use`, `deep_research`, `academic_research`) **absent from the main CoreAgent graph** (not merely catalog-filtered). Register them on a parallel intake-only registry and invoke them **directly** from `invoke_wired_subagent`. `planner` stays on the open CoreAgent `task` catalog and continues to use resolve → execute.

---

## Design

1. `AgentBuilder` partitions `resolve_subagents()` into:
   - **catalog** → `create_deep_agent(subagents=catalog)` / `SootheNanoAgent.subagents`
   - **intake-only** → `SootheNanoAgent.intake_only_subagents` (lookup only; never on `task`)
2. `invoke_wired_subagent`:
   - **intake-only wire**: stream specialist (prefer `astream` custom+values; `ainvoke` fallback) → ledger Human/AI execute-step → route `goal_completion` (progress via IG-602 orphan card)
   - **catalog wire (`planner`)**: inject trivial plan → route `resolve_decision` (unchanged)
3. StrangeLoop `PlanContext` remains catalog-filtered (IG-600).
4. Open-hop `task` for those names fails naturally (not registered); keep middleware guard as belt-and-suspenders.

---

## Files

| File | Action |
|------|--------|
| `foundation/sloop/state/schemas.py` | `partition_subagent_specs` / `spec_subagent_name` |
| `foundation/coreagent/coding/builder.py` | Split catalog vs intake-only |
| `foundation/coreagent/coding/core_agent.py` + `lazy.py` | Hold intake-only registry + lookup |
| `orchestrator/nodes/invoke_wired_subagent.py` | Direct invoke path |
| `orchestrator/builder.py` + `routing.py` + `state.py` | Conditional edge after wired node |
| RFC-630 / IG-600 notes | Exposure: not on CoreAgent graph |

---

## Cleanse (related dead / dual paths)

- Removed `wired_directive_allows_intake_only` and ToolEnforcement “allow when wired” exception.
- `resolve_wire_subagent_for_step` / step-hint enforcement ignore intake-only names (never `soothe_step_subagent`).
- Prompt wording: intake-only specialists are not available via `task` at all.
- Catalog builder uses partitioned lists only (no post-filter of intake-only from catalog).
- Removed deepagents `task_catalog_subagents` / `catalog_subagent_names` (IG-600 advertise-subset API); listing == registration after dual registry.
- Tests: planner for CoreAgent task-path fixtures; assert intake-only `task` always blocked.

## Acceptance

- [x] IG authored
- [x] Intake-only specs not passed to `create_deep_agent`
- [x] Wired intake-only → direct invoke → goal_completion
- [x] Wired `planner` still → resolve → execute
- [x] Related dead / backward-compat dual paths cleansed
- [x] Verify green
