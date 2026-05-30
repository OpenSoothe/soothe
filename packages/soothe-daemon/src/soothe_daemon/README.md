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
│  ChannelManager        multi-channel     │
│  channels/             WebSocket, HTTP, …│
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
| `server.py` | `SootheDaemon` — process lifecycle, WebSocket server |
| `entrypoint.py` | `run_daemon()` — CLI entry point, signal handling |
| `channel_manager.py` | Manages all channels (WebSocket, HTTP REST, plugins) |
| `channels/` | RFC-620 channel implementations (`WebSocketChannel`, `HttpRestChannel`, …) |
| `transports/` | Low-level transport helpers still used for HTTP autopilot route setup |
| `message_router.py` | Routes incoming JSON messages to runner public APIs |
| `query_engine.py` | `QueryEngine` — streams a single query, owns cancel / ownership |
| `thread_state.py` | `ThreadStateRegistry` — per-thread draft, history, logger |
| `client_session.py` | Tracks connected client metadata and event filtering |
| `event_bus.py` | In-process pub/sub for broadcasting events to all clients |
| `protocol.py` / `protocol_v2.py` | Wire-format encode/decode helpers |
| `websocket_client.py` | `WebSocketClient` — for CLI commands that talk to the daemon |
| `singleton.py` | Single-instance enforcement |
| `paths.py` | `pid_path()` — canonical PID file path |
| `health/` | `HealthChecker` and per-category check implementations |
| `persistence/` | PostgreSQL pool lifecycle, worker cleanup, pool sizing, persistence health |

---

## persistence/ subpackage

Daemon-side persistence helpers (shared PostgreSQL pools, stale worker cleanup,
pool sizing aligned with `thread_pool`, and `check_persistence` for doctor).

```
daemon/persistence/
├── __init__.py           # Public exports
├── pools.py              # Pre-open, idle release, periodic maintenance, shutdown
├── pool_sizing.py        # recommended_*_pool_size helpers
├── process_cleanup.py    # reap + periodic_stale_worker_reap (asyncio + to_thread)
└── health_check.py       # Persistence category for HealthChecker
```

- **CLI**: `python -m soothe_daemon.persistence` (optional `--dry-run`) — manual reap when the daemon is stopped or after crashes.
- **Automatic**: start/stop one-shot reap; with `worker_pool.enabled` and `stale_worker_reap.enabled`, periodic reap every `stale_worker_reap.interval_seconds` (default 1800s) via an asyncio task (does not block the event loop).

---

## health/ subpackage

Health checks verify all Soothe components including daemon connectivity,
persistence, providers, protocols, and external APIs.

```
daemon/health/
├── __init__.py          # HealthChecker, format_* exports
├── checker.py           # HealthChecker orchestrator
├── models.py            # CheckResult, CategoryResult, HealthReport
├── formatters.py        # format_text, format_markdown, format_json
└── checks/
    ├── config_check.py
    ├── daemon_check.py  # uses soothe_daemon.paths (pid_path)
    ├── protocols_check.py
    ├── providers_check.py
    ├── vector_stores_check.py
    ├── mcp_check.py
    ├── external_apis_check.py
    └── observability_check.py
```

Health checks live here (not in `core`) because they legitimately depend
on daemon-layer paths (`pid_path`) and daemon connectivity.

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
from soothe_daemon import SootheDaemon      # main daemon class
from soothe_daemon import WebSocketClient   # client for CLI ↔ daemon
from soothe_daemon import run_daemon        # entrypoint
from soothe_daemon import pid_path          # ~/.soothe/soothe.pid
from soothe_daemon.health import HealthChecker
```

---

## Message flow

```
Client connects (WebSocket / HTTP)
  → ChannelManager routes connection to handler
  → MessageRouter.handle(msg) dispatches by msg["type"]
  → QueryEngine.stream(runner, query, thread_id, ...)
    → runner.astream(...)  yields (namespace, mode, data)
    → events broadcast via EventBus to all clients
```
