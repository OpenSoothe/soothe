# IG-504: Remove HTTP REST Channel and Related APIs

**Status**: Completed
**Created**: 2025-06-25
**Scope**: Remove HTTP REST transport channel from daemon and all related client code

---

## Summary

Remove the HTTP REST channel from soothe-daemon and all client code that uses HTTP REST to communicate with the daemon. WebSocket remains the sole bidirectional transport.

---

## Motivation

HTTP REST was added as an optional secondary transport (RFC-620) for:
- Health checks
- Autopilot REST API
- Cron REST API
- Memory profiling endpoints

WebSocket is the primary and required transport. HTTP REST adds maintenance overhead without essential functionality - all features can work through WebSocket messaging.

---

## Scope Analysis

### Files to DELETE

| Package | File | Reason |
|---------|------|--------|
| soothe-daemon | `channels/http_rest.py` | HTTP REST channel implementation |
| soothe-daemon | `tests/unit/channels/test_http_rest_cron.py` | Unit tests for HTTP REST |
| soothe-daemon | `tests/integration/core/test_http_rest_transport.py` | Integration tests |
| soothe-daemon | `tests/integration/daemon/test_daemon_http_protocol.py` | Protocol tests |
| soothe-daemon | `tests/integration/autopilot/test_autopilot_http_api.py` | Autopilot HTTP tests |
| soothe-cli | `runtime/cron_http.py` | Cron HTTP client |
| soothe-cli | `tests/unit/runtime/test_cron_http.py` | Cron HTTP tests |
| soothe-sdk | `client/autopilot_http.py` | Autopilot HTTP client and utilities |
| soothe-sdk | `tests/unit/client/test_autopilot_http.py` | Autopilot HTTP tests |

### Files to MODIFY

| Package | File | Changes |
|---------|------|---------|
| soothe-daemon | `config/models.py` | Remove HttpRestConfig class |
| soothe-daemon | `channel_manager.py` | Remove HTTP REST channel handling, unified_app logic |
| soothe-daemon | `health/checks/daemon_check.py` | Remove HTTP REST health checks |
| soothe-daemon | `cli.py` | Remove HTTP-specific shutdown helper |
| soothe-cli | `cli/commands/autopilot_cmd.py` | Remove HTTP client usage, may need WebSocket alternative |
| soothe-cli | `cli/commands/cron_cmd.py` | Remove HTTP client usage |
| soothe-cli | `tui/app/_model.py` | Remove HTTP client imports |
| soothe-cli | `cli/execution/daemon.py` | Remove HTTP client imports |
| soothe-sdk | `client/__init__.py` | Remove HTTP exports |
| soothe-sdk | `client/helpers.py` | Remove aiohttp shutdown helper |

### Files NOT to Modify (Different Purpose)

| Package | File | Reason |
|---------|------|--------|
| soothe | `toolkits/http_requests.py` | Agent HTTP tools for external APIs (not daemon transport) |
| soothe | `subagents/tacitus/polite_http.py` | HTTP client for external APIs (not daemon transport) |
| soothe | `tests/unit/toolkits/test_http_requests_toolkit.py` | Tests for agent HTTP tools |
| soothe | `tests/unit/subagents/tacitus/test_polite_http.py` | Tests for external HTTP client |
| soothe-daemon | `channels/msteams.py` | MS Teams channel uses BaseHTTPRequestHandler (separate) |

---

## Implementation Steps

### Phase 1: Remove HTTP REST Channel from Daemon

1. Delete `channels/http_rest.py`
2. Modify `channel_manager.py`:
   - Remove `HttpRestChannel` import and instantiation
   - Remove unified_app logic (FastAPI shared with HTTP)
   - Simplify to WebSocket-only listener
   - Remove autopilot_service, cron_service, memory_profiler dependencies
3. Modify `config/models.py`:
   - Remove `HttpRestConfig` class
   - Remove `http_rest` field from `TransportConfig` and `ChannelsConfig`
   - Remove `effective_http_rest_listen()` method
4. Delete HTTP-related test files in soothe-daemon

### Phase 2: Remove HTTP Clients from soothe-cli

1. Delete `runtime/cron_http.py`
2. Modify `cli/commands/cron_cmd.py`:
   - Remove CronHttpClient usage
   - Update CLI to use WebSocket or remove HTTP-dependent features
