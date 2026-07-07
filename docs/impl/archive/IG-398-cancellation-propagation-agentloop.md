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

## Follow-up: daemon `/cancel` grace and state ownership

**Problem:** `QueryEngine.cancel_current_query()` used a 2s `wait_for` on the query task, then cleared `_active_threads`, `_current_query_task`, and broadcast `idle` even when subagent unwind took longer. The TUI saw `idle` while the daemon kept streaming.

**Changes:**

- `daemon.cancel_grace_seconds` (default 30, `ge=1`) in `DaemonConfig`; wired into cancel await via `asyncio.wait_for(asyncio.shield(task), ...)`. On timeout, log a warning and `asyncio.create_task` a background drain — do not forge daemon state.
- `cancel_current_query` / `_cancel_thread_locked`: signal `task.cancel()`, await shield up to grace, broadcast only `[yellow]Cancellation requested.[/yellow]` — remove legacy “Query cancelled successfully” and synthetic `idle` (those come from `_run_stream` `finally`).
- After `create_task(_run_stream)`, `await asyncio.sleep(0)` in both `run_query` and `run_query_multithreaded` so the stream coroutine starts before `run_query` returns; avoids `/cancel` racing a task that has not entered `try` yet (no `finally` cleanup).

**Tests:** `packages/soothe/tests/unit/daemon/test_query_engine_cancel.py`.

