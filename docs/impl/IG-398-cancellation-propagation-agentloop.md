# IG-398: Cancellation Propagation for AgentLoop/Subagent Execution

## Status
In Progress

## RFC Links
- RFC-220: LangGraph Agent Loop Orchestrator

## Goals
- Ensure `Ctrl+C` / daemon thread cancel stops in-flight AgentLoop execution promptly.
- Prevent cancellation from being converted into normal step failure/success paths.
- Stop follow-up steps and subagent launches after cancellation is requested.

## Scope
- `packages/soothe/src/soothe/core/agent_loop/core/executor.py`
- `packages/soothe/src/soothe/core/runner/_runner_phases.py`

## Design Notes
- Treat `asyncio.CancelledError` as control-flow, not business failure.
- Re-raise `CancelledError` in broad exception wrappers so cancellation propagates to task boundary.
- Keep existing non-cancellation error handling unchanged.

## Verification Plan
- Add/update unit tests to assert cancellation is re-raised (not swallowed).
- Run focused unit tests for runner/executor cancellation paths.
- Run `./scripts/verify_finally.sh`.

