# IG-533: Goal-Completion TUI Transfer & Worker Lifecycle Fixes

**RFC**: [RFC-614](../specs/RFC-614-unified-streaming-messaging.md) (messages + `phase`), [RFC-450](../specs/RFC-450-ws-protocol-v1.md) (stream terminate / idle ordering)
**Created**: 2026-07-01
**Status**: Implemented (2026-07-01)
**Superseded (stream termination)**: [IG-556](IG-556-stream-termination-unification.md) — P0–P2 removes post-idle 30s drain and turn-end flush workarounds
**Related**: [IG-509](IG-509-loop-7cba-hang-analysis.md), [IG-507](IG-507-loop-3328-log-analysis-fixes.md), [IG-527](IG-527-go-client-appkit.md)
**Incident loops**: `b84e` (`019f1966-edbb-7ab3-9541-dd665bf7b84e`), `0b0e` (`019f1969-7e78-7143-8351-7bb9a4df0b0e`), `37e2` (`019f196a-dfb7-77f3-ad2a-9b878e9d37e2`)
**Logs**: `~/.soothe/logs/soothe.log`, `deploy/logs/soothe.log` (docker), loop `runner.log` under `~/.soothe/data/loops/`

---

## Executive Summary

Two user-visible failures share one underlying gap: **the daemon often completes goal synthesis, but the client loses the tail of the stream**.

| Symptom | User sees | Daemon logs |
|---------|-----------|-------------|
| `RuntimeError: Worker thread exited unexpectedly during query execution` | Turn abort + error bubble | May show `thread ended (busy=True)` or no graceful `error` emit |
| Goal-completion report “incomplete” in TUI | Steps stuck running / partial synthesis card / 3-line preview only | `Synthesis stream: chunks=N chars=M`, `Goal completed: action=synthesize` |

Forensics on loops `b84e`, `0b0e`, `37e2` (2026-07-01): all three **completed synthesis on the daemon** (1579–5356 chars). TUI incompleteness is a **client delivery / lifecycle** problem, not failed StrangeLoop logic.

This IG bundles the fixes into four phases: **P0 client stream integrity**, **P0 worker reliability**, **P1 backpressure & UX**, **P2 gateway (mizar-airway)**.

---

## Problem Summary

### Symptom A — `Worker thread exited unexpectedly`

Generic `RuntimeError` from `thread_runner._route_failure_for_dead_busy_worker()` when a **thread-pool worker dies mid-query without emitting `("error", exc)`**:

```
packages/soothe-daemon/src/soothe_daemon/runner/thread_runner.py:663-666
```

Distinct from:
- Normal in-worker exceptions → re-raised to client as original message
- `Worker subprocess exited…` → `pool_runner.py` (OS process pool)
- Worker idle timeout / respawn → `busy=False`, no client error

Contributing factors (from IG-509, loop `0b0e` investigation):
- `request_timeout_seconds=0` → hung tools hold worker indefinitely
- Unbounded grep walk (resolved: ag/rg-only grep per IG-509 Resolution)
- Daemon restart / `/clear` while worker busy
- Dependency mismatch (`langchain_core.tracers.context` missing on some workers)

### Symptom B — Goal-completion not fully shown in TUI

| Mechanism | Location | Effect |
|-----------|----------|--------|
| Turn ends before synthesis arrives | `textual_adapter.py` stream-end safety net | Steps marked “Stream ended before steps completed” |
| `/clear` switches `loop_id` without cancel | `_execution.py` + `session.py` filter | Old loop `goal_completion` events skipped |
| Post-idle drain too short (2.5s) | `session.py` `_POST_IDLE_DRAIN_DEADLINE_S` | Tail frames after `status: idle` dropped |
| Chunk backpressure drop | `response_bridge.py` | Silent loss of synthesis chunks (100-queue, 0.5s timeout) |
| Dedupe suppresses report card | `textual_adapter.py` `_tui_goal_completion_matches_prior_main_visible_answer` | Full report hidden; 3-line step preview only |
| No resume fallback on truncate | TUI turn cleanup | Persisted ledger not fetched when stream aborts |

---

## Architecture (failure mode)

```
TUI                    Daemon main              Worker thread
 │  loop_input  ──────►  submit request  ──────►  StrangeLoop + synthesis
 │                      ResponsePusher ◄──────  chunk × N (goal_completion)
 │  iter_turn_chunks ◄── broadcast
 │
 ├─ /clear → new loop_id ──► filters old loop_id events (DROP)
 ├─ idle + 2.5s drain ──► may miss slow tail
 └─ worker death ──► RuntimeError + finalize_pending_* (incomplete UI)

Daemon may still log: Goal completed: action=synthesize, chars=5182
```

---

## Implementation Plan

### Phase 1 — P0: Client stream integrity (goal_completion must reach TUI)

