# IG-349: Unified loop-based subagent routing

## Status: In progress

## Goal

Remove direct subagent bypass (`_run_direct_subagent` / runner quick path). Route all queries—including slash-command hints—through intent classification and `AgentLoop`. Rename wire field `subagent` → `preferred_subagent` (breaking change).

## unified_classification contract

1. **`LoopState.unified_classification`**: `RoutingClassification | None`, set at loop start from merged intent + optional wire `preferred_subagent`.
2. **`PlanContext.unified_classification`**: Copied from `LoopState` in `_build_plan_context`.
3. **Planner**: `LLMPlanner.create_plan` continues to use `_apply_preferred_subagent` on `Plan`. `LLMPlanner.plan` applies the same policy to `PlanResult.decision` via `apply_preferred_subagent_to_agent_decision` (IG-349).
4. **Executor**: Every `core_agent.astream` input includes `unified_classification` when loop state has it (sequential wave, parallel per-step).

## Verification

- `./scripts/verify_finally.sh`

## References

- Plan: unified loop-based subagent routing (remove direct path + compat)
