# IG-470: Decommission Legacy Resume Path (RFC-413 Phase 4)

**Guide**: IG-470
**Title**: Cut TUI Over to Ledger-Only; Delete RFC-411 Reconstructor
**Created**: 2026-06-04
**Related RFCs**: RFC-413 (Server-Owned Display Card Ledger), RFC-411 (superseded)
**Scope**: Mechanical cleanup — deletes legacy code paths now that Phase 3's ledger is the primary source. Strictly subtractive (+ one small additive: `context_tokens` in the RPC response so the TUI doesn't need a side-channel state read).

---

## Goal

After this IG:
* TUI's `_fetch_loop_history_data` has **one** code path: the daemon's `loop_cards_fetch` RPC. The legacy checkpoint+activity-log merge is gone.
* `~/.soothe/data/loops/<loop_id>/cards.jsonl` is the single resume source for TUI consumers.
* Daemon `handle_loop_reattach` no longer emits `history_replay` / `loop_reattached` / `replay_complete`. Only `card.*` frames remain.
* SDK `_STALE_TURN_PENDING_TYPES` loses the deprecated frame types.
* `soothe.core.events.replay.reconstructor` and `enricher` are deleted.
* RFC-411 is marked **Deprecated** (superseded by RFC-413).

No real-time `card.*` emission alongside live events is introduced — that's a separate future enhancement (live render still uses the existing pipeline, unchanged since Phase 2). The ledger remains lazily-derived per Phase 3.

## Scope

### Additive (minimal)
1. **Add `context_tokens` to `loop_cards_fetch_response`** so the TUI no longer needs a separate `loop_state_get` round-trip for the token count. Daemon reads the checkpoint's `_context_tokens` channel value during `ensure_for_loop`.

### Subtractive (the bulk of the work)
2. **TUI `_fetch_loop_history_data`** collapses to a single ledger path:
   - On ledger success → render.
   - On ledger failure → show "Could not load history: <error>" and return empty (matches today's terminal-error UX in the message-mount path).
3. **Delete TUI helpers no longer reachable**:
   - `_HistoryMixin._get_loop_state_values`
   - `_HistoryMixin._recover_missing_checkpoint_messages`
   - `_HistoryMixin._fetch_loop_activity_events`
   - `_HistoryMixin._convert_loop_events_to_data` (was the fallback's fallback)
   - `_HistoryMixin._merge_history_sources` / `_convert_combined_to_data` (only used by deleted paths)
   - `_HistoryMixin._collect_cognition_card_replay` (was the cognition replay piece of the legacy merge)
4. **Keep** the static binder delegates that downstream tests exercise directly (`_convert_messages_to_data`, `_convert_event_to_message_data`, `_merge_step_progress`, etc.). They remain thin wrappers around the SDK binder.
5. **Daemon `handle_loop_reattach`** stops emitting `history_replay` / `loop_reattached` / `replay_complete`. Only the `card.*` block remains.
6. **SDK `_STALE_TURN_PENDING_TYPES`** loses `history_replay`, `loop_reattached`, `replay_complete`. The `card.*` entries stay (still need silent peeling for TUI).
7. **Delete** `packages/soothe/src/soothe/core/events/replay/__init__.py`, `reconstructor.py`, `enricher.py`. Verify no remaining importers.
8. **RFC-411 status** flips from "Draft (superseded by RFC-413 once Implemented)" to "Deprecated. Superseded by RFC-413."

## Files Touched

### Modified
- `packages/soothe-sdk/src/soothe_sdk/client/websocket.py` — remove 3 legacy entries from `_STALE_TURN_PENDING_TYPES`.
- `packages/soothe-daemon/src/soothe_daemon/protocol/router.py` — `_handle_loop_cards_fetch` also reads `_context_tokens` from checkpoint state and includes it in the response.
- `packages/soothe-daemon/src/soothe_daemon/event/reattachment.py` — drop the three legacy frame emissions; keep `card.*` block + error handling.
- `packages/soothe-cli/src/soothe_cli/runtime/transport/session.py` — `fetch_loop_cards` returns `context_tokens` from the RPC.
- `packages/soothe-cli/src/soothe_cli/tui/app/_history.py` — collapse `_fetch_loop_history_data`; delete the 6 helper methods listed above; `_try_load_ledger_payload` uses RPC-supplied `context_tokens` directly.
- `docs/specs/RFC-411-event-stream-replay.md` — status banner: Deprecated.
- `docs/specs/rfc-index.md` — RFC-411 entry: status to Deprecated; RFC-413 entry: status to Implemented (matches reality after this IG).
- `docs/specs/rfc-history.md` — new entry for the IG-470 cleanup.

### Deleted
- `packages/soothe/src/soothe/core/events/replay/__init__.py`
- `packages/soothe/src/soothe/core/events/replay/reconstructor.py`
- `packages/soothe/src/soothe/core/events/replay/enricher.py`

## Test Plan

1. **No test regressions** — all 3,584 pre-Phase-4 tests must still pass. The fallback-path tests were not present (the fallback was a runtime-only safety net for older daemons; we now require the new daemon).
2. **TUI integration tests** — `test_resume_loop_history_ordering.py` (IG-467) and `test_convert_messages_to_data.py` continue to pass via the binder delegates.
3. **Daemon reattach** — `test_reattach_replay_emits_card_frames.py` updated: the assertion that `HISTORY_REPLAY_WIRE` / `LOOP_REATTACHED_WIRE` are present becomes an assertion that they are **absent**.
4. **Reconstructor deletion** — `grep -r reconstructor packages/` shows zero hits in source (only in docs/changelogs).
5. `./scripts/verify_finally.sh` green.

## Risks

| Risk | Mitigation |
|---|---|
| **Pre-Phase-3 daemon in production** | None expected for first-party clients (TUI ships with daemon). If a stale daemon is in play, the RPC fails → TUI shows error message rather than silently falling through. Acceptable for the cleanup IG; the fallback was never meant to be load-bearing. |
| **Hidden importer of `core.events.replay`** | `grep` audit before deletion; if any importer exists, delete the import along with the module. |
| **`context_tokens` reads failing during backfill** | Read in a try/except in the RPC handler; default to 0 on failure. TUI already tolerates `context_tokens=0` (renders without a token-budget badge). |
| **Non-TUI clients still relying on `history_replay`** | None known. The frame's payload was always empty after Phase 3 (`"events": []`). Removing it is safe. |

## Done When

- TUI's `_fetch_loop_history_data` is one short function — RPC, then render — with no legacy branches.
- The three legacy frame types are gone from daemon emission and SDK filter.
- `soothe/core/events/replay/` is deleted.
- RFC-411 reads "Deprecated. Superseded by RFC-413."
- All tests pass; lint + format clean.