#### 1.1 Cancel in-flight query on `/clear` before loop switch

**Problem**: `/clear` calls `new_loop()` and updates `session._loop_id` immediately. In-flight synthesis on the **old** loop is filtered out.

**Files**:
| File | Change |
|------|--------|
| `packages/soothe-cli/src/soothe_cli/tui/app/_execution.py` | Before `new_loop()`: if `_agent_running`, await `daemon_session.cancel_turn()` (or `/cancel` notify); wait for idle or timeout (e.g. 5s) |
| `packages/soothe-cli/src/soothe_cli/runtime/transport/session.py` | Expose `cancel_active_turn()` if not already; document ordering contract |
| `packages/soothe-daemon/src/soothe_daemon/server/commands.py` | Ensure `reinitialize_for_clear` cancels worker for prior loop via `loop_runner.cancel()` |
| `packages/soothe-daemon/src/soothe_daemon/query/engine.py` | Verify `cancel_loop` tears down thread-pool runner for old `loop_id` |

**Acceptance**:
- `/clear` during synthesis → no TUI crash; old loop cancelled in daemon log
- No `Skipping daemon event for non-active loop` for events user still expects

#### 1.2 Extend post-idle stream drain

**Problem**: `_POST_IDLE_DRAIN_DEADLINE_S = 2.5` is far below synthesis duration (19–53s observed).

**Files**:
| File | Change |
|------|--------|
| `packages/soothe-cli/src/soothe_cli/runtime/transport/session.py` | Raise default to **30s** (or `max(2.5, streaming_interval × 50)`); make configurable via daemon session ctor |
| `packages/soothe-daemon/src/soothe_daemon/server/session.py` | Confirm `await_loop_delivery_drained()` completes before `status: idle` (IG-436 HIGH-priority settle margin) |
| `packages/soothe-daemon/src/soothe_daemon/query/engine.py` | Audit all `status: idle` emit paths; none before drain + `complete` subscription message |

**Acceptance**:
- Integration test: synthesis chunks emitted **after** last execute event but **before** idle all received by `iter_turn_chunks`
- No regression on fast quiz/direct_model turns (drain returns quickly when queue empty)

#### 1.3 Finalize or recover goal_completion on turn abort

**Problem**: Worker death / connection loss leaves open `goal_completion_stream_by_namespace` entries and running step cards.

**Files**:
| File | Change |
|------|--------|
| `packages/soothe-cli/src/soothe_cli/tui/textual_adapter.py` | In `except` / interrupt paths: call existing end-of-stream flush (`goal_completion_stream_by_namespace` finalize block ~3462) before safety-net error finalize |
| `packages/soothe-cli/src/soothe_cli/tui/app/_execution.py` | After error: optional **ledger fetch** — `fetch_conversation_log` / checkpoint API for last `phase=goal_completion` row; mount as `AssistantMessage` if stream empty |
| `packages/soothe-cli/src/soothe_cli/runtime/transport/session.py` | Add `fetch_goal_completion_text(loop_id) -> str | None` helper wrapping persisted conversation row |

**Acceptance**:
- Simulated mid-synthesis disconnect → TUI shows full report from ledger OR explicit “partial — resume loop” message, not silent incompleteness

#### 1.4 Friendly error copy for thread worker loss

**Files**:
| File | Change |
|------|--------|
| `packages/soothe-cli/src/soothe_cli/cli/execution/daemon_errors.py` | Add `DAEMON_WORKER_THREAD_LOST` matcher for `Worker thread exited unexpectedly`; map to actionable copy (retry / resume loop) like subprocess variant |
| `packages/soothe-cli/tests/unit/ux/tui/test_execution_error_copy.py` | Cover thread variant |

---

### Phase 2 — P0: Worker reliability (prevent silent thread death & hangs)

#### 2.1 Log root cause on busy worker death

**Files**:
| File | Change |
|------|--------|
| `packages/soothe-daemon/src/soothe_daemon/runner/thread_runner.py` | In `_handle_dead_worker`: log last known `loop_id`, `request_id`, stack if available; attach `exc_info` from worker exit hook if added |
| `packages/soothe-daemon/src/soothe_daemon/runner/thread_runner.py` | In `_thread_worker_body` `finally`: set thread-local `last_error` before thread exit |

**Acceptance**:
- Force-kill worker in test → daemon log contains actionable cause, not only watchdog line

#### 2.2 Enable request-level timeout (config default)

**Problem**: IG-509 — `request_timeout_seconds=0` allows infinite hangs.

**Files**:
| File | Change |
|------|--------|
| `config/daemon.template.yml` / config schema | Default `thread_pool.request_timeout_seconds` and `worker_pool.request_timeout_seconds` to **1209600** (14 days); use `0` only for no cap |
| `packages/soothe-daemon/src/soothe_daemon/runner/thread_runner.py` | Ensure timeout emits `("timeout", RuntimeError(...))` not silent hang |
| Docs | Document interaction with `ToolTimeoutMiddleware` (IG-511) |

