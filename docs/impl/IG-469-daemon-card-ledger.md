# IG-469: Daemon-Owned Card Ledger + Replay (RFC-413 Phase 3)

**Guide**: IG-469
**Title**: Daemon-Resident `CardBinder` + Per-Loop `cards.jsonl` Ledger + `card.*` Replay Wire Frames
**Created**: 2026-06-04
**Related RFCs**: RFC-413 (Server-Owned Display Card Ledger)
**Scope**: Full RFC-413 Phase 3 in a single IG. Phase 4 (decommission legacy `reconstructor`/`enricher`, cut over live UX to `card.*`) is deferred to IG-471.

---

## Goal

Run the SDK's `CardBinder` inside the daemon as a parallel subscriber on the loop event bus, persist the bound cards as append-only JSONL at `~/.soothe/data/loops/<loop_id>/cards.jsonl`, and route both:

1. The TUI's resume flow (synchronous: `loop_cards_fetch` RPC), and
2. The reattach / `loop_subscribe` replay (streamed: new `card.replay_begin` / `card.created` / `card.replay_end` wire frames)

through that ledger. Live event delivery is **unchanged** in this IG — the new `card.*` frames carry historical replay only. This keeps live UX strictly stable; cutting live render over to `card.*` is Phase 4.

After this IG:
- Every event the daemon broadcasts on `loop:{loop_id}` is also fed to a `CardBinder`, which writes mutations to the loop's `cards.jsonl`.
- A new `loop_cards_fetch` RPC returns the current cards for a loop. If no ledger exists yet (pre-413 loop), the daemon **eagerly backfills** from checkpoint + activity log using the same `CardBinder`.
- The TUI's `_fetch_loop_history_data` prefers the ledger RPC; the existing checkpoint+activity-log merge stays as a fallback for one release.
- Reattach (`loop_subscribe` and `loop_reattach`) now streams `card.*` frames from the ledger instead of the sparse iteration events from `core.events.replay.reconstructor`. The SDK stops filtering those new frames as stale.
- Legacy `history_replay` / `loop_reattached` / `replay_complete` frames stay deprecated-but-emitted for the rollout window; non-TUI clients keep working. Phase 4 removes them.

## Why One IG, Not Two

Original plan split this into 3a (persistence + RPC) and 3b (wire frames + reattach). Per design decision: keep it as one IG to close the "live ≡ replay" invariant in a single PR. Risk is reduced by **not touching live render**: the new `card.*` frames are scoped to replay; the live event path is untouched. A future Phase 4 IG handles the live cut-over.

## Architecture

```
Daemon                                              TUI client
──────                                              ──────────
EventBus("loop:abc123") ─┬─► existing live sessions ─► live event consumer (unchanged)
                         │                          
                         └─► LoopBinderTask ──► CardBinder ──► LoopCardLedger
                                                                  │
                                                                  ▼
                                          ~/.soothe/data/loops/<loop_id>/cards.jsonl
                                                                  │
                       ┌──────────────────────────────────────────┘
                       ▼
                loop_cards_fetch (synchronous RPC)  ──► _fetch_loop_history_data (TUI startup + /loops switch)
                       │
                loop_subscribe / loop_reattach      ──► streams card.replay_begin → card.created* → card.replay_end
                                                            (new TUI consumer applies to MessageStore on reattach)
```

The binder task is a parallel subscriber on the existing `loop:{loop_id}` topic. It never blocks client delivery; its queue is bounded (size **256**) with drop-oldest semantics on overflow.

## New Modules

### `soothe_sdk/display/card_ledger.py` (new, SDK side — pure schema)

```python
@dataclass(frozen=True, slots=True)
class CardMutation:
    seq: int
    ts: str  # ISO-8601 UTC
    op: Literal["create", "update", "finalize", "header"]
    card_id: str
    kind: str  # MessageType value, or "header"
    data: dict[str, Any]  # full state for create/finalize; partial for update

class InMemoryCardLedger:
    """Latest-state-per-card-id projection of a mutation stream."""
    def apply(self, mutation: CardMutation) -> None: ...
    def snapshot(self) -> list[MessageData]: ...
    def to_mutations(self) -> list[CardMutation]: ...    # for backfill / streaming
    @classmethod
    def from_mutations(cls, mutations: Iterable[CardMutation]) -> "InMemoryCardLedger": ...
```

