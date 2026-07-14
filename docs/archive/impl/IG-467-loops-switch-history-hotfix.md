# IG-467: `/loops` Switch History Hotfix

**Guide**: IG-467
**Title**: `/loops` Switch Loads Historical Transcript (RFC-413 Phase 1)
**Created**: 2026-06-04
**Related RFCs**: RFC-413 (Server-Owned Display Card Ledger), RFC-503 (Loop-First UX)
**Scope**: Single-file hotfix; ships independently of the rest of RFC-413.

---

## Goal

When a user switches loops from `/loops` inside the TUI, the historical transcript renders before live events begin — matching the behavior of `soothe loop continue <id>` on startup. Today the screen is wiped and only future events appear.

## Root Cause (recap)

`SootheApp._resume_loop_via_daemon` (in `packages/soothe-cli/src/soothe_cli/tui/app/_model.py`) clears the message store, calls `daemon_session.switch_loop`, and starts a background event consumer — but never invokes `_load_loop_history` for the new loop. The TUI's startup path (`_startup.py`) does call it.

## Change

Insert one `await self._load_loop_history(loop_id=loop_id)` between the `switch_loop` RPC success and `run_worker(_consume_daemon_events_background)`. Awaiting (rather than scheduling) guarantees the historical transcript paints before live frames start arriving on the new subscription.

The history-load failure path inside `_load_loop_history` already mounts an "Could not load history" message and logs the exception, so the surrounding try/except in `_resume_loop_via_daemon` does not need extra handling — a load failure surfaces a soft error but does not roll the loop switch back.

## Files Touched

- `packages/soothe-cli/src/soothe_cli/tui/app/_model.py` — add one `await` call.
- `packages/soothe-cli/tests/unit/tui/test_resume_loop_history_ordering.py` — new regression test (mock-based) asserting `_load_loop_history` is awaited after `switch_loop` and before the live event consumer starts.

## Test Plan

1. **Regression unit test** (added in this IG): mock `SootheApp` instance, drive `_resume_loop_via_daemon("new_loop")`, assert call order:
   - `daemon_session.switch_loop` awaited once with `"new_loop"`.
   - `_load_loop_history` awaited once with `loop_id="new_loop"`, *after* `switch_loop`.
   - `run_worker` invoked *after* `_load_loop_history`.
2. **Manual TUI verification**: open the TUI on an existing loop, switch via `/loops` to another loop with prior history, confirm transcript renders. Verify no regression for the empty-history case (new/empty loops).
3. `./scripts/verify_finally.sh` passes (formatting, lint, all unit tests).

## Out of Scope

- Subagent / step-binding fidelity improvements (RFC-413 Phase 3).
- Daemon-side `CardBinder` / `DisplayCardLedger` (RFC-413 Phases 2–3).
- Removing `_STALE_TURN_PENDING_TYPES` filtering (RFC-413 Phase 3).

## Risk

Minimal. The change reuses the same `_load_loop_history` flow already exercised on every startup-resume. `await`-ordering may add up to ~100–500 ms of perceived latency on `/loops` switch as history hydrates — acceptable trade-off vs. an empty transcript.

## Done When

- Code change merged.
- Regression test passing in CI.
- Manual verification noted in PR description.
