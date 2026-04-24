# IG-153: WebSocket Keepalive Timeout Fix

**Status**: ✅ Completed
**Date**: 2026-04-12
**Scope**: WebSocket transport ping/pong configuration
**RFCs**: RFC-0013 (Daemon Communication Protocol)

---

## Problem Statement

CLI `--no-tui` mode experienced WebSocket connection timeouts during long-running tool executions:

```
soothe --no-tui -p "run cloc to calculate code base"
● run cloc to calculate code base
→ 🌀 I will run cloc on the workspace root directory to generate code statistics.
○ Run cloc on the workspace root directory to count lines of code

[Connection closes after ~60 seconds with no output]
```

### Root Cause

WebSocket connection experienced "keepalive ping timeout" after 60 seconds:

```log
websockets.exceptions.ConnectionClosedError: received 1011 (internal error)
keepalive ping timeout; then sent 1011 (internal error) keepalive ping timeout
```

**Two independent timeout mechanisms were conflicting:**

1. **WebSocket library-level**: Default `ping_interval=20s`, `ping_timeout=20s` → timeout after 40s of inactivity
2. **Application-level**: Daemon sends heartbeat events every 5 seconds during query execution

The WebSocket library's ping/pong mechanism timed out even though the daemon was sending application heartbeats, because these two mechanisms operate at different layers.

---

## Solution

Disabled WebSocket library's ping/pong mechanism in **both server and client**:

### Server-side Fix

**File**: `src/soothe/daemon/transports/websocket.py:81-89`

```python
# Start WebSocket server
# Disable WebSocket library ping/pong since daemon uses application-level heartbeats
# (RFC-0013: daemon sends heartbeat events every 5 seconds during query execution)
self._server = await websockets.asyncio.server.serve(
    self._handle_client,
    host=self._config.host,
    port=self._config.port,
    ssl=ssl_context,
    ping_interval=None,  # Disable ping/pong mechanism
    ping_timeout=None,   # Use application-level heartbeats instead
)
```

### Client-side Fix

**File**: `src/soothe/daemon/websocket_client.py:51-57`

```python
try:
    # Disable WebSocket ping/pong to use application-level heartbeats (RFC-0013)
    self._ws = await websockets.asyncio.client.connect(
        self._url,
        ping_interval=None,  # Disable client-side ping/pong
        ping_timeout=None,  # Use daemon heartbeats instead
    )
    self._connected = True
```

### Why This Works

1. **RFC-0013 daemon heartbeat**: Server broadcasts `DaemonHeartbeatEvent` every 5 seconds during query execution (see `src/soothe/daemon/server.py:468-502`)
2. **CLI handles heartbeats**: Headless client tracks heartbeats to extend query start timeout (see `src/soothe/ux/cli/execution/daemon.py:109-114`)
3. **No WebSocket-level conflict**: By disabling library ping/pong, only application-level heartbeats maintain connection keepalive

---

## Implementation

### Changes

**File 1**: `src/soothe/daemon/transports/websocket.py:81-89`

Added `ping_interval=None` and `ping_timeout=None` to server-side `websockets.serve()` call:

```diff
 # Start WebSocket server
+# Disable WebSocket library ping/pong since daemon uses application-level heartbeats
+# (RFC-0013: daemon sends heartbeat events every 5 seconds during query execution)
 self._server = await websockets.asyncio.server.serve(
     self._handle_client,
     host=self._config.host,
     port=self._config.port,
     ssl=ssl_context,
+    ping_interval=None,  # Disable ping/pong mechanism
+    ping_timeout=None,   # Use application-level heartbeats instead
 )
```

**File 2**: `src/soothe/daemon/websocket_client.py:51-57`

Added `ping_interval=None` and `ping_timeout=None` to client-side `websockets.connect()` call:

```diff
 try:
+    # Disable WebSocket ping/pong to use application-level heartbeats (RFC-0013)
-    self._ws = await websockets.asyncio.client.connect(self._url)
+    self._ws = await websockets.asyncio.client.connect(
+        self._url,
+        ping_interval=None,  # Disable client-side ping/pong
+        ping_timeout=None,  # Use daemon heartbeats instead
+    )
     self._connected = True
```