Pure logic — testable without files, callable from either the daemon (production writer) or future tooling.

### `soothe_daemon/display/` (new package)

- **`loop_card_ledger.py`** — file-backed wrapper around `InMemoryCardLedger`. Owns the per-loop `cards.jsonl` file, handles append + load + replay, manages monotonic `seq`. One instance per active loop. Per-loop asyncio lock around append.

- **`loop_binder_task.py`** — asyncio task that:
  1. Subscribes a bounded (size 256) `asyncio.Queue` to `EventBus` topic `loop:{loop_id}`.
  2. Pulls events, converts to the binder's input shape, calls SDK `CardBinder` functions.
  3. Diff-converts produced `MessageData` against current ledger state into `CardMutation`s.
  4. Awaits `ledger.append(...)`.
  5. Throttled warning on queue overflow (drop-oldest, one log per 5 s per loop).

- **`loop_card_manager.py`** — orchestrator:
  - Tracks `loop_id → (LoopCardLedger, LoopBinderTask)` map.
  - `ensure_for_loop(loop_id)` — opens / creates `cards.jsonl`, eagerly backfills if empty, starts the binder task. Idempotent.
  - `stop_for_loop(loop_id)` — unsubscribes, drains, closes.
  - `get_ledger(loop_id)` — for the synchronous RPC.
  - `replay_to_client(loop_id, send_fn, after_seq=None)` — streams `card.replay_begin` → `card.created` × N → `card.replay_end` to a client via the provided send function.
  - `backfill_ledger(loop_id)` — calls SDK binder over checkpoint + activity log to materialize the ledger when no `cards.jsonl` exists.

### Backfill reuse

Backfill is literally:

```python
checkpoint_messages = await runner.get_checkpoint_messages(loop_id)
activity_events = await runner.get_persisted_thread_messages(thread_id, include_events=True)
cognition_replay = card_binder.collect_cognition_card_replay(activity_events)
cards = card_binder.convert_messages_to_data(
    checkpoint_messages, cognition_card_replay=cognition_replay
)
# Convert MessageData list → CardMutation stream (op=create each), append all to cards.jsonl
```

## New Wire Frames

Added to the daemon → client protocol, used **only during replay** in this IG:

| Frame | Direction | Payload | Purpose |
|---|---|---|---|
| `card.replay_begin` | daemon → client | `{loop_id, total_cards, latest_seq}` | Signals start of historical card stream |
| `card.created` | daemon → client | `{loop_id, seq, card_id, kind, data}` | One bound card (full MessageData wire form) |
| `card.replay_end` | daemon → client | `{loop_id, latest_seq, card_count}` | End of historical stream; live frames follow on existing channels |

`card.updated` / `card.finalized` / real-time `card.created` are **reserved** in the schema but not emitted in this IG. The replay stream emits one `card.created` per current card (latest-state-per-card-id projection), not the full mutation history. That keeps the wire payload bounded at ~1 card per visible card on resume.

The SDK's `_STALE_TURN_PENDING_TYPES` is updated to **remove** `card.replay_begin`, `card.created`, `card.replay_end` (they become consumed). Legacy `history_replay`, `loop_reattached`, `replay_complete` remain in the filter for backward compat.

### Why only `card.created` for replay (not the diff stream)

In Phase 3 the wire still ships latest-state snapshots so the TUI can render with no understanding of mutation history. Real-time mutations (`card.updated`, `card.finalized`) are reserved for Phase 4 when live render cuts over to `card.*`. This keeps the TUI consumer simple in this IG: "for each `card.created` between `replay_begin` and `replay_end`, mount it into MessageStore."

## New RPC

`loop_cards_fetch` (request → `loop_cards_fetch_response`):

```jsonc
// request
{ "type": "loop_cards_fetch", "loop_id": "abc123", "request_id": "..." }

// response (success)
{
  "type": "loop_cards_fetch_response",
  "request_id": "...",
  "loop_id": "abc123",
  "cards": [<MessageData wire form>, ...],   // insertion order
  "context_tokens": 1247,                     // mirrors today's _context_tokens
  "seq": 1247,                                // latest seq in ledger
  "source": "ledger" | "backfill"             // diagnostic
}
```

Wire form for `MessageData` is `dataclasses.asdict(...)` — same shape the TUI already round-trips through `_convert_messages_to_data`'s output.

Handler in `soothe_daemon/protocol/router.py`:
1. Validate `loop_id`.
2. `ledger = await self._daemon._card_manager.ensure_for_loop(loop_id)` — starts binder task if not running; backfills synchronously if `cards.jsonl` doesn't exist yet.
3. Return `(ledger.snapshot(), context_tokens, latest_seq)`.

Backfill is **eager**: the RPC waits for backfill to complete before responding. Typical cost is ~1–3 s for 100-turn loops; logged at INFO. This matches today's `_fetch_loop_history_data` latency, so it's not a regression.

## Reattach Replay

`handle_loop_reattach` (in `soothe_daemon/event/reattachment.py`) is rewritten to:

```python
async def handle_loop_reattach(loop_id, daemon, client_id):
    await daemon._card_manager.ensure_for_loop(loop_id)
    await daemon._card_manager.replay_to_client(
        loop_id,
        send_fn=lambda frame: daemon._send_client_message(client_id, frame),
    )
```

The `replay_to_client` helper emits `card.replay_begin`, one `card.created` per card in the ledger, then `card.replay_end`. The legacy emission of `history_replay` + `loop_reattached` + `replay_complete` is **kept** in this IG (still emitted after `card.replay_end`) for non-TUI clients that haven't migrated. Phase 4 removes them.

`core.events.replay.reconstructor` and `enricher` are **kept but unused** in this IG — they're called only from the legacy path that we're now bypassing. Phase 4 deletes them.

## TUI Changes

### Synchronous resume path (`_fetch_loop_history_data`)

```python
async def _fetch_loop_history_data(self, loop_id):
    # 1. NEW: try ledger first.
    try:
        ledger = await self._daemon_session.fetch_loop_cards(loop_id)
        if ledger.success and ledger.cards:
            return _LoopHistoryPayload(
                [MessageData(**c) for c in ledger.cards],
                ledger.context_tokens or 0,
            )
    except Exception:
        logger.warning("loop_cards_fetch failed; falling back to legacy resume", exc_info=True)
    # 2. FALLBACK: existing checkpoint+activity-log merge path (unchanged).
    ...
```

If the RPC fails or returns empty, the existing path runs. **Strictly additive** — zero risk of regression.

### Reattach/subscribe replay consumer

The TUI's daemon-session consumer (in `_consume_daemon_events_background` / SDK `WebSocketClient`) gains handling for the three new frame types:

- `card.replay_begin` → enter "replay mode" for `loop_id`; clear queued cards; suspend the legacy `history_replay` consumer if it fires.
- `card.created` → reconstruct `MessageData`, accumulate.
- `card.replay_end` → bulk-load accumulated cards into `MessageStore`, mount visible widgets, exit replay mode.

When `card.replay_*` frames are received, the legacy `history_replay` / `loop_reattached` / `replay_complete` frames (which today are filtered out) are ignored even if filtering changes — the new consumer is authoritative.

## Daemon Lifecycle Wiring

Three integration points:

1. **`Daemon.__init__`** — instantiate `LoopCardManager`, hold as `self._card_manager`.
2. **`Daemon._broadcast`** — when a new `loop_id` first appears on any broadcast, call `self._card_manager.ensure_for_loop(loop_id)`. Idempotent; cheap fast path after first call.
3. **Loop teardown / GC** — when a loop is purged (existing `purge_loop_fully` flow), call `self._card_manager.stop_for_loop(loop_id)`. The per-loop data directory cleanup already covers `cards.jsonl`.

## Files Touched

### New

