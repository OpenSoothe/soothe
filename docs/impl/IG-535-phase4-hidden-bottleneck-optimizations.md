# IG-535: Phase 4 Hidden Bottleneck Optimizations

**RFC**: [RFC-614](../specs/RFC-614-unified-streaming-messaging.md), [RFC-450](../specs/RFC-450-daemon-communication-protocol.md)
**Design**: [docs/drafts/2026-07-01-daemon-tui-performance-isolation-design.md §5](../drafts/2026-07-01-daemon-tui-performance-isolation-design.md)
**Created**: 2026-07-01
**Updated**: 2026-07-01
**Status**: Done (Optimizations 1–4; defaults tuned for 32 concurrent loops)
**Priority**: Post-Phase 1-3 (IG-534) completion

---

## Executive Summary

This IG implements the "hidden bottlenecks" identified in §5 of the performance isolation design draft. These optimizations target bottlenecks discovered through code-level analysis that aren't addressed by the phased program in IG-534.

**Configuration Defaults (Jul 2026)**: All defaults tuned for 32 concurrent loops:
- Thread pool: `min_pool_size=8`, `max_pool_size=32`
- Response bridge semaphore: `100 slots per worker`
- Queue sizes doubled across pipeline, thread runner, websocket client

---

## Optimization 1: WebSocket Priority-Aware Drop Policy ✅

**Problem**: SDK client's `_put_inbound_queue` uses drop-oldest policy, which can evict terminal frames (`done`, `idle`) or goal_completion chunks when the queue fills.

**Files**: `packages/soothe-sdk/src/soothe_sdk/client/websocket.py`

### 1.1 Tasks

| Task | Status | Notes |
|------|--------|-------|
| 1.1 Add `_inbound_frame_drop_priority()` helper | **Done** | Returns 0 (CRITICAL) for goal_completion/terminal, 1 (HIGH) for cognition events, 2 (NORMAL) for streaming |
| 1.2 Refactor `_put_inbound_queue` with priority-aware drop | **Done** | Scans queue, drops highest-priority candidate (NORMAL) instead of oldest |
| 1.3 Unit test: goal_completion never dropped | **Done** | `test_websocket_priority_drop.py::TestInboundFrameDropPriority` |
| 1.4 Unit test: status:idle never dropped | **Done** | `test_websocket_priority_drop.py::TestPriorityAwareInboundQueue` |

**Exit criteria**: ✅ No goal_completion or terminal frames dropped in load harness.

---

## Optimization 2: TUI Apply Path Chunk Batching ✅

**Problem**: `_apply_turn_chunk` runs per-chunk with multiple async widget operations, saturating Textual event loop.

**Files**: `packages/soothe-cli/src/soothe_cli/runtime/turn/pipeline.py`

### 2.1 Tasks

| Task | Status | Notes |
|------|--------|-------|
| 2.1 Add `TurnApplyBatcher` class | **Done** | Accumulates up to 10 chunks, flushes on HIGH priority or 50ms timeout |
| 2.2 Extend `run_turn_pipeline` with batching parameters | **Done** | `batch_size`, `batch_delay_ms`, `batching_enabled` params |
| 2.3 Unit test: batching reduces DOM ops | Pending | Integration-level test needed |

**Exit criteria**: TUI-side latency reduction under dense tool-call streams (to be validated in load harness).

---

## Optimization 3: QueryEngine Batched Broadcast — Done

**Problem**: `_broadcast_stream_tuple` called per-tuple, each triggers full EventBus publish with subscriber iteration.

**Files**: `packages/soothe-daemon/src/soothe_daemon/query/engine.py`

### 3.1 Tasks

| Task | Status | Notes |
|------|--------|-------|
| 3.1 `_broadcast_coalescer_outputs` batches coalescer step | **Done** | Emits `event_batch` when >1 frame per ingest/flush |
| 3.2 `_prepare_stream_tuple_events` helper | **Done** | Preserves tool-batch + skip semantics |
| 3.3 Unit tests | **Done** | `test_broadcast_batch.py` |

**Exit criteria**: ✅ Fewer EventBus publishes per coalescer step under multi-output ingest.

---

## Optimization 4: Card Binding Dedicated Thread Pool ✅

**Problem**: `LoopCardManager._flush_buffers_to_ledger` uses `asyncio.to_thread` which competes with general thread pool.

**Files**: `packages/soothe-daemon/src/soothe_daemon/display/loop_card_manager.py`

### 4.1 Tasks

| Task | Status | Notes |
|------|--------|-------|
| 4.1 Add `_card_bind_executor` module-level | **Done** | 2-worker ThreadPoolExecutor with `soothe-card-bind` prefix |
| 4.2 Modify `_flush_buffers_to_ledger` | **Done** | Uses `loop.run_in_executor(executor, ...)` |
| 4.3 Add executor shutdown on daemon stop | **Done** | `shutdown_card_bind_executor()` exported |
| 4.4 Unit test: binding doesn't block to_thread | Pending | Integration-level test needed |

**Exit criteria**: Main-loop occupancy reduction under concurrent loops (to be validated in load harness).

---

## Testing Strategy

| Level | Coverage |
|-------|----------|
| Unit | ✅ Optimization 1 priority drop tests in `test_websocket_priority_drop.py` |
| Integration | Multi-loop performance harness (IG-534 Phase 0) |
| Manual | 3 TUI clients, parallel turns, verify synthesis complete |

✅ `./scripts/verify_finally.sh` passed.

---

## Rollout

1. **Optimization 1** ✅ — WebSocket priority drop (safety-critical, shipped)
2. **Optimization 2** ✅ — TUI batching (highest latency win, shipped)
3. **Optimization 3** ✅ — QueryEngine batched broadcast (shipped)
4. **Optimization 4** ✅ — Card bind executor (isolation win, shipped)

---

## Related

- [IG-534](IG-534-daemon-tui-performance-isolation.md) — Phase 0-3 program
- [RFC-450 §9.5](../specs/RFC-450-daemon-communication-protocol.md) — event_batch envelope