---
title: "Daemon Server API"
parent: API Reference
grand_parent: Wiki
nav_order: 2
description: >-
  The soothe_daemon package — a long-running background server hosting SootheRunner instances with multi-transport communication.
---

# Daemon Server (`soothe_daemon`)

The `soothe_daemon` package is Layer 3 of the Soothe architecture — a long-running background server that hosts `SootheRunner` instances, manages multi-transport communication, and coordinates goal dispatch. It is the bridge between clients (CLI, SDK, messaging platforms) and the agent runtime.

> **Source**: `packages/soothe-daemon/src/soothe_daemon/`
> **Package**: `soothe-daemon` (note the hyphen) · **Python**: `>=3.11` · **Stability**: ⚠️ Alpha

---

## Server Lifecycle

> **Source**: `packages/soothe-daemon/src/soothe_daemon/server/core.py`

### SootheDaemon

`SootheDaemon` is the main server class. It owns the `SootheRunner`, the `ChannelManager`, the `EventBus`, the `ClientSessionManager`, and all background services (autopilot, cron, memory profiler).

The daemon follows a strict startup sequence:

1. **Config load** — `SootheConfig` (agent core, `config.yml`) + `SootheDaemonConfig` (transports, worker pool, `daemon.yml`) are loaded separately. The `.env` file is loaded *before* any langchain imports so provider keys are available at import time.
2. **PID lock** — `acquire_pid_lock()` writes `${SOOTHE_HOME}/soothe.pid` to enforce single-instance. This is a file-based lock, not just a PID file — concurrent daemons on the same home directory will fail to start.
3. **Channel init** — `ChannelManager` initializes all enabled channels from the registry.
4. **Ready state** — The daemon transitions through `starting` → `warming` → `ready`. Clients connecting during `starting`/`warming` are held with a bounded wait (RFC-450); the daemon does not re-push `daemon_ready` on transition, so clients must re-request status.

### Minimal Startup

```python
from soothe_daemon.bootstrap import run_daemon

run_daemon(config_path="config/config.yml")
```

### Key Lifecycle Gotchas

- **Detached mode** — When `detached=True`, SIGINT shutdown handling is disabled. This is for daemonized background processes where the parent manages lifecycle.
- **Heartbeat** — The daemon broadcasts a heartbeat every 5 seconds (`_HEARTBEAT_INTERVAL_S`) to all connected clients.
- **Cleanup timeout** — On `stop()`, the daemon waits up to 8 seconds (`_STOP_TIMEOUT_S`) for graceful shutdown, then 3 seconds (`_CLEANUP_TIMEOUT_S`) for channel cleanup.

---

## Bootstrap & Process Management

> **Source**: `packages/soothe-daemon/src/soothe_daemon/bootstrap/`

`run_daemon()` is the canonical entrypoint. It accepts both `SootheConfig` and `SootheDaemonConfig` objects (or paths to their YAML files), constructs a `SootheDaemon`, and blocks on `serve_forever()`.

The `pid_path()` function returns the PID file location (`${SOOTHE_HOME}/soothe.pid` by default). CLI commands like `soothed status` and `soothed stop` use this file for process discovery.

### Two Config Files

A common confusion: the daemon uses **two separate config files**:

| File | Config Class | Controls |
|------|-------------|----------|
| `config.yml` | `SootheConfig` | Agent core — providers, models, protocols, tools |
| `daemon.yml` | `SootheDaemonConfig` | Server — transports, worker pool, channels, TLS |

The agent config can be shared across daemon and non-daemon (embedded) deployments. The daemon config is server-specific.

---

## Channel Architecture

> **Source**: `packages/soothe-daemon/src/soothe_daemon/channel_manager.py`, `packages/soothe-daemon/src/soothe_daemon/channels/`

### ChannelManager

`ChannelManager` (RFC-620) is the coordination hub for all transports. It:

1. Initializes enabled channels from configuration via the channel registry
2. Routes inbound messages to `EventBus` loop topics
3. Subscribes to loop topics, translates events, dispatches outbound messages
4. Handles streaming: coalesces deltas, buffers for non-streaming channels
5. Applies retry policy on send failures (exponential backoff: 1s, 2s, 4s)

The manager supports `broadcast()` (all clients, with optional exclusion) and `send_to_client()` (targeted delivery).

### Channel Base Class

All channels extend `Channel` (ABC) with capability flags:

| Flag | Meaning | WebSocket | Telegram | Slack | Email |
|------|---------|:---------:|:-------:|:-----:|:-----:|
| `supports_inbound` | Can receive messages | ✅ | ✅ | ✅ | ✅ |
| `supports_outbound` | Can send messages | ✅ | ✅ | ✅ | ✅ |
| `supports_streaming` | Incremental deltas | ✅ | ❌ | ❌ | ❌ |

Streaming channels receive `send_delta()` and `send_reasoning_delta()` calls; non-streaming channels receive buffered complete messages. This is why a Telegram bot shows the full response at once while a WebSocket client sees token-by-token streaming.

### WebSocket Channel

The primary transport. Runs a FastAPI/uvicorn server with WebSocket endpoint. Supports multiple concurrent clients, TLS, CORS, and configurable max frame size (default 10 MiB). Also hosts command handlers for autopilot, cron, and memory profiling.

```yaml
transport:
  websocket:
    host: "127.0.0.1"
    port: 8765
    max_frame_size: 10485760  # 10 MiB — match SDK client's setting
```

> **Gotcha**: The SDK client's `max_frame_size` must be ≥ the daemon's. The `websockets` library defaults to 1 MiB, which silently closes the connection (code 1009) when the daemon streams larger JSON events.