| File | Purpose |
|---|---|
| `packages/soothe-sdk/src/soothe_sdk/display/card_ledger.py` | `CardMutation`, `InMemoryCardLedger` |
| `packages/soothe-daemon/src/soothe_daemon/display/__init__.py` | package init |
| `packages/soothe-daemon/src/soothe_daemon/display/loop_card_ledger.py` | file-backed ledger |
| `packages/soothe-daemon/src/soothe_daemon/display/loop_binder_task.py` | event bus subscriber |
| `packages/soothe-daemon/src/soothe_daemon/display/loop_card_manager.py` | per-loop lifecycle + replay-to-client |
| `packages/soothe-sdk/tests/unit/display/test_card_ledger.py` | SDK ledger logic |
| `packages/soothe-daemon/tests/unit/display/__init__.py` | test pkg init |
| `packages/soothe-daemon/tests/unit/display/test_loop_card_ledger.py` | file I/O |
| `packages/soothe-daemon/tests/unit/display/test_loop_binder_task.py` | event consumption |
| `packages/soothe-daemon/tests/unit/display/test_loop_card_manager.py` | lifecycle + backfill |
| `packages/soothe-daemon/tests/unit/display/test_reattach_replay_emits_card_frames.py` | reattach emits new frames |
| `packages/soothe-cli/tests/unit/tui/test_card_replay_consumer.py` | TUI card.* consumer |

### Modified

| File | Change |
|---|---|
| `packages/soothe-sdk/src/soothe_sdk/display/__init__.py` | export `CardMutation`, `InMemoryCardLedger` |
| `packages/soothe-sdk/src/soothe_sdk/client/websocket.py` | remove `card.replay_*` from `_STALE_TURN_PENDING_TYPES`; keep `history_replay` et al. for one release |
| `packages/soothe-daemon/src/soothe_daemon/server/core.py` | `Daemon.__init__` instantiates `_card_manager`; `_broadcast` calls `ensure_for_loop` |
| `packages/soothe-daemon/src/soothe_daemon/protocol/router.py` | add `loop_cards_fetch` dispatch + `_handle_loop_cards_fetch` |
| `packages/soothe-daemon/src/soothe_daemon/event/reattachment.py` | rewrite `handle_loop_reattach` to stream `card.*` frames; still emit legacy frames for backward compat |
| `packages/soothe-cli/src/soothe_cli/runtime/transport/session.py` | add `fetch_loop_cards(loop_id)` RPC client |
| `packages/soothe-cli/src/soothe_cli/tui/app/_history.py` | `_fetch_loop_history_data` tries ledger first; `_consume_daemon_events_background` handles `card.replay_*` |

## Test Plan

### Unit tests

1. **SDK** `test_card_ledger.py`:
   - `InMemoryCardLedger.apply` updates state per `card_id`; `snapshot()` returns insertion-ordered MessageData.
   - `from_mutations` reconstructs identical state from a recorded stream (round-trip).
   - `to_mutations` after applying a sequence produces a stream that round-trips to the same snapshot.
2. **Daemon ledger** `test_loop_card_ledger.py`:
   - `append(mutation)` writes one JSONL line; `seq` is monotonic.
   - `load()` reconstructs the same state across simulated daemon restart.
   - Header record exists with `card_schema_version: 1`.
   - Concurrent append + snapshot are serialized correctly (per-loop lock).
3. **Binder task** `test_loop_binder_task.py`:
   - Feeding canned events (user input, step.started, tool_call, tool_result, step.completed, final AIMessage) produces a ledger snapshot identical to what `card_binder.convert_messages_to_data` returns over equivalent checkpoint messages.
   - Queue overflow throttle: feed 1000 events with a stalled consumer → one warning per 5 s.
4. **Manager + backfill** `test_loop_card_manager.py`:
   - `ensure_for_loop` on a pre-413 loop (with checkpoint + activity log) backfills the ledger; resulting snapshot matches `_fetch_loop_history_data`'s legacy output card-for-card.
   - Eager backfill is awaited before `ensure_for_loop` returns.
5. **Reattach replay** `test_reattach_replay_emits_card_frames.py`:
   - `handle_loop_reattach` emits exactly one `card.replay_begin`, N `card.created`, one `card.replay_end`.
   - Frame order is deterministic (insertion order from ledger).
   - Legacy `history_replay` + `loop_reattached` + `replay_complete` still emitted (for backward compat).
