# IG-408: Loop-scoped daemon client plane

**Status:** In progress  
**Goal:** Model client communication around AgentLoop (`loop_id`): one loop, many CoreAgent threads internally. Remove thread CRUD/subscribe/resume from daemon wire and SDK. Route events and input processing by `loop:{loop_id}` with per-loop queues.

**Scope:** `soothe.daemon` (server, handlers, message router, client session, query engine, transports), `soothe_sdk.client`, CLI bootstrap, tests.

**Non-goals:** Changing durability/thread persistence inside the runner—only the client/daemon boundary.

---

## Motivation

- **User-facing scope is the AgentLoop**, not LangGraph checkpoint ids. Clients should subscribe and send input against a stable `loop_id`; the daemon binds that to the active CoreAgent `thread_id` internally.
- **Isolation:** Concurrent clients (or one client switching loops) must not share a single input FIFO. Per-loop queues serialize work for that loop without blocking others.
- **Wire cleanup:** Legacy `subscribe_thread` / `new_thread` / `input` + `thread_id` paths are replaced or superseded by loop-first messages (see RFC-503).

---

## Terminology

| Term | Meaning |
|------|--------|
| `loop_id` | AgentLoop identity on the wire; primary handle for subscribe, input, and many RPCs. |
| `thread_id` (CoreAgent) | LangGraph / durability checkpoint key and internal registry id. Resolved after bind; **not** required on client `command_request` when `loop_id` is present. |
| `loop:{loop_id}` | Event-bus topic string for loop-scoped fan-out (`loop_event_topic`). |

---

## Daemon model: loops vs threads (final)

This is the **authoritative mental model** for how the daemon reconciles the client plane (`loop_id`) with CoreAgent / LangGraph execution (`thread_id`).

### Loop = client and routing unit

- Each **AgentLoop** is identified by **`loop_id`**. Clients **subscribe**, **send input**, and **resume interrupts** using that id only.
- The daemon stores per-loop state under a **loop workspace directory** with **`metadata.json`** (and mirrors key fields in SQLite `agentloop_loops` for durability and self-healing—see `_ensure_loop_metadata` in `message_router.py`).
- **Outbound events** for subscribers are scoped by **`loop:{loop_id}`** (`loop_event_topic`), not by raw `thread_id`, so the UI does not need to track checkpoint id changes.

### Thread = internal execution / checkpoint key

- A loop may accumulate **multiple** CoreAgent **`thread_id`** values over time (e.g. internal thread switches, new checkpoint branches). The metadata fields capture this:
  - **`thread_ids`**: history/list of checkpoint ids associated with this loop.
  - **`current_thread_id`**: which checkpoint context the **runner should use next** for that loop.
- **`bind_execution_thread_for_loop(daemon, loop_id)`** loads `metadata.json`, ensures **`current_thread_id`** exists (allocating one via UUID7 if missing), updates metadata when it had to create an id, then:
  - registers the thread in **`_thread_registry`**,
  - sets the thread’s **workspace** and **loop mapping** (`set_thread_loop(thread_id, loop_id)`),
  - calls **`_runner.set_current_thread_id(thread_id)`** so the next turn uses the right checkpoint.
- RPCs such as **`command_request`** accept **`loop_id`** on the wire; if **`thread_id`** is omitted, the handler **binds** via the same helper so handlers always see a resolved execution context.

### Concurrency and isolation

- **`LoopInputDispatcher`** maintains **one asyncio queue + worker per `loop_id`**. All `loop_input` and (subscribed) **`command_request`** work for that loop is **serialized** on that queue—different loops do not share a FIFO.
- **Multiple WebSocket clients** subscribed to the **same** `loop_id` share that loop’s queue and event stream semantics (verbosity / subscription rules still apply per session).

### What clients should not assume

- Clients must **not** treat LangGraph **`thread_id`** as the primary handle for live control plane operations; it remains an **internal** checkpoint key and may change as the loop evolves.
- **Persistence listing** and admin APIs may still expose `thread_id` for inspection/export; that is separate from **loop-first** subscribe/input.

---

## Architecture (client → daemon → runner)

```
Client                          Daemon
──────                          ──────
bootstrap_loop_session          message_router: loop_new / loop_subscribe / loop_input
       │                                │
       └─ loop_id ───────────────────────┼─► session.subscriptions[loop_id]
                                           │
loop_input / command_request               ├─► LoopInputDispatcher.enqueue(loop_id, msg)
  (loop_id explicit or from subscription)   │         │
                                           │         └─► per-loop worker
                                           │                 │
                                           │                 ├─► bind_execution_thread_for_loop
                                           │                 │   (metadata.json → thread_id, registry, runner)
                                           │                 │
                                           │                 └─► _process_loop_input_message
                                           │                       → runner / query engine
```

---

## Daemon building blocks

