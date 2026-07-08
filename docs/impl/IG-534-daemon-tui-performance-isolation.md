# IG-534: Daemon ↔ TUI Performance Isolation

**RFC**: [RFC-614](../specs/RFC-614-unified-streaming-messaging.md), [RFC-450](../specs/RFC-450-daemon-communication-protocol.md)  
**Design**: [docs/archive/drafts/2026-07-01-daemon-tui-performance-isolation-design.md](../archive/drafts/2026-07-01-daemon-tui-performance-isolation-design.md)  
**Created**: 2026-07-01  
**Updated**: 2026-07-01  
**Status**: Phase 3 complete  
**Priority order**: B → A → C (correctness, fairness, latency)

---

## Executive Summary

Multi-client, multi-loop workloads expose weak **performance isolation** on the daemon streaming path: shared thread pool, global `ResponsePusher` semaphore, event-bus NORMAL drops, and TUI inbound drop-oldest. This IG implements a phased program with measurable gates.

---

## Phase 0 — Observability & load harness

| Task | Status | Notes |
|------|--------|-------|
| 0.1 Event bus drop metrics by priority/topic | **Done** ✅ | `get_event_bus_drop_counts()` in `event/bus.py` |
| 0.2 Response bridge queue wait metrics | **Done** ✅ | Existing `ThreadPoolMetrics` in `thread_runner.py` |
| 0.3 Integration load harness | **Done** ✅ | `test_multi_loop_performance.py` — 4 loops, goal_completion delivery |
| 0.4 TUI synthesis-visible latency metric | **Done** ✅ | `TurnLatencyStats` in `session_stats.py`, wired in turn pipeline |

---

## Phase 1 — Correctness (B): no silent loss

| Task | Status | Files |
|------|--------|-------|
| 1.1 Terminal `done` blocking put | **Done** ✅ | `response_bridge.py` |
| 1.2 Stale busy worker recovery | **Done** ✅ | `thread_runner.py` |
| 1.3 Pool runner terminal parity | **Done** ✅ | `pool_runner.py` uses blocking `Queue.put` |
| 1.4 Event bus: `goal_completion` → HIGH + block on overflow | **Done** ✅ | `event/bus.py` — `_wire_has_goal_completion_phase`, `_should_block_on_queue_full` |
| 1.5 User-visible NORMAL block at 90% queue | **Done** ✅ | `event/bus.py` — `_is_user_visible_for_backpressure` |
| 1.6 Client `stream_degraded` visibility | **Done** ✅ | `websocket.py` callback, `session_stats.py` tracking |
| 1.7 `/clear` cancel in-flight | **Done** ✅ | `_execution.py:569` — calls `_interrupt_daemon_agent_turn()` before `new_loop()` |
| 1.8 Ledger fetch on turn abort | **Done** ✅ | `_execution.py:947` — `_try_recover_goal_completion_from_ledger()` on error |

**Exit criteria** — All passed

- [x] Load harness: 0 terminal delivery failures (`test_multi_loop_goal_completion_delivery`)
- [x] Load harness: 0 silent `goal_completion` drops (`test_goal_completion_blocks_on_full_queue`)
- [x] TUI warns when `inbound_dropped > 0` (log warning in `_log_turn_event_stats`)

---

## Phase 2 — Fairness & capacity (A)

| Task | Status | Files |
|------|--------|-------|
| 2.1 Per-worker `ResponsePusher` semaphore (100 slots) | **Done** ✅ | `response_bridge.py` — `_pending_slots_for(worker_id)` |
| 2.2 Per-loop in-flight budget | **Done** ✅ | `loop_broadcast_budget.py`, `_broadcast_loop_message` |
| 2.3 Async card ingest off hot path | **Done** ✅ | `loop_card_manager.py` — per-loop queue (500) + worker |
| 2.4 Thread pool sizing docs + startup log | **Done** ✅ | `daemon.template.yml` comments, `thread_runner.py` warning at low max_pool_size |
| 2.5 IG-535 defaults for 32 concurrent loops | **Done** ✅ | All queue sizes, pool sizes, semaphore slots |

**Exit criteria**

