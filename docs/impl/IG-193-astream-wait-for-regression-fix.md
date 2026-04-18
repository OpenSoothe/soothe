# IG-193: Fix `asyncio.wait_for` + `__anext__` breaking slow LangGraph streams

## Problem

`_stream_phase()` used `asyncio.wait_for(chunk_iter.__anext__(), timeout=0.5)` to poll for cooperative cancellation (IG-157). On timeout, `wait_for` **cancels** the inner await, which corrupts the async iterator: the next `__anext__()` can complete immediately with `StopAsyncIteration` even though the graph is still running. Symptom: headless runs exit with few chunks and no LLM output when gaps between chunks exceed ~0.5s.

## Solution

Introduce `_await_next_astream_chunk()` that waits with `asyncio.wait({anext_task}, timeout=poll_s)`. Unlike `wait_for`, this does **not** cancel the pending read when the poll interval elapses; we only check `asyncio.current_task().cancelling()` and then cancel the `__anext__` task explicitly when stopping.

## Files

- `packages/soothe/src/soothe/core/runner/_runner_phases.py` — helper + `_stream_phase` loop
- `packages/soothe/tests/unit/core/runner/test_runner_stream_poll.py` — regression test

## Verification

`./scripts/verify_finally.sh`
