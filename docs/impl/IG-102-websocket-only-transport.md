# IG-102: WebSocket-Only Transport Implementation

**Implementation Guide**: IG-102
**Title**: Remove Unix Domain Socket, Use WebSocket-Only Transport
**Related RFC**: RFC-0013 (Unified Daemon Communication Protocol)
**Created**: 2026-03-29
**Status**: In Progress

## Overview

This guide implements the WebSocket-only transport architecture defined in RFC-0013. The Unix domain socket transport is removed due to stability issues (stale socket files, large payload disconnects). WebSocket becomes the sole bidirectional transport for all clients.

## Scope

| Aspect | Change |
|--------|--------|
| Transport layer | Remove Unix socket, WebSocket required |
| Client connection | CLI/TUI use WebSocket client to localhost |
| Configuration | Remove UnixSocketConfig section |
| Documentation | Update RFC-0013, user guide |

## Files to Delete

1. `src/soothe/daemon/transports/unix_socket.py` - Unix socket server
2. `src/soothe/daemon/client.py` - Unix socket client (JSONL-based DaemonClient)

## Files to Modify

### Core Daemon

| File | Change |
|------|--------|
| `src/soothe/daemon/transport_manager.py` | Remove Unix socket from `_build_transports()`, WebSocket required |
| `src/soothe/daemon/server.py` | Remove Unix socket references |
| `src/soothe/daemon/singleton.py` | Remove socket file cleanup logic |

### Configuration

| File | Change |
|------|--------|
| `src/soothe/config.py` | Remove `UnixSocketConfig` class and section |
| `config/config.yml` | Remove `transports.unix_socket` section |
| `config/env.example` | Remove Unix socket environment variables |

### CLI/TUI

| File | Change |
|------|--------|
| `src/soothe/ux/cli/execution/daemon.py` | Use WebSocket client for localhost connections |
| `src/soothe/ux/cli/commands/daemon_cmd.py` | Update daemon commands |

## Implementation Steps

### Step 1: Delete Unix Socket Files

Remove the Unix socket implementation files that are no longer needed.

```bash
rm src/soothe/daemon/transports/unix_socket.py
rm src/soothe/daemon/client.py
```

### Step 2: Update Transport Manager

Modify `src/soothe/daemon/transport_manager.py`:

1. Remove Unix socket import and transport building
2. Make WebSocket required (error if disabled)
3. Update transport order comment

### Step 3: Update Daemon Server

Modify `src/soothe/daemon/server.py`:

1. Remove Unix socket transport references
2. Remove any socket-specific cleanup logic

### Step 4: Update Singleton

Modify `src/soothe/daemon/singleton.py`:

1. Remove stale socket file cleanup (`_is_socket_live`, socket unlink)
2. Keep PID file logic for process management

### Step 5: Update Configuration

Modify `src/soothe/config.py`:

1. Remove `UnixSocketConfig` class
2. Remove `unix_socket` from `TransportsConfig`
3. Remove `SOOTHE_TRANSPORTS__UNIX_SOCKET_*` env var handling

Update `config/config.yml`:
1. Remove `transports.unix_socket` section

Update `config/env.example`:
1. Remove Unix socket environment variables

### Step 6: Update CLI Execution

Modify `src/soothe/ux/cli/execution/daemon.py`:

1. Import `WebSocketClient` instead of `DaemonClient`
2. Use WebSocket URL for localhost: `ws://127.0.0.1:{port}`
3. Remove any Unix socket-specific connection logic

### Step 7: Update Daemon Commands

Modify `src/soothe/ux/cli/commands/daemon_cmd.py`:

1. Update daemon start/stop/status commands
2. Remove Unix socket path references

## Configuration Changes

### Before

```yaml
transports:
  unix_socket:
    enabled: true
    path: ~/.soothe/soothe.sock
  websocket:
    enabled: true
    host: "127.0.0.1"
    port: 8765
```

### After

```yaml
transports:
  websocket:
    enabled: true         # Required - daemon fails if disabled
    host: "127.0.0.1"
    port: 8765
  http_rest:
    enabled: true
    host: "127.0.0.1"
    port: 8766
```

## Client Connection Changes

### Before (Unix Socket)

```python
from soothe.daemon.client import DaemonClient
client = DaemonClient()
await client.connect()  # Connects to ~/.soothe/soothe.sock
```

### After (WebSocket)

```python
from soothe.daemon.websocket_client import WebSocketClient
client = WebSocketClient(url="ws://127.0.0.1:8765")
await client.connect()
```

## Verification

After implementation, run:

```bash
./scripts/verify_finally.sh
```

This ensures:
- All linting passes
- All unit tests pass
- Code formatting is correct

## Success Criteria

1. ✅ Unix socket files deleted
2. ✅ Transport manager builds WebSocket only
3. ✅ CLI/TUI connect via localhost WebSocket
4. ✅ Configuration schema updated
5. ✅ All tests pass
6. ✅ No stale socket file issues

## Rollback Plan

If issues arise:
1. Restore deleted files from git
2. Restore configuration sections
3. Update transport manager to include Unix socket

## Timeline

- Estimated effort: 2-3 hours
- Risk level: Medium (breaking change for transport layer)