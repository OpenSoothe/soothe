# IG-632: Cancel + Queued Goal Lifecycle Hardening

**RFC**: [RFC-450](../specs/RFC-450-daemon-communication-protocol.md), [RFC-631](../specs/RFC-631-goal-display-snapshots.md)  
**Created**: 2026-07-12  
**Status**: Implemented  
**Related**: [IG-549](IG-549-loop-worker-goal-boundary-hardening.md), [IG-533](IG-533-goal-completion-tui-worker-lifecycle-fixes.md)  
**Incident loop**: `d07c` (`019f5504-f781-7e20-9500-cbf6826cd07c`)

---

## Executive Summary

Ctrl+C on a running goal while another goal is queued caused two failures:

1. **TUI sync gap** — daemon executed the queued goal but the client showed no updates.
2. **Concurrent goals** — resubmitting spawned a second worker while the first orphan run continued.

Root cause: cancelled asyncio turns still emitted terminal frames and tore down the **successor** runner via loop-keyed `_active_runners`; queued `loop_input` was processed before cancel/worker teardown finished; thread pool allowed a second dispatch for the same `loop_id` on a different worker.

---

## Scope

### P0 — Daemon turn ownership

- Per-loop **turn generation** incremented on each admitted query.
- `_active_runners` stores `(runner, generation)`; `finally` only cancels runner and emits `idle` / `complete` when generation still matches.
- `cancel_loop` / cancel orchestrator do not pop successor runners from `_active_runners`.

### P0 — Serialize post-cancel intake

- `await_loop_ready_for_turn()` waits for cancel orchestrator completion and execution-pool worker idle.
- `run_query()` calls it before admission (invoked from loop worker handlers for user input).

### P0 — Per-loop worker dispatch

- `ThreadPool` / `WorkerPool` wait until no busy worker is mapped to the same `loop_id` before dispatch.

### P1 — TUI stale terminal guard

- `iter_turn_chunks` ignores `idle` until at least one stream payload chunk was seen for the current read session (after `running`).

---

## Files

| Area | File |
|------|------|
| Turn ownership + await | `packages/soothe-daemon/src/soothe_daemon/query/engine.py` |
| Loop worker → run_query | `packages/soothe-daemon/src/soothe_daemon/server/handlers.py` |
| Pool serialize | `packages/soothe-daemon/src/soothe_daemon/runner/thread_runner.py` |
| Pool serialize | `packages/soothe-daemon/src/soothe_daemon/runner/pool_runner.py` |
| TUI consumer | `packages/soothe-cli/src/soothe_cli/runtime/transport/session.py` |
| Tests | `packages/soothe-daemon/tests/unit/query/test_cancel_queued_goal.py` |
| Tests | `packages/soothe-cli/tests/unit/ux/tui/test_daemon_session_normalize.py` |

---

## Verification

```bash
./scripts/verify_finally.sh
```

Manual: multi-goal loop → queue goal B → Ctrl+C during goal A → B should stream in TUI without resubmit; resubmit must not double-run.
