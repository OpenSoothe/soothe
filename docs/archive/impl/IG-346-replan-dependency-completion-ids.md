# IG-346: Replanned steps — dependency completion across waves

## Status

Complete.

## Problem

When `plan_action == "new"`, `LoopState.completed_step_ids` is cleared before executing the new `AgentDecision`. New steps often declare `dependencies` on prior-wave IDs (e.g. `step_001`). Those IDs are no longer in `completed_step_ids`, so `get_ready_steps` returns empty → `No ready steps to execute`.

## Fix

Introduce `LoopState.dependency_completion_ids()`: union of `completed_step_ids` and successful `step_result.step_id` values. Use this set everywhere readiness or remaining-step checks need dependency satisfaction.

## Files

- `packages/soothe/src/soothe/cognition/agent_loop/state/schemas.py`
- `packages/soothe/src/soothe/cognition/agent_loop/core/agent_loop.py`
- `packages/soothe/src/soothe/cognition/agent_loop/core/executor.py`
- `packages/soothe/src/soothe/cognition/agent_loop/core/plan_phase.py`
- `packages/soothe/tests/unit/cognition/agent_loop/state/test_schemas.py`