### Why Both Sides Needed the Fix

The WebSocket ping/pong mechanism operates as a **bidirectional handshake**:
1. **Server** sends ping frames at `ping_interval` (default: 20s)
2. **Client** must respond with pong within `ping_timeout` (default: 20s)
3. If either side doesn't respond, the connection closes with "keepalive ping timeout"

Even with the server-side fix, the client's default ping timeout was still active, causing the client to timeout if it didn't receive pongs from the server. Therefore, **both sides** needed to disable ping/pong to fully rely on application-level heartbeats.

### Testing

**Verification**: All checks passed
- ✓ Code formatting (Ruff)
- ✓ Linting (zero errors)
- ✓ Unit tests (1584 passed)

**Manual tests**:

1. **Simple test** (works):
```bash
soothe daemon restart
soothe --no-tui -p "echo hello"
# Output: hello ✓
```

2. **Long-running command test** (70 seconds - works):
```bash
soothe --no-tui -p "sleep 70 && echo done"
# Output: Full execution completed after 92.8s ✓
```

3. **Real-world cloc test** (460+ seconds - works):
```bash
soothe --no-tui -p "run cloc to calculate code base"
# Output: Full cloc statistics report after 494.7s ✓
# No WebSocket timeout despite 8+ minute execution time
```

---

## Impact Analysis

### What This Fixes

✅ Long-running tool executions (>40 seconds) no longer timeout
✅ WebSocket connections remain alive during extended LLM processing
✅ CLI `--no-tui` mode works reliably for all query durations

### What This Does NOT Affect

- ✓ Application-level heartbeat mechanism unchanged (still sends every 5s)
- ✓ TUI mode unchanged (uses same WebSocket connection)
- ✓ Daemon protocol unchanged (same heartbeat event format)
- ✓ Other transports unchanged (Unix socket, HTTP REST)

### Safety Considerations

**Q: Is disabling WebSocket ping/pong safe?**
A: Yes, because:
1. Application-level heartbeats provide equivalent keepalive functionality
2. Heartbeats are only sent during query execution (when connection is active)
3. WebSocket library ping/pong was redundant with application heartbeats

**Q: What about idle connections?**
A: Idle connections (no query running) don't need keepalive:
- Client can reconnect if connection drops during idle
- Daemon state persists across connections (RFC-0013)
- No active query = no risk of losing work

---

## Related Work

### RFC-0013: Daemon Communication Protocol

Specifies:
- Daemon heartbeat interval: 5 seconds
- Heartbeat event format: `DaemonHeartbeatEvent`
- Heartbeat sent only during query execution

### Implementation Reference

- Daemon heartbeat implementation: `src/soothe/daemon/server.py:468-502`
- CLI heartbeat handling: `src/soothe/ux/cli/execution/daemon.py:109-114`
- Heartbeat event definition: `src/soothe/core/event_catalog.py:192`

---

## Lessons Learned

1. **Bidirectional WebSocket handshake**: WebSocket ping/pong is a bidirectional protocol - both server AND client must disable it to fully bypass transport-level keepalive
2. **Layer separation**: Application-level and transport-level keepalive mechanisms can conflict when operating independently
3. **Default timeouts**: WebSocket library defaults (20s ping, 20s timeout = 40s total) are too aggressive for long-running operations (>60s)
4. **Explicit configuration**: Always configure keepalive timeouts explicitly when mixing application-level and transport-level mechanisms
5. **Testing at scale**: Simple tests (<10s) pass with partial fixes; need realistic long-running tests (>60s) to surface timeout issues

---

## Future Considerations

### Optional Enhancement

Consider documenting WebSocket keepalive strategy in RFC-0013:
- Current: Application-level heartbeats only
- Alternative: Mixed approach with WebSocket ping/pong configured to match application heartbeat interval

Not urgent - current fix works well.

---

## Conclusion

WebSocket connection timeout issue resolved by disabling library-level ping/pong and relying solely on RFC-0013 application-level heartbeats. Fix verified and ready for production.