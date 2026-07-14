# IG-546: Loop TUI Event Throughput

**RFC**: [RFC-614](../specs/RFC-614-unified-streaming-messaging.md), [RFC-503](../specs/RFC-503-loop-first-user-experience.md)  
**Created**: 2026-07-03  
**Status**: Complete  

## Follow-ups (outside IG-546 scope)

| Item | Priority | Status |
|------|----------|--------|
| Subprocess process-group kill on `run_command` timeout (orphan PIDs) | P1 | Done |
| Card ingest overflow depth metrics + daemon `stream_degraded` when overflow grows | P1 | Done |
| soothe-desktop `MessageList.tsx` coalesce / virtualization | P1 | Done |
| Full `./scripts/verify_finally.sh` green (import/collection fixes landed separately) | P0 | Verify |
**Related**: [IG-534](IG-534-daemon-tui-performance-isolation.md)

## Goal

Reduce WebSocket/card-binding load and TUI render pressure on tool-heavy loops without changing execution semantics. Provide zero-loss event propagation to TUI under backpressure.

## Scope

| Task | Priority | Status |
|------|----------|--------|
| Debounced card-ledger flush in `LoopCardManager` | P0 | Done |
| Raise `card_ingest_queue_maxsize` default | P0 | Done |
| Aggressive stream coalescing defaults (`tool_batch`, skip redundant wire) | P0 | Done |
| Explore step events → INTERNAL tier (hidden at normal verbosity) | P0 | Done |
| Skip explore step events in card ingest | P0 | Done |
| Execute-wave TUI coalesce interval (CLI) | P0 | Done |
| Card bind executor workers 2 → 4 | P1 | Done |
| **Zero-loss card ingest** (overflow deque, no drop-oldest) | P0 | Done |
| **Zero-loss TUI wire** (`event_batch` / batch blocking + client HIGH priority) | P0 | Done |
| Adaptive flush debounce when ingest queue > 80% | P0 | Done |
| Collapsed tool rows (`+N more tools` in step card) | P0 | Done |
| Explore iteration caps (medium 6, thorough 10) | P0 | Done |
| Planner subagent validation (invalid → explore) | P0 | Done |
| Explore step soft tool budget (40 tools) | P0 | Done |

## Zero-loss architecture

Two delivery paths feed the TUI:

1. **Live WebSocket stream** — `EventBus` → session → client inbound queue → TUI adapter  
   - `event_batch` and `tool_call_updates_batch` block at 80% queue fill (daemon)  
   - Client marks `event_batch` / top-level batch frames as HIGH priority (prefer keep over streaming text)

2. **Card ledger ingest** — parallel path for reattach/display DB  
   - Bounded `asyncio.Queue` + **overflow deque per loop** (no drop-oldest)  
   - Worker drains overflow before blocking on queue  
   - Adaptive debounce widens flush window when backlog > 80%

Memory growth on the overflow deque is the backpressure signal (preferable to silent frame loss).

## Verification

```bash
pytest packages/soothe-daemon/tests/unit/display/test_loop_card_manager.py -v
pytest packages/soothe-daemon/tests/unit/event/test_bus.py -v
pytest packages/soothe-sdk/tests/unit/test_websocket_priority_drop.py -v
pytest packages/soothe-cli/tests/unit/ux/tui/test_cognition_step_activity.py -v
pytest packages/soothe/tests/unit/core/loop/state/test_schemas.py -v
./scripts/verify_finally.sh
```
