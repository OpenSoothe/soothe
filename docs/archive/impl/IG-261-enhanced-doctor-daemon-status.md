# IG-261: Enhanced Doctor Daemon Status Checks

**Implementation Guide**: IG-261
**Title**: Enhanced `soothed doctor` Daemon Status Checks
**Status**: Completed
**Created**: 2026-04-25
**Dependencies**: RFC-450, IG-258
**Number**: 261

## Summary

This implementation modernizes the `soothed doctor` daemon health checks from deprecated Unix socket-based verification to WebSocket + HTTP REST architecture (RFC-450), while adding comprehensive status monitoring including readiness states, queue metrics (IG-258), client sessions, active threads, and daemon uptime.

## Changes

### Phase 1: Replace Unix Socket Checks

**Modified Files**:
1. `/Users/chenxm/Workspace/Soothe/packages/soothe/src/soothe/daemon/health/checks/daemon_check.py`

**Removed**:
- `_check_socket_connectivity()` - Deprecated Unix socket check
- `_check_socket_responsiveness()` - Deprecated Unix socket JSON status check
- Unix socket stale lock detection

**Added**:
- `_check_websocket_connectivity(config)` - WebSocket transport connectivity check (RFC-450)
- `_check_http_rest_connectivity(config)` - HTTP REST transport connectivity check (RFC-450)
- `_check_http_rest_status(config)` - Fetch daemon status via HTTP REST /api/v1/status endpoint
- Updated `_check_stale_locks(config)` - Zombie daemon detection (PID alive but WebSocket dead)

**Updated**:
- `check_daemon(config)` - WebSocket-first priority logic instead of Unix socket-first

### Phase 2: Add Readiness and Status Checks

**Added Functions**:
1. `_check_daemon_readiness(config)` - Daemon readiness state via WebSocket handshake (RFC-450)
   - Reads `daemon_ready` message from WebSocket
   - Maps states: ready (OK), degraded (WARNING), error (ERROR), starting/warming (INFO)

2. `_check_daemon_uptime(pid)` - Daemon uptime from PID start time
   - Uses `psutil.Process.create_time()`
   - Formats human-readable uptime (hours, minutes)

3. `_check_client_sessions(config)` - Connected client sessions count
   - Calls HTTP REST `/api/v1/status` endpoint
   - Returns INFO status (informational)

4. `_check_active_threads(config)` - Active thread count
   - Calls HTTP REST `/api/v1/threads?status=running`
   - Returns WARNING if >80% of max_concurrent_threads

5. `_check_queue_depth(config)` - Queue depth monitoring (IG-258)
   - Calls HTTP REST `/api/v1/health` (enhanced endpoint)
   - Returns WARNING if input queue >80% or clients near capacity

### Phase 3: Extend HTTP REST Health Endpoint

**Modified Files**:
1. `/Users/chenxm/Workspace/Soothe/packages/soothe/src/soothe/daemon/transports/http_rest.py`
2. `/Users/chenxm/Workspace/Soothe/packages/soothe/src/soothe/daemon/transport_manager.py`

**Enhanced** `/api/v1/health` endpoint:
```python
@self._app.get("/api/v1/health")
async def health_check() -> dict[str, Any]:
    """Health check endpoint with queue metrics (IG-258)."""
    queue_metrics = {}
    
    # Input queue depth
    if self._runner and hasattr(self._runner, "_current_input_queue"):
        input_queue = self._runner._current_input_queue
        max_size = self._soothe_config.daemon.max_input_queue_size
        current_size = input_queue.qsize()
        
        queue_metrics["input_queue"] = {
            "current": current_size,
            "max": max_size,
            "percent": round((current_size / max_size * 100) if max_size > 0 else 0, 2)
        }
    
    # Event queue depths
    if self._session_manager and hasattr(self._session_manager, "_sessions"):
        event_queues = []
        for session in self._session_manager._sessions.values():
            if hasattr(session, "event_queue"):
                event_queues.append(session.event_queue.qsize())
        
        if event_queues:
            queue_metrics["event_queues"] = {
                "max_depth": max(event_queues),
                "avg_depth": round(sum(event_queues) / len(event_queues), 2),
                "clients_near_capacity": sum(1 for d in event_queues if d > 8000)  # >80% of 10000
            }
    
    return {
        "status": "healthy",
        "transport": "http_rest",
        "queues": queue_metrics
    }
```

**Added `session_manager` parameter** to `HttpRestTransport.__init__()`:
```python
def __init__(
    self,
    config: HttpRestConfig,
    thread_manager: Any | None = None,
    runner: Any | None = None,
    soothe_config: Any | None = None,
    session_manager: Any | None = None,  # NEW
) -> None:
```