### Platform Channels (16+)

Each platform channel is a self-contained plugin following the same `Channel` pattern. They are configured under the top-level `channels:` section:

| Channel | Module | Platform |
|---------|--------|----------|
| Telegram | `channels.telegram` | Telegram Bot API |
| Slack | `channels.slack` | Slack Socket Mode |
| Discord | `channels.discord` | Discord Bot API |
| Feishu/Lark | `channels.feishu` | Feishu WebSocket |
| Matrix | `channels.matrix` | Matrix (Element) |
| WhatsApp | `channels.whatsapp` | Node.js bridge |
| Signal | `channels.signal` | signal-cli JSON-RPC |
| Email | `channels.email` | IMAP/SMTP |
| MS Teams | `channels.msteams` | Microsoft Teams |
| WeChat | `channels.weixin` | Personal WeChat |
| WeCom | `channels.wecom` | Enterprise WeChat |
| DingTalk | `channels.dingtalk` | DingTalk |
| QQ | `channels.qq` | QQ |
| Mochat | `channels.mochat` | Mochat (Socket.IO) |

Channels are lazily imported — the `soothe_daemon` `__init__.py` uses `__getattr__` lazy loading to avoid the 5+ second import cost of channels/nio/crypto at package load time.

---

## Session Management

> **Source**: `packages/soothe-daemon/src/soothe_daemon/server/session.py`

`ClientSessionManager` creates and tracks `ClientSession` objects, each holding a client's `client_id`, current `loop_id`, `thread_id`, `workspace`, and an `asyncio.Queue` for event streaming.

Key design details:
- **Event queue with backpressure** — Each client gets a bounded queue (default 10,000 events). If the consumer is too slow, events are dropped with a log throttle (one drop-log per 5 seconds per client).
- **Priority-aware draining** — During drain settle, the manager peeks the queue for HIGH/CRITICAL priority events and gives them extra settle time (0.15s margin, IG-436).
- **Sender filtering** — Events originating from a client are not echoed back to that same client (prevents feedback loops), with drop logging throttled to avoid spam.

---

## RPC Commands

> **Source**: `packages/soothe-daemon/src/soothe_daemon/server/commands.py`

The daemon accepts structured RPC commands over WebSocket (RFC-454). Each request has `type: "command_request"`, a `command` name, optional `params`, a `loop_id`, and a `request_id` for correlation.

### Available Commands

| Command | Actions | Purpose |
|---------|---------|---------|
| `/memory` | `clear`, `recall`, `remember` | Manage agent memory for the loop |
| `/policy` | `check`, `list` | Inspect active permissions |
| `/thread` | `create`, `list`, `show`, `delete` | Thread lifecycle management |
| `/history` | — | Fetch conversation history (with limit + metadata flag) |
| `/clear` | — | Clear current conversation context |
| `/cancel` | — | Cancel active execution |
| `/exit` | — | Shut down the daemon |

### Command Binding

A critical implementation detail: commands arrive with a `loop_id` (the StrangeLoop subscription scope), but handlers need a `checkpoint_thread_id` (the LangGraph persistence key). The handler calls `bind_execution_thread_for_loop()` to resolve the loop to its thread. If the runner already has `current_thread_id` set, it's used directly. This binding is why `/thread` and `/memory` commands work correctly even when multiple loops share a workspace.

---

## Health Checks

> **Source**: `packages/soothe-daemon/src/soothe_daemon/health/`

`HealthChecker` is invoked by the `soothed doctor` CLI command. It runs categorized checks and returns a `HealthReport` with overall status (`healthy` / `degraded` / `unhealthy`) and per-component detail.

### Check Categories

| Category | Module | What it validates |
|----------|--------|-------------------|
| `config` | `config_check` | Config file validity, env resolution |
| `daemon` | `daemon_check` | Daemon process, PID file, ports |
| `persistence` | `persistence_check` | DB connectivity (SQLite/PostgreSQL) |
| `protocols` | `protocols_check` | Protocol backend health (memory, durability, etc.) |
| `vector_stores` | `vector_stores_check` | Vector DB connectivity + dimension match |
| `providers` | `providers_check` | LLM provider API key validity |
| `mcp_servers` | `mcp_check` | MCP server reachability |
| `models` | `embedding_warmup_check` | Model instantiation + embedding warmup |
| `external_apis` | `external_apis_check` | OpenAI/Anthropic/etc. connectivity |
| `observability` | `observability_check` | Logging, tracing config |

You can run a subset with `categories=["config", "protocols"]` or exclude specific ones with `exclude=["external_apis"]`.

---

## Daemon Configuration

> **Source**: `packages/soothe-daemon/src/soothe_daemon/config/models.py`

`SootheDaemonConfig` is separate from `SootheConfig`. It holds transport settings (WebSocket host/port/TLS), channel configs, worker pool sizing, and distributed runner settings. The default config path is resolved via `default_daemon_config_path()`.

`WebSocketConfig` fields worth noting:
- `cors_origins` defaults to `["http://localhost:*", "http://127.0.0.1:*"]` — browser clients must match
- `tls_enabled` / `tls_cert` / `tls_key` for secure WebSocket (`wss://`)
- `max_frame_size` must be coordinated with SDK clients (see gotcha above)

---

## See Also

- [Core API](core-api.md) — Layer 1/2 agent and runner
- [SDK API](sdk-api.md) — WebSocket client for connecting to this daemon
- [Daemon Management Guide](../daemon-management.md) — Operational lifecycle
- [Multi-Transport Communication](../multi-transport.md) — Channel architecture deep-dive
- [RFC-302 Daemon Communication](../../specs/RFC-302-daemon-communication.md) — Specification
