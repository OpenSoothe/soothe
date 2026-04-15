# soothe.daemon

Long-running background process that serves the Soothe agent over multiple
transports. Acts as a **transport adapter** around `SootheRunner` — it does
not re-implement orchestration logic.

---

## Relationship to `soothe.core`

```
┌──────────────────────────────────────────┐
│  TUI / CLI client                        │
└───────────────┬──────────────────────────┘
                │ WebSocket / HTTP REST
┌───────────────▼──────────────────────────┐
│  soothe.daemon                           │
│                                          │
│  SootheDaemon          process lifecycle │
│  TransportManager      multi-transport   │
│  MessageRouter         JSON → runner API │
│  QueryEngine           streaming + cancel│
│  ThreadStateRegistry   per-thread state  │
└───────────────┬──────────────────────────┘
                │ constructs / calls
┌───────────────▼──────────────────────────┐
│  soothe.core.runner.SootheRunner         │
│  (orchestration, protocols, streaming)   │
└──────────────────────────────────────────┘
```

`SootheDaemon` holds a single `SootheRunner` instance and delegates all
query execution to it via public APIs (`astream`, thread helpers). The
daemon **never** duplicates protocol, memory, or planning logic.

---

## Directory map

| File / Package | Responsibility |
|----------------|----------------|
| `server.py` | `SootheDaemon` — process lifecycle, WebSocket server, Unix socket |
| `entrypoint.py` | `run_daemon()` — CLI entry point, signal handling |
| `transport_manager.py` | Manages multiple transport servers (WebSocket, HTTP REST) |
| `transports/` | `WebSocketTransport`, `HttpRestTransport`, `TransportServer` base |
| `message_router.py` | Routes incoming JSON messages to runner public APIs |
| `query_engine.py` | `QueryEngine` — streams a single query, owns cancel / ownership |
| `thread_state.py` | `ThreadStateRegistry` — per-thread draft, history, logger |
| `client_session.py` | Tracks connected client metadata and event filtering |
| `event_bus.py` | In-process pub/sub for broadcasting events to all clients |
| `protocol.py` / `protocol_v2.py` | Wire-format encode/decode helpers |
| `websocket_client.py` | `WebSocketClient` — for CLI commands that talk to the daemon |
| `singleton.py` | Single-instance enforcement |
| `paths.py` | `pid_path()`, `socket_path()` — canonical filesystem paths |
| `health/` | `HealthChecker` and per-category check implementations |

---

## health/ subpackage

Health checks verify all Soothe components including daemon socket,
persistence, providers, protocols, and external APIs.

```
daemon/health/
├── __init__.py          # HealthChecker, format_* exports
├── checker.py           # HealthChecker orchestrator
├── models.py            # CheckResult, CategoryResult, HealthReport
├── formatters.py        # format_text, format_markdown, format_json
└── checks/
    ├── config_check.py
    ├── daemon_check.py  # uses soothe.daemon.paths (pid_path, socket_path)
    ├── persistence_check.py
    ├── protocols_check.py
    ├── providers_check.py
    ├── vector_stores_check.py
    ├── mcp_check.py
    ├── external_apis_check.py
    └── observability_check.py
```

Health checks live here (not in `core`) because they legitimately depend
on daemon-layer paths (`pid_path`, `socket_path`) and daemon connectivity.

---

## Boundary rules

| Direction | Rule |
|-----------|------|
| `daemon` → `core` | OK — daemon composes `SootheRunner` |
| `daemon` → `soothe.logging` | OK |
| `daemon` → `config` | OK |
| `daemon` → `ux` | **Forbidden** |
| `daemon.health` → `daemon.paths` | OK — intra-daemon import |
| Orchestration logic in daemon | **Forbidden** — belongs in `core` |

---

## Key types

```python
from soothe.daemon import SootheDaemon      # main daemon class
from soothe.daemon import WebSocketClient   # client for CLI ↔ daemon
from soothe.daemon import run_daemon        # entrypoint
from soothe.daemon import pid_path          # ~/.soothe/soothe.pid
from soothe.daemon import socket_path       # ~/.soothe/soothe.sock
from soothe.daemon.health import HealthChecker
```

---

## Message flow

```
Client connects (WebSocket / HTTP)
  → TransportManager routes connection to handler
  → MessageRouter.handle(msg) dispatches by msg["type"]
  → QueryEngine.stream(runner, query, thread_id, ...)
    → runner.astream(...)  yields (namespace, mode, data)
    → events broadcast via EventBus to all clients
```