**Acceptance**:
- Hung grep (mock) → worker emits timeout within configured bound; client sees error, worker marked idle

#### 2.3 Grep ag/rg-only (implemented)

**Files**: `packages/soothe/src/soothe/foundation/core/filesystem/grep_search.py`, `local.py`

**Status**: Builtin grep uses `ag`/`rg` subprocesses only; no Python directory walk. See IG-509 Resolution.

#### 2.4 Fix `langchain_core.tracers.context` dependency drift

**Problem**: Logged `ModuleNotFoundError` on intake classification (loop `6eee`).

**Files**:
| File | Change |
|------|--------|
| `packages/soothe/pyproject.toml` / lockfile | Pin compatible `langchain-core` version; add tracers extra if split package |
| Deploy image | Single Python version (3.11 **or** 3.12) for daemon + workers — logs showed mixed 3.11/3.12 venv paths |

---

### Phase 3 — P1: Backpressure & synthesis delivery

#### 3.1 Stop silently dropping goal_completion chunks

**Problem**: `ResponsePusher` drops chunks when asyncio queue full after 0.5s.

**Files**:
| File | Change |
|------|--------|
| `packages/soothe-daemon/src/soothe_daemon/runner/response_bridge.py` | For terminal-bound phases (`goal_completion`, `direct_model`): **block** with longer timeout or coalesce consecutive text chunks before enqueue |
| `packages/soothe-daemon/src/soothe_daemon/runner/thread_runner.py` | Consider raising `response_queue` maxsize (100 → 500) OR count-based coalescing in pusher |
| `packages/soothe-daemon/tests/unit/runner/test_response_bridge.py` | Assert `goal_completion` chunks not dropped under slow consumer |

**Acceptance**:
- Load test: 500 synthesis chunks, slow consumer → zero `dropping chunk` warnings; payload byte-identical

#### 3.2 Coalesce synthesis chunks at sender (optional optimization)

**Files**:
| File | Change |
|------|--------|
| `packages/soothe-daemon/src/soothe_daemon/query/engine.py` or stream coalescer | Merge adjacent `phase=goal_completion` AIMessageChunks before broadcast when `stream_delivery=batched` |

Reduces queue pressure without changing TUI rendering semantics.

#### 3.3 Fairness under parallel loops

**Problem**: Three long loops (`b84e`, `0b0e`, `37e2`) ran concurrently on one daemon.

**Files**:
| File | Change |
|------|--------|
| Daemon config | Document `max_concurrent_threads` / pool size vs expected parallelism |
| `thread_runner.py` | Metrics: queue depth, drop count, per-loop chunk rate (debug) |

---

### Phase 4 — P1: TUI rendering & dedupe

#### 4.1 Narrow goal_completion dedupe

**Problem**: `_tui_goal_completion_matches_prior_main_visible_answer` may suppress standalone report when execute prose partially matches.

**Files**:
| File | Change |
|------|--------|
| `packages/soothe-cli/src/soothe_cli/tui/textual_adapter.py` | Dedupe only for `ledger_direct` replay or exact normalized match **above min length** (e.g. 200 chars); never dedupe when synthesis > step preview |
| `packages/soothe-cli/tests/unit/ux/tui/test_textual_adapter_goal_completion_dedupe.py` | Add case: long synthesis vs short step prose → report still mounted |

#### 4.2 Full report affordance on step card

**Files**:
| File | Change |
|------|--------|
| `packages/soothe-cli/src/soothe_cli/tui/widgets/messages/cognition_step.py` | When `set_result_preview` used but full `goal_completion` card exists, link/expand; or increase preview when no standalone card mounted |

#### 4.3 Stream-end message clarity

**Files**:
| File | Change |
|------|--------|
| `packages/soothe-cli/src/soothe_cli/tui/textual_adapter.py` | Distinguish “cancelled” vs “worker lost” vs “connection lost” in `_stream_end_pending_error_message` |

---

### Phase 5 — P2: mizar-airway gateway (IG-527 consumer)

**Scope**: `/Users/chenxm/Workspace/mizaralpha/mizar-airway` — not soothe-cli TUI.

| # | Change | File |
|---|--------|------|
| 5.1 | Raise `QueryTimeout` above long StrangeLoop + synthesis (90s → 30m or configurable) | `internal/agent/soothe_agent.go` |
| 5.2 | Stream `goal_completion` deltas to SSE until deliverable complete | `internal/agent/soothe_agent.go` `publishEvent` |
| 5.3 | Verify `DefaultDeliverablePhases()` includes `goal_completion` | `soothe-client-go/intent_hints.go` (already true) |
| 5.4 | On timeout, surface “partial — poll history” not empty complete | gateway `api.EventChatError` + optional history endpoint |

