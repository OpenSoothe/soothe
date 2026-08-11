# Soothe Data Flow — CLI ↔ Daemon ↔ Host (soothe) Communication

Canonical diagram: [`data_flow_daemon_cli.mmd`](data_flow_daemon_cli.mmd)

Captures the end-to-end wire path for a user turn: CLI encodes a protocol-1
envelope, the daemon routes it to the host runner, and streaming events flow
back over the same WebSocket session. Module references follow the one-way DAG
from [`module_boundaries.md`](module_boundaries.md) (AGENTS.md §7b).

---

## 1. Participants (by package)

| Process | Package | Role in this flow |
|---------|---------|-------------------|
| CLI | `soothe-cli` | Typer command + Textual TUI; owns `TuiDaemonSession` and `AsyncCommandClient` |
| Wire | `soothe-sdk` (PyPI) | `wire.codec` envelopes, `wire.protocol` JSON encode/decode |
| Transport | `soothe-client-python` (submodule) | `WebSocketClient` connection + priority-aware inbound queue |
| Daemon | `soothe-daemon` | `soothed` process: WS server, `MessageRouter`, `LoopInputDispatcher`, `EventBus` |
| Host | `soothe` | `QueryEngine.run_query` → `SootheRunner` → StrangeLoop graph |

The CLI **never imports** daemon or host code. It talks to the daemon only
through wire contracts in `soothe-sdk` and the `soothe-client-python`
transport (hard ban §7b.1). The daemon **never imports** `soothe_client` in
runtime source (hard ban §7b.2); admin RPCs use `soothe_sdk.wire`.

---

## 2. Request path — CLI → daemon → host

```
CLI command / TUI input
   │  loop_input | slash_command | rpc_command (method+params+id)
   ▼
TuiDaemonSession / AsyncCommandClient          [soothe_cli.runtime.transport.session]
   │  encode_envelope(msg)                      [soothe_sdk.wire.codec]
   │  encode_websocket_text(msg)               [soothe_sdk.wire.protocol]
   ▼
WebSocketClient.send → ws.send (text frame)     [soothe_client.websocket]
   │
   ▼── protocol-1 handshake ───────────────────────────────────────────────
   │   connection_init → connection_ack
   │   daemon advertises capabilities: streaming | batch | heartbeat | receipts
   │   (Router._DAEMON_CAPABILITIES, RFC-450 §8.2)
   ▼
AuthHandler → ClientSessionManager.create_session  [soothe_daemon.server]
   │
   ▼
MessageRouter.dispatch(client_id, msg)            [protocol/router.py]
   │  envelope types: request | notification | subscribe | unsubscribe
   │  method → handler map (_METHOD_TO_HANDLER):
   │    slash_command    → _handle_command
   │    disconnect       → _handle_detach
   │    loop_events      → _handle_loop_subscribe
   │    autopilot_events → _handle_autopilot_subscribe
   │    rpc_command      → _handle_command_request
   ▼
DaemonHandlersMixin._handle_client_message        [server/handlers.py]
   │  validate_message → build_error_response on failure (transport boundary)
   │  type=loop_input / input → enqueue per-loop queue
   ▼
LoopInputDispatcher                                [runtime/loop_dispatcher.py]
   │  bind_execution_thread_for_loop(daemon, loop_id)
   │     - checkpoint thread id == loop_id (RFC-223)
   │     - fetch/update loop metadata via PersistenceManager
   │  _process_loop_input_message(loop_id, msg)
   │     - _coerce_loop_input_text(content)
   │     - _queue_options_from_daemon_message(msg): preferred_subagent, model,
   │       model_params, router_profile, intent_hint, response_schema,
   │       clarification_mode/answers, resume_interrupted, intake_scope
   ▼
QueryEngine.run_query(text, loop_id=..., ...)     [query/engine.py]
   │  admit → reserve turn generation → emit authoritative "running" frame
   │  stream_turn_overrides passed to runner
   ▼
SootheRunner (strange_loop / autopilot_worker)    [soothe.runner]
   │
   ▼
StrangeLoop graph (in-proc)                       [soothe.sloop.engine]
```

### Key wire shapes (request)

| `type` | Purpose | Dispatched by |
|--------|---------|---------------|
| `loop_input` (content: str \| {text}) | One user turn scoped to a loop | `LoopInputDispatcher` → `run_query` |
| `input` (text: str) | Legacy normalized queue payload | same handler |
| `command_request` | Slash-command RPC (cancel, resume, cron, plan, …) | `server/commands._handle_command_request` |
| `subscribe` (method=loop_events \| autopilot_events) | Open event stream for a loop | `ClientSessionManager.subscribe_loop` |
| `connection_init` | Protocol-1 handshake | `AuthHandler` + `build_connection_ack` |

---

## 3. Response path — host → daemon → CLI