- [x] N=32 load test: each loop receives ≥75% events (`test_multi_loop_fairness_under_pressure`)
- [x] N=64 load test: p95 cross-loop start delay ≤ 2× baseline (`test_multi_loop_n64_start_delay_gate`)

---

## Phase 3 — Latency (C)

| Task | Status | Files |
|------|--------|-------|
| 3.1 TUI `streaming_interval_ms` → 100 | **Done** ✅ | Default in `soothe/config/models.py` OutputStreamingConfig |
| 3.2 Per-client `stream_delivery` | **Done** ✅ | `ClientSession.stream_delivery`; query uses `client_id` |
| 3.3 Synthesis HIGH in `EventMeta` at broadcast | **Done** ✅ | `_resolve_publish_priority()` promotes goal_completion to HIGH |
| 3.4 TUI render batching profile | **Done** ✅ | `TurnApplyBatcher` in `turn/pipeline.py` (default on) |
| 3.5 CoreAgent warmup at pool start | **Done** ✅ | `_worker_runner.warmup_worker_runner_on_loop`, `thread_pool.warmup_core_agent` |

**Exit criteria**

- [x] p50 time-to-first-chunk ↓ 20% vs Phase 2 baseline (`test_phase3_first_chunk_p50_under_load`, coalesce gate in `test_stream_delivery.py`)
- [x] p95 synthesis visible within 5s of daemon goal complete log (`test_phase3_synthesis_visible_p95_under_5s`)

---

## Performance Optimization Summary

| Change | Impact |
|--------|--------|
| Added `pytest-xdist` for sdk/cli | Parallel test execution (4 workers) |
| Optimized slow test sleeps | Reduced 1.1s/3.5s sleeps to 0.02s/2s |
| Per-worker semaphore | Isolates backpressure across workers |
| Per-loop query exclusivity + atomic task registration | Prevents duplicate concurrent queries per loop; fixes `_query_state_lock` race |
| Per-loop broadcast budget (80 slots) | Blocks only that loop's stream consumer toward EventBus |
| EventBus concurrent subscriber delivery | `asyncio.gather` per subscriber queue |
| ThreadStateRegistry `ensure()` lock | Double-checked locking under `threading.Lock` |
| CoreAgent pool warmup (`warmup_core_agent`) | Moves ~5–10s LazyCoreAgent compile to daemon `warming` phase |

**Configuration defaults (IG-535, Jul 2026)**:
- `max_in_flight_broadcasts_per_loop`: 80 (per-loop EventBus backpressure)
- `thread_pool.min_pool_size`: 8 (pre-warm baseline)
- `thread_pool.max_pool_size`: 32 (full parallelism)
- `thread_pool.warmup_core_agent`: true (compile CoreAgent during worker warmup)
- `thread_pool.thread_startup_timeout_seconds`: 60 (wait for baseline warmup)
- `response_bridge._DEFAULT_SLOTS_PER_WORKER`: 100 (dense streaming)
- `thread_runner.response_queue maxsize`: 200 (chunk backlog)
- `pipeline.inbound_maxsize`: 2048, `outbound_maxsize`: 1024 (TUI throughput)
- `websocket._inbound_maxsize`: 20_000 (client buffer)

**Verification timing (Jul 2026)**:
- soothe-sdk: ~3s (xdist)
- soothe-cli: ~4s (xdist)
- soothe: ~22s (async fixtures)
- soothe-daemon: ~14s (async fixtures)

---

## Testing

```bash
./scripts/verify_finally.sh

# Integration tests require --run-integration
pytest --run-integration packages/soothe-daemon/tests/integration/daemon/test_multi_loop_performance.py
```

Unit: `test_bus.py` (goal_completion), `test_response_push_bridge.py`, `test_thread_runner_stale_busy.py`
Integration: `test_multi_loop_performance.py` (Phase 0–1 gates, N=32 baseline per IG-535)

---

## Related

- [IG-533](IG-533-goal-completion-tui-worker-lifecycle-fixes.md) — stream lifecycle (partial overlap)
- [IG-477](IG-477-response-bridge-backpressure.md) — bridge backpressure history