# IG-701: Autopilot Job Token Consumption

**Created**: 2026-08-06  
**Status**: Implemented  
**Related**: [RFC-624](../specs/RFC-624-context-engine.md), [RFC-625](../specs/RFC-625-autopilot-monitor-context-engine-unification.md), [IG-689](IG-689-autopilot-top-step-mirror.md)

---

## Goal

Record per-goal token usage on Autopilot Context Engine `GoalNode.total_tokens_used`,
expose job subtree totals on job APIs, and show consumption in CLI autopilot job UI.

## Design

1. **Mirror path** — `step_completed` progress already carries cumulative
   `total_tokens_used` from `LoopState`. AutopilotService tracks a per-goal
   cursor, computes deltas, and writes `StepExecution.tokens_used` so CE
   accumulates via `complete_step` / `fail_step`.
2. **Attempt reset** — on `goal_started`, reset the cursor to `0` (new loop
   attempt starts token accounting at zero; CE keeps lifetime totals).
3. **Job total** — sum `GoalNode.total_tokens_used` over the `parent_id`
   subtree; surface on `list_jobs` / `get_job` / `dag_snapshot` / `top`.
4. **CLI** — `autopilot jobs`, `job`, and `top` display formatted token totals.

## Out of scope

- Changing StrangeLoop / solo-loop token accounting