| Piece | Module | Role |
|-------|--------|------|
| `loop_event_topic` | `soothe.daemon.loop_isolation` | Stable topic prefix for loop-scoped events. |
| `bind_execution_thread_for_loop` | `soothe.daemon.loop_isolation` | Load loop workspace metadata, ensure `thread_id`, sync `_thread_registry` + `_runner.set_current_thread_id`. |
| `LoopInputDispatcher` | `soothe.daemon.loop_isolation` | `asyncio.Queue` + worker task **per** `loop_id`; drains into `_process_loop_input_message`. |
| `SootheMessageRouter` | `soothe.daemon.message_router` | Parses `loop_*` RPCs; for `command_request`, requires an active loop subscription and **enqueues** onto the dispatcher for that loop. |
| `_process_loop_input_message` | `soothe.daemon` (handlers mixin) | Dispatches enqueued payloads (e.g. `loop_input`, nested `command_request`) after bind. |
| `_handle_command_request` | `soothe.daemon._rpc_handlers` | Accepts `loop_id` (preferred); if `thread_id` omitted, uses `bind_execution_thread_for_loop` before handler dispatch. |

Loop workspace layout and `metadata.json` (`current_thread_id`, `thread_ids`, …) are created/updated through the message router’s loop lifecycle handlers; `bind_execution_thread_for_loop` reads the same files under the daemon workspace.

---

## Wire protocol (loop-first)

Canonical reference: **RFC-503** (Loop-First UX). Typical client flow:

1. **`daemon_ready`** → wait for ready.
2. **`loop_new`** → **`loop_new_response`** with `loop_id` *(or skip if resuming)*.
3. **`loop_subscribe`** `{ loop_id, verbosity }` → **`loop_subscribe_response`**.
4. **`loop_input`** `{ loop_id, content, … }` for user turns (SDK `WebSocketClient.send_input` uses this shape).
5. **`command_request`** may carry **`loop_id`**; if the client has already subscribed, the router can associate the client’s active loop and enqueue the request on that loop’s queue.

**`resume_interrupts`** uses **`loop_id`** + `resume_payload` and checks subscription state before satisfying a pending interrupt future.

Legacy thread-oriented messages may still exist for admin/tooling paths; new client code should prefer the loop messages above.

---

## SDK and CLI

| Layer | Location | Notes |
|-------|----------|--------|
| Bootstrap | `soothe_sdk.client.session.bootstrap_loop_session` | `resume_loop_id` optional; always completes with `loop_subscribe`. |
| WebSocket API | `soothe_sdk.client.websocket.WebSocketClient` | `send_loop_new`, `send_loop_subscribe`, `send_loop_input` / `send_input` → `loop_input`. |
| CLI / TUI | `packages/soothe-cli` | `TuiDaemonSession`, command router (`loop_id` on RPC), event processor `loop_id` on status, `resume_loop_id` on run paths. |
| Other clients | `client/go`, `client/typescript` | Mirror bootstrap + `loop_input`; keep checkpoint/thread APIs separate where they talk to persistence-only RPCs. |

Slash-command validation uses registry flag **`requires_loop`** (not `requires_thread`); see RFC-454.

---

## Testing

- **Daemon routing / enqueue:** `packages/soothe/tests/unit/daemon/test_message_router_loop_input.py` (and related daemon transport tests).
- **Loop workspace:** `packages/soothe/tests/unit/core/workspace/test_loop_workspace_resolution.py`.
- **SDK bootstrap:** `packages/soothe-sdk/tests/unit/test_session_bootstrap.py`.
- **CLI:** `packages/soothe-cli/tests/unit/ux/` (daemon session normalize, event processor, TUI paths).

---

## Related specifications

- [RFC-503](../specs/RFC-503-loop-first-user-experience.md) — UX and wire semantics for loops.
- [RFC-504](../specs/RFC-504-loop-management-cli-commands.md) — Loop management CLI commands.
- [RFC-454](../specs/RFC-454-slash-command-architecture.md) — Slash commands, `validate_command(..., loop_id)`, RPC routing.
- [RFC-215](../specs/RFC-215-agentloop-persistence-backend.md) — Persistence boundaries (daemon still uses checkpoints internally).

---

## Progress checklist

- [x] Per-loop input queues and workers (`LoopInputDispatcher`).
- [x] `bind_execution_thread_for_loop` for command/input paths.
- [x] `command_request` loop association + enqueue when subscription present.
- [x] SDK `bootstrap_loop_session` + `loop_input` on `WebSocketClient`.
- [x] CLI/TUI session and processor prefer `loop_id`; `resume_loop_id` on run launcher.
- [ ] Final audit: remove or formally deprecate remaining thread-first wire messages in docs and thin adapters.
- [ ] External client repos (Go/TS) version-pinned or released alongside the `soothe` **0.5.x** line where applicable.

---

## Changelog (this IG)

| Date | Note |
|------|------|
| — | Expanded with architecture, module map, wire summary, SDK/CLI pointers, tests, and checklist. |
| 2026-05-08 | Added **Daemon model: loops vs threads (final)**—`loop_id` vs `thread_ids` / `current_thread_id`, bind path, dispatcher isolation, client assumptions. |