**Updated `transport_manager.py`** to pass `session_manager`:
```python
http_transport = HttpRestTransport(
    self._config.transports.http_rest,
    thread_manager=self._thread_manager,
    runner=self._runner,
    soothe_config=self._soothe_config,
    session_manager=self._session_manager,  # NEW
)
```

### Phase 4: Dependencies

**Added `psutil` to dependencies**:
- `/Users/chenxm/Workspace/Soothe/packages/soothe/pyproject.toml`
- Added: `"psutil>=5.9.0"` to dependencies list

## Verification

### Manual Testing Checklist

1. **Start daemon**: `soothed start`
2. **Run doctor**: `soothed doctor --category daemon`
3. **Verify output contains**:
   - `websocket_connectivity` (OK/INFO)
   - `http_rest_connectivity` (OK/SKIPPED/INFO)
   - `daemon_readiness` (OK/INFO/WARNING)
   - `daemon_uptime` (INFO)
   - `client_sessions` (INFO)
   - `active_threads` (OK/WARNING)
   - `queue_depth` (OK/WARNING)
4. **Verify NO deprecated checks**:
   - NOT: `socket_connectivity`
   - NOT: `socket_responsiveness`
5. **Stop daemon**: `soothed stop`
6. **Run doctor again**: Expect INFO status "daemon not running"

### Verification Script

```bash
./scripts/verify_finally.sh
```

Expected:
- Format check: ✓
- Lint check: ✓ (zero errors)
- Unit tests: ✓ (1270 tests pass)

## Architecture Changes

### WebSocket-First Priority Logic

**Old (Unix socket-first)**:
```
Socket OK → PID checks informational
Socket fail → PID checks critical
```

**New (WebSocket-first)**:
```
WebSocket OK → All checks informational → Daemon healthy
WebSocket fail → HTTP REST fallback → Daemon degraded
Both fail → PID fallback → Zombie daemon or not running
```

### Daemon Health States

| Scenario | WebSocket | HTTP REST | PID | Status | Message |
|----------|-----------|-----------|-----|--------|---------|
| Healthy | OK | OK/SKIPPED | OK/INFO | OK | Daemon healthy (WebSocket responsive) |
| Degraded | INFO | OK | OK | WARNING | Daemon degraded (WebSocket failed, HTTP REST responsive) |
| Zombie | INFO | INFO | OK | ERROR | Zombie daemon (process alive but transports dead) |
| Stale PID | INFO | INFO | WARNING | WARNING | Daemon not running (stale PID file) |
| Not Running | INFO | INFO/SKIPPED | INFO | INFO | Daemon not running (optional for CLI usage) |

## RFC Compliance

### RFC-450: Daemon Communication Protocol

✓ WebSocket primary transport check
✓ HTTP REST secondary transport check
✓ Readiness state check (starting/warming/ready/degraded/error)
✓ WebSocket handshake protocol
✓ Removed deprecated Unix socket checks

### IG-258: Daemon Concurrent Performance Optimization

✓ Queue depth monitoring
✓ Input queue metrics (current/max/percent)
✓ Event queue metrics (max_depth/avg_depth/clients_near_capacity)
✓ Active threads check against max_concurrent_threads

## Performance Impact

**Minimal**: All checks use existing endpoints and methods:
- WebSocket connectivity: Port check (same as `SootheDaemon._is_port_live()`)
- HTTP REST calls: 2-second timeout, async execution
- Uptime: `psutil.Process.create_time()` - cached system call
- Queue metrics: Already collected by daemon, just exposed via HTTP REST

**Expected latency**: <1 second for full daemon category check (when daemon running)

## Future Enhancements

1. **Add WebSocket RPC for queue metrics** - More efficient than HTTP REST
2. **Add daemon memory/CPU metrics** - Using `psutil` for resource monitoring
3. **Add transport latency metrics** - WebSocket/HTTP REST response time tracking
4. **Add daemon error history** - Recent errors from daemon logs
5. **Add client health metrics** - Client connection stability, disconnect rate

## References

- RFC-450: Daemon Communication Protocol
- IG-258: Daemon Concurrent Performance Optimization
- RFC-000: System Conceptual Design
- Implementation Plan: `/Users/chenxm/.claude/plans/abundant-launching-elephant.md`

---

*Modernized daemon health checks with WebSocket + HTTP REST architecture, readiness states, and IG-258 queue monitoring.*