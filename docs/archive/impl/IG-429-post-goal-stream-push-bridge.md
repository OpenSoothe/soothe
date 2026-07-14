# IG-429: Post-Goal Ghost Phase Elimination (Push Bridge)

**Status**: Completed  
**Started**: 2026-05-22  
**Completed**: 2026-05-22  
**Related**: IG-427, IG-426, IG-410

---

## Summary

Eliminate the ~50s post-goal "ghost phase" where the daemon keeps processing stream chunks after the agent has finished. Root cause: `_poll_worker_responses` delivers at most **one** chunk per busy worker every **50ms** (~20/s), leaving ~1000 chunks queued when the worker exits.

**Solution**: Push bridge with zero poll delay on the chunk hot path—no ZeroMQ (see Appendix B in plan).

| Metric | Before (loop f010) | Target |
|--------|-------------------|--------|
| Goal complete → `astream() completed` | ~50s | **<2s** |
| Goal complete → CLI `task.complete` | ~50s | **<5s** |

---

## Root cause

1. Worker thread/process enqueues all `StreamChunk`s quickly, then `done`.
2. Main asyncio loop `_poll_worker_responses`: `get_nowait` once + `sleep(0.05)` per cycle.
3. Backlog at goal end: `~1000 × 0.05s ≈ 50s` ghost drain.

Secondary: early `status: idle` on `AGENT_LOOP_COMPLETED` while backlog remains (UX).

---

## Architecture

### Thread pool (`thread_runner`)

- `ResponsePusher`: `call_soon_threadsafe` → per-request `asyncio.Queue` (no `threading.Queue` on chunk path).
- Request dispatch: `("request", request_id, req, pusher)`.
- `_poll_worker_responses` → `_worker_health_watchdog`: dead worker + idle stale drain only.

### Process pool (`pool_runner`)

- Per-worker `_bridge_worker_responses` coroutine: blocking `mp.Queue.get(timeout=0.5)` in executor, immediate route (no 50ms throttle).
- `_poll_worker_responses` → `_worker_health_watchdog`: stuck/dead detection only.

### Query engine

- Remove early `_signal_turn_idle` inside stream loop on `turn_complete_pending`.
- Final `idle` only in `_run_stream` `finally` after coalescer flush.

---

## Files

| File | Change |
|------|--------|
| `runner/response_bridge.py` | New `ResponsePusher` |
| `runner/thread_runner.py` | Push + health watchdog |
| `runner/pool_runner.py` | Bridge coroutine + health watchdog |
| `query/engine.py` | Defer early idle |
| `tests/unit/runner/test_response_push_bridge.py` | New |

---

## Verification

```bash
./scripts/verify_finally.sh
```

Manual: polish README turn; `Goal completed` vs `runner.astream() completed` in `daemon.log` should be **<2s**.

---

## Status log

| Date | Note |
|------|------|
| 2026-05-22 | IG created; Push bridge implementation (no ZMQ) |
| 2026-05-22 | Implemented ResponsePusher, pool bridge, deferred early idle; daemon tests pass |