6. **TUI consumer** `test_card_replay_consumer.py`:
   - `card.replay_begin` / `card.created` × N / `card.replay_end` produces the same MessageStore state as a direct `bulk_load` of those cards.
   - When `card.replay_*` arrives, the legacy `history_replay` consumer is no-op.

### Integration / smoke

7. **`./scripts/verify_finally.sh`** green.
8. **Manual TUI smoke**:
   - Start a new loop, run 3+ turns with tool calls + cognition cards. Inspect `~/.soothe/data/loops/<loop_id>/cards.jsonl` — it has a header + one mutation per card.
   - Restart the TUI with `soothe loop continue <id>` → transcript renders identically to before (now via ledger RPC).
   - `/loops` switch to that loop → transcript renders identically (IG-467 path now backed by ledger).
   - Detach + reattach via `loop attach <id>` → transcript renders identically (new `card.*` replay path).
   - For a **pre-413** loop (one whose `cards.jsonl` doesn't exist before this change): first open triggers backfill, subsequent opens use the ledger.

## Risks

| Risk | Mitigation |
|---|---|
| **Binder hot path latency** | Binder runs in own asyncio task fed by bounded queue (256, drop-oldest non-critical). Never on `_broadcast`'s critical path. |
| **Disk write amplification** | One JSONL append per mutation. Estimated ~1 KB per mutation, ~1000 mutations per 100-turn loop = ~1 MB per loop. Within RFC's stated budget. |
| **Eager backfill cost on first read** | ~1–3 s for 100-turn loops; matches today's `_fetch_loop_history_data` latency. INFO log on entry/exit; if a loop is so large backfill exceeds 30 s, log a WARNING. |
| **Diverging from live render** | Resolved: live render is **unchanged**. Resume goes through the ledger; live still uses the existing event pipeline. The drift class is eliminated only on the resume axis; live ↔ resume parity is closed because both derive from the same `CardBinder` over the same events. |
| **MessageData wire-form drift** | RPC and `card.created` both serialize via `dataclasses.asdict`; client reconstructs via `MessageData(**dict)`. Identity not preserved across the wire, but structural equality is — verified by tests. |
| **Concurrent reads while ledger is being written** | Per-loop asyncio lock around `append` + in-memory state update. `snapshot()` reads under the same lock. Single-writer multi-reader. |
| **Frame ordering on reattach** | `replay_to_client` holds a snapshot reference and iterates synchronously before yielding to live events. Live `_broadcast` events queue up on the client's session queue behind the in-flight `card.replay_*` frames — natural ordering, no race. |
| **Pre-413 loop with no checkpoint** | If `runner.get_checkpoint_messages` returns empty, backfill falls back to activity-log-only conversion (existing `convert_loop_events_to_data` path in the SDK binder). Logged as "limited backfill" at INFO. |
| **SDK stale filter regression** | Tests assert `card.replay_*` are NOT in `_STALE_TURN_PENDING_TYPES` and ARE consumed by the TUI. Legacy entries remain unchanged. |

## Out of Scope (Phase 4 / IG-471)

- Real-time `card.created` / `card.updated` / `card.finalized` emission alongside live events.
- TUI cut-over to consume `card.*` for live rendering.
- Removing legacy `history_replay` / `loop_reattached` / `replay_complete` frames + their `_STALE_TURN_PENDING_TYPES` entries.
- Deleting `soothe.core.events.replay.reconstructor` and `enricher`.

## Done When

- `~/.soothe/data/loops/<loop_id>/cards.jsonl` exists and contains a header + mutations for every loop the daemon has executed since this change.
- `loop_cards_fetch` RPC returns a populated ledger for active loops; backfills eagerly for legacy loops on first call.
- TUI `_fetch_loop_history_data` uses the ledger primary path; the legacy path runs only when the RPC fails or returns empty.
- Reattach (`loop attach`) emits `card.replay_*` frames and the TUI renders the transcript from them.
- All existing tests pass; new tests added per §"Test Plan"; `verify_finally.sh` green.
- Manual smoke checks listed above pass.
- PR description documents the additive nature and the deferred Phase 4 cleanup.