**Tracking**: Add `mizar-airway/docs/impl/IG-006-soothe-gateway-long-turn-timeouts.md` (short pointer to this IG §Phase 5) when implementing.

---

## File Map (all packages)

```
packages/soothe-daemon/src/soothe_daemon/
├── runner/
│   ├── thread_runner.py          # P0 worker death logging, queue sizing
│   ├── response_bridge.py        # P1 no silent drop for goal_completion
│   └── pool_runner.py            # parity for subprocess pool errors
├── query/engine.py               # P0 idle ordering, drain before idle
└── server/
    ├── session.py                # P0 await_loop_delivery_drained audit
    └── commands.py               # P0 clear → cancel old loop

packages/soothe-cli/src/soothe_cli/
├── runtime/transport/session.py  # P0 drain deadline, cancel API, ledger fetch
├── tui/
│   ├── textual_adapter.py        # P0 finalize on abort, P1 dedupe
│   ├── app/_execution.py         # P0 /clear cancel ordering
│   └── widgets/messages/cognition_step.py  # P1 preview UX
└── cli/execution/daemon_errors.py  # P0 friendly thread worker copy

packages/soothe/src/soothe/foundation/core/filesystem/
└── grep_search.py, local.py    # ag/rg-only grep (IG-509 Resolution)

mizar-airway/internal/agent/
└── soothe_agent.go               # P2 gateway timeout + SSE streaming
```

---

## Tests

| Area | Test file (new or extend) |
|------|---------------------------|
| `/clear` cancels old loop | `tests/unit/tui/test_clear_cancels_active_turn.py` |
| Post-idle drain receives synthesis | `tests/unit/ux/tui/test_daemon_session_normalize.py` (extend drain-after-idle) |
| Ledger fallback on abort | `tests/unit/ux/tui/test_goal_completion_ledger_recovery.py` |
| Thread worker error copy | `tests/unit/ux/tui/test_execution_error_copy.py` |
| ResponsePusher no drop | `tests/unit/runner/test_response_bridge.py` |
| Dedupe narrow | `tests/unit/ux/tui/test_textual_adapter_goal_completion_dedupe.py` |
| Gateway timeout | `mizar-airway/internal/agent/soothe_agent_test.go` |

---

## Verification Checklist

Run after each phase; full pass required before release.

1. **Happy path**: Single TUI turn → full synthesis card; char count ≈ daemon log `Synthesis stream: chars=N`.
2. **`/clear` during synthesis**: No crash; old loop cancelled; new loop clean.
3. **Parallel loops**: 3 concurrent long turns → no `dropping chunk`, no `Worker thread exited`, no “Stream ended before steps completed” on success paths.
4. **Resume**: `/resume` loop after disconnect → full `goal_completion` visible from persisted log.
5. **Worker timeout**: Mock hung tool → timeout error within configured bound; worker respawns idle.
6. **Gateway**: mizar-airway chat through docker stack → SSE receives full report for 5+ min turn.
7. **Regression**: `./scripts/verify_finally.sh` green.

---

## Rollout Order

| Order | Phase | Risk | Notes |
|-------|-------|------|-------|
| 1 | 2.4 deps + grep ag/rg verify | Low | Stops worker crashes on classify |
| 2 | 1.1 `/clear` cancel | Medium | Fixes 0b0e crash class |
| 3 | 1.2 drain + idle ordering | Medium | Fixes truncated synthesis |
| 4 | 3.1 backpressure | Medium | Needs load test |
| 5 | 1.3 ledger recovery + 1.4 error copy | Low | UX polish |
| 6 | 4.x dedupe/preview | Low | Cosmetic |
| 7 | 5.x mizar-airway | Independent | Gateway only |

---

## Open Questions

1. Should post-idle drain be **unbounded until queue empty** with only a hard cap (120s) instead of fixed 2.5s?
2. Should `/clear` **block UI** until cancel ack (vs fire-and-forget with spinner)?
3. Coalesce at daemon vs increase queue — which is default for `stream_delivery=streaming`?
4. Thread pool vs process pool in docker — are we standardizing on one mode to simplify lifecycle?

---

## References

- [IG-509](IG-509-loop-7cba-hang-analysis.md) — worker hang, ag/rg-only grep, no request timeout
- [IG-507](IG-507-loop-3328-log-analysis-fixes.md) — “Stream ended unexpectedly” + step count mismatch
- [IG-527](IG-527-go-client-appkit.md) — mizar-airway appkit / deliverable phases
- RFC-614 § goal_completion on `mode=messages` + `phase`
- RFC-450 §9.4 — `complete` before client considers stream ended
