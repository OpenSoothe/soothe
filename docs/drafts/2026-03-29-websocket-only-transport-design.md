# Design Draft: WebSocket-Only Transport

**Date:** 2026-03-29
**Status:** Phase 0 Draft
**Related RFCs:** RFC-0013 (Daemon Communication Protocol)

---

## Problem Statement

The Unix domain socket transport exhibits two stability issues:

1. **Stale socket files** - After daemon crashes, `~/.soothe/soothe.sock` remains and blocks new connections
2. **Random disconnects** - Large payload streaming causes unexpected connection drops

Additionally, WebSocket transport is required for remote clients (browser UI, remote CLI). Maintaining two transports adds complexity and the Unix socket issues suggest fundamental problems worth removing entirely.

---

## Proposed Solution

Remove Unix domain socket transport. Make WebSocket the sole bidirectional transport for all clients (local CLI/TUI and remote). HTTP REST remains for health checks and CRUD operations.

---

## Architecture Change

```
Before:                           After:
┌─────────────────────┐           ┌─────────────────────┐
│ CLI/TUI → UnixSock  │           │ CLI/TUI → WebSocket │
│ Web UI  → WebSocket │           │ Web UI  → WebSocket │
│ Health  → HTTP REST │           │ Health  → HTTP REST │
└─────────────────────┘           └─────────────────────┘
```

**Transport roles after change:**
- **WebSocket**: All bidirectional streaming (CLI, TUI, browser, remote)
- **HTTP REST**: Health checks, daemon status, CRUD operations (unchanged)

---

## Files Removed

| File | Description |
|------|-------------|
| `src/soothe/daemon/transports/unix_socket.py` | Unix socket server implementation |
| `src/soothe/daemon/client.py` | Unix socket client (JSONL-based DaemonClient) |

---

## Files Modified

### Core Daemon

| File | Change |
|------|--------|
| `src/soothe/daemon/transport_manager.py` | Remove Unix socket from `_build_transports()`, WebSocket becomes required (error if disabled) |
| `src/soothe/daemon/server.py` | Remove Unix socket references, require WebSocket enabled |
| `src/soothe/daemon/singleton.py` | Remove PID lock file path references (keep PID tracking for process management) |

### Configuration

| File | Change |
|------|--------|
| `src/soothe/config.py` | Remove `UnixSocketConfig` section, deprecate `SOOTHE_TRANSPORTS__UNIX_SOCKET_*` env vars |
| `config/config.yml` | Remove `transports.unix_socket` section |
| `config/env.example` | Remove Unix socket environment variables |

### CLI/TUI

| File | Change |
|------|--------|
| `src/soothe/ux/cli/execution/daemon.py` | Replace Unix socket client with WebSocket client for all connections |
| `src/soothe/ux/cli/commands/daemon_cmd.py` | Update daemon start/stop/connect commands for WebSocket |

### Documentation

| File | Change |
|------|--------|
| `docs/specs/RFC-0013.md` | Update transport layer section, remove Unix socket from wire format and client sections |
| `docs/user_guide.md` | Update daemon connection instructions |

---

## Client Connection Path

CLI/TUI will connect via WebSocket to localhost:

```python
# Connection sequence (existing websocket_client.py already supports this)
client = WebSocketClient(url="ws://127.0.0.1:8765", token=None)
await client.connect()
await client.request_daemon_ready()
await client.wait_for_daemon_ready(timeout_s=20)
await client.send_new_thread()  # or send_resume_thread(thread_id)
await client.subscribe_thread(thread_id, verbosity=verbosity)
await client.send_input(prompt, autonomous=autonomous)
# Stream events via existing EventProcessor
```

**No new client implementation needed** - `websocket_client.py` already provides full protocol support.

---

## Configuration

### New Default Config

```yaml
transports:
  websocket:
    enabled: true         # Required - daemon fails if disabled
    host: "127.0.0.1"     # Bind address
    port: 8765            # Default, configurable
    cors_origins: ["*"]   # CORS patterns for browser clients
  http_rest:
    enabled: true
    host: "127.0.0.1"
    port: 8766
```

### Environment Variables

**Active:**
- `SOOTHE_TRANSPORTS__WEBSOCKET__HOST`
- `SOOTHE_TRANSPORTS__WEBSOCKET__PORT`
- `SOOTHE_TRANSPORTS__WEBSOCKET__CORS_ORIGINS`

**Deprecated (no longer functional):**
- `SOOTHE_TRANSPORTS__UNIX_SOCKET__ENABLED`
- `SOOTHE_TRANSPORTS__UNIX_SOCKET__PATH`

---

## Error Handling

### WebSocket Connection Failure

CLI exits with clear message:
```
Error: Unable to connect to daemon at ws://127.0.0.1:8765
Hint: Ensure daemon is running with 'soothe daemon start'
```

Retry logic preserved (existing `_connect_with_retries` adapts to WebSocket).

### Port Conflict

Daemon startup failure:
```
Error: Port 8765 already in use
Hint: Configure alternate port via SOOTHE_TRANSPORTS__WEBSOCKET__PORT
```

### Daemon Not Running

Same behavior as before - client retries with exponential backoff, then fails with actionable message.

---

## RFC-0013 Updates

### Sections to Modify

1. **Transport Layer** - Remove Unix socket from transport comparison table
2. **Wire Format** - WebSocket text frames only (remove JSONL section)
3. **Connection Flow** - WebSocket-only handshake sequence
4. **Client Implementation** - `websocket_client.py` as primary reference client

### Sections to Remove

- Unix socket specific implementation details
- Stale socket cleanup logic (no longer applicable)
- JSONL message framing description

---

## Migration Path

For existing users:

1. No action required for default config (WebSocket already enabled)
2. Users with custom Unix socket path configs will see deprecation warning on startup
3. CLI/TUI automatically use WebSocket after update

---

## Success Criteria

1. CLI/TUI connect reliably to daemon via WebSocket
2. No stale socket file cleanup needed
3. Large payload streaming works without disconnects
4. Remote clients continue working unchanged
5. Single transport reduces codebase complexity

---

## Scope

This change affects:
- Daemon transport layer
- CLI/TUI connection code
- Configuration schema
- RFC-0013 documentation

Not affected:
- HTTP REST transport (retained)
- Event bus and message handling
- Session management
- Query execution logic

---

## Next Steps

After approval, proceed to Platonic Coding Phase 1:
1. Create RFC amendment or new RFC section for transport simplification
2. Update RFC-0013 with WebSocket-only specification
3. Generate implementation guide in `docs/impl/`