```
StrangeLoop graph emits events + status frames
   │
   ▼
SootheRunner → QueryEngine._broadcast(status | event)   [query/engine.py]
   │
   ▼
EventBus.publish("loop:{loop_id}", event)                [event/bus.py]
   │  topic format: loop:{id} | global | autopilot
   │  lock-free hot path (IG-258 Phase 2); subscriber = asyncio.Queue
   ▼
ClientSessionManager._sender_loop(session)               [server/session.py]
   │  - pull from session.event_queue
   │  - batch up to 50 frames or batch_timeout window
   │  - IG-436: HIGH/CRITICAL priority (goal_completion, complete, terminal)
   │    flush immediately without batch wait
   │  - drop policy on queue backpressure (CRITICAL never dropped)
   ▼
ClientSessionManager._translate_for_client(session, msg)
   │  legacy frame → protocol-1 "next" envelope (RFC-450 §9.3)
   │  event_batch wrapper preserved as transport optimization
   ▼
ClientSessionManager.send_to_client(session, wire)
   │  async with session.send_lock:
   │    await session.transport.send(session.transport_client, wire)
   │  _note_delivery_sent_for_events (delivery-ack tracking)
   ▼
WebSocketClient ← ws text frame → decode_websocket_text → decode_envelope
   │  unwrap_next (soothe_client.appkit.events)
   │  early_drop_fn (CLI: should_drop_stream_chunk_early — LangChain-aware)
   ▼
DaemonSession.iter_turn_chunks()                        [appkit/daemon_session.py]
   │  turn-boundary detection, post-idle drain (DEFAULT_POST_IDLE_DRAIN_S=0.5),
   │  connection-loss detection, stale-loop handling
   ▼
EventProcessor → PresentationEngine → renderer           [soothe_cli.runtime]
   │  headless: HeadlessCliRenderer (stdout)
   │  TUI: Textual widgets (cards, mermaid, tool_display)
   ▼
User
```

### Autopilot event bridge

Internal autopilot events are bridged to client-visible events for sessions
with `autopilot_subscribed=True` (RFC-228). The daemon subscribes a bridge
callback to the internal bus (`subscribe("*", _bridge_internal_to_client)`)
which converts via `internal_to_client_event` and republishes on the
`autopilot` topic.

### RPC command responses

`server/commands._send_command_response` routes the matched `id` reply back
through `ClientSessionManager.send_to_client`, so the CLI `AsyncCommandClient`
sees a request/reply correlation on its RPC sidecar socket (separate from the
stream socket so metadata calls don't starve loop events).

---

## 4. Delivery & liveness guarantees

| Mechanism | Owner | Behavior |
|-----------|-------|----------|
| `connection_ack` capabilities | `MessageRouter._DAEMON_CAPABILITIES` | Daemon advertises `streaming`, `batch`, `heartbeat`, `receipts` |
| Delivery-ack tracking | `ClientSessionManager` | `_wire_event_needs_delivery_ack` marks `complete`, terminal message frames, `STRANGE_LOOP_COMPLETED`; `await_loop_delivery_drained` gates turn `complete`/`idle` |
| Priority flush (IG-436) | `_sender_loop` | `EventPriority.HIGH`/`CRITICAL` (goal_completion) flush immediately, skip batch fill |
| Inbound drop priority | `WebSocketClient._inbound_frame_drop_priority` | 0 = never drop (terminal, goal_completion, error, ack); 1 = prefer keep (tool_call_updates, event_batch); 2 = drop candidate (streaming text) |
| Heartbeat | `SootheDaemon._periodic_heartbeat` (5s) | Keeps idle sessions alive |
| Loop GC / status reconciliation | `_periodic_loop_gc`, `_periodic_loop_status_reconciliation` | Reaps orphaned loops, reconciles drifted status |

---

## 5. Wire serialization

`soothe_sdk.wire.protocol._serialize_for_json` is LangChain-message-aware:
it recurses into lists/dicts, tries `model_dump()` then `dict()`, then
`__dict__`, finally `str(obj)`. This means `HumanMessage` / `AIMessage` and
structured-output Pydantic models emitted by the StrangeLoop graph are
serialized in-place at the daemon broadcast boundary — no separate mapping
step is needed before `encode_websocket_text`.

---

## 6. Checkpoint thread binding

`bind_execution_thread_for_loop` enforces the RFC-223 invariant: the main
StrangeLoop checkpoint thread id **equals** the `loop_id`. Returning a
distinct UUID would cause `loop_state_get` / `loop_messages` RPCs to query
the wrong LangGraph checkpoint and surface an empty conversation on resume.
Fork threads use the `{loop_id}__step_<id>` scheme and remain listed in
`thread_ids` history.

---

## 7. Module ownership (cross-ref)

Full package DAG, import allow/deny matrix, and hard bans are documented in
[`module_boundaries.md`](module_boundaries.md). This flow diagram references
the same packages and respects the same one-way arrows:

- `soothe-cli` → `soothe-sdk` + `soothe-client-python` (no daemon/host import)
- `soothe-daemon` → `soothe` + `soothe-sdk` (no `soothe_client` in runtime)
- `soothe` → `soothe-sdk` + `soothe-nano` + `soothe-deepagents`