3. Modify `cli/commands/autopilot_cmd.py`:
   - Remove AutopilotHttpClient usage
   - Update CLI to use WebSocket or remove HTTP-dependent features
4. Modify `tui/app/_model.py`:
   - Remove HTTP client imports
5. Modify `cli/execution/daemon.py`:
   - Remove HTTP client imports

### Phase 3: Remove HTTP Clients from soothe-sdk

1. Delete `client/autopilot_http.py`
2. Modify `client/__init__.py`:
   - Remove `http_rest_url_from_config`, `ensure_http_rest_available` exports
3. Modify `client/helpers.py`:
   - Remove aiohttp shutdown helper (or keep for other purposes)

### Phase 4: Update Health Checks

1. Modify `health/checks/daemon_check.py`:
   - Remove `_check_http_rest_connectivity`, `_check_http_rest_status` functions
   - Remove HTTP-related health check logic

### Phase 5: Run Verification

1. Run `make lint` to ensure no syntax errors
2. Run `./scripts/verify_finally.sh` for full verification
3. Verify WebSocket-only mode works

---

## Design Decision: WebSocket Adaptation

### Autopilot/Cron Commands → WebSocket

Instead of removing CLI commands, adapt them to use WebSocket messaging:

**Approach**: Create a WebSocket-based command client that sends request messages and waits for response messages.

**Protocol Flow**:
1. CLI connects to daemon WebSocket
2. CLI sends command message: `{type: "autopilot_command", action: "submit", payload: {...}}`
3. Daemon processes via existing AutopilotService/CronService
4. Daemon sends response message: `{type: "autopilot_response", result: {...}}`
5. CLI disconnects

**New Components**:
- `soothe_sdk/client/ws_command_client.py` - WebSocket command client with request/response pattern
- Update CLI commands to use `WsCommandClient` instead of `AutopilotHttpClient`

### Memory Profiling → WebSocket

Add WebSocket message types for memory profiling:

**Message Types**:
- `{type: "memory_command", mode: "daemon"}` → `{type: "memory_response", stats: {...}}`

---

## Implementation Steps

### Phase 1: Remove HTTP REST Channel from Daemon

1. Delete `channels/http_rest.py`
2. Modify `channel_manager.py`:
   - Remove `HttpRestChannel` import and instantiation
   - Remove unified_app logic (FastAPI shared with HTTP)
   - Simplify to WebSocket-only listener
   - Keep autopilot_service, cron_service, memory_profiler (used by WebSocket)
3. Modify `config/models.py`:
   - Remove `HttpRestConfig` class
   - Remove `http_rest` field from `TransportConfig` and `ChannelsConfig`
   - Remove `effective_http_rest_listen()` method
4. Delete HTTP-related test files in soothe-daemon

### Phase 2: Create WebSocket Command Client (SDK)

1. Create `soothe_sdk/client/ws_command_client.py`:
   - `WsCommandClient` class with request/response pattern
   - Methods: `send_command(type, action, payload) -> response`
   - Timeout handling, connection management
2. Add command handlers to daemon WebSocket channel:
   - `autopilot_command` → AutopilotService
   - `cron_command` → CronService
   - `memory_command` → MemoryProfiler
3. Update `soothe_sdk/client/__init__.py` exports

### Phase 3: Adapt CLI Commands

1. Modify `cli/commands/autopilot_cmd.py`:
   - Replace `AutopilotHttpClient` with `WsCommandClient`
   - Same command interface, WebSocket transport
2. Modify `cli/commands/cron_cmd.py`:
   - Replace `CronHttpClient` with `WsCommandClient`
3. Delete old HTTP client files:
   - Delete `runtime/cron_http.py`
   - Delete `client/autopilot_http.py` (SDK)

### Phase 4: Update Health Checks

1. Modify `health/checks/daemon_check.py`:
   - Remove HTTP REST connectivity checks
   - Keep WebSocket checks (or add WebSocket-based health)

### Phase 5: Cleanup and Verification

1. Delete remaining HTTP files
2. Remove HTTP imports from all modified files
3. Update tests to use WebSocket mocking
4. Run `make lint` and `./scripts/verify_finally.sh`

---

## Breaking Changes

- Daemon configuration `transports.http_rest` section will be invalid (remove it)
- HTTP endpoints `/api/v1/*` will be unavailable

---

## Depends On

- WebSocket message protocol for command/response pattern

---

## Related

- RFC-620: Channel Architecture (defines HTTP REST channel)