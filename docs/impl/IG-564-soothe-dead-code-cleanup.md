# IG-564: Soothe Legacy & Dead Code Cleanup (Moderate Scope)

## Goal

Remove confirmed unreachable legacy code in `packages/soothe` after RFC-222 (autonomous loop removal) and RFC-625 (GoalEngine deletion).

## In scope

1. **Runner**: dead pre-stream path, `CheckpointMixin`, `RunArtifactStore` wiring
2. **Cron**: `SchedulerService` in-memory task registry (keep `ScheduleSpec`)
3. **Planner**: unused `PlannerProtocol` methods (`create_plan`, `revise_plan`, `reflect`), legacy runner types
4. **Misc**: `path_display.py`, `cleanup_execution_resources()` no-op, stale tests

## Out of scope (keep)

- Config YAML migration in `settings.py`
- SQLite goal_records column migration
- `build_plan_assess_message()` compat shim
- `langchain_adapter.py`, `examples/`, MemU subtree

## Verification

- `./scripts/verify_finally.sh` passes
