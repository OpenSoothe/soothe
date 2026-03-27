# IG-047: Daemon Integration Test Coverage Enhancement

**Status**: Draft
**Created**: 2026-03-23
**RFC References**: RFC-0013, RFC-0015, RFC-0017
**Implementation Priority**: P0 (Critical)

## Executive Summary

This implementation guide addresses critical test coverage gaps in Soothe's daemon protocol implementation. While existing tests provide solid coverage of basic thread CRUD operations, major gaps exist in security, error handling, multi-transport scenarios, and event protocol validation.

**Deliverables**:
- 5 new integration test files
- 28 new test cases
- Coverage improvement: Security 5%→70%, Error Handling 20%→75%, Event Protocol 10%→60%

**Estimated Effort**: 3-5 days

## Current Coverage Analysis

### Existing Test Files

| File | LOC | Transport | Tests | Focus |
|------|-----|-----------|-------|-------|
| `test_daemon_domainsocket_protocol.py` | 294 | Unix Socket | 2 | Thread lifecycle, multi-turn conversation |
| `test_daemon_http_protocol.py` | 384 | HTTP REST | 5 | REST endpoints, thread CRUD, contract tests |
| `test_daemon_websocket_protocol.py` | 320 | WebSocket | 4 | Message protocol, thread operations, validation |

**Total**: 11 daemon protocol integration tests

### Coverage Matrix

#### Well-Covered Operations ✅

| Operation | Unix Socket | HTTP REST | WebSocket |
|-----------|-------------|-----------|-----------|
| Thread create | ✅ | ✅ | ✅ |
| Thread list | ✅ | ✅ | ✅ |
| Thread get | ✅ | ✅ | ✅ |
| Thread resume | ✅ | ✅ | ✅ |
| Thread messages | ✅ | ✅ | ✅ |
| Thread artifacts | ✅ | ✅ | ✅ |
| Thread archive | ✅ | ✅ | ✅ |
| Thread delete | ✅ | ✅ | ✅ |
| Transport lifecycle | ✅ | ✅ | ✅ |
| Broadcast events | ✅ | N/A | ✅ |

#### Missing Coverage ❌

**Security & Authentication**:
- Unix socket file permissions (0o600)
- CORS origin validation
- Message size limit (10MB)
- Rate limiting
- PID lock enforcement

**Error Handling**:
- Malformed JSON messages
- Missing required fields
- Invalid message types
- Thread not found errors
- Client disconnection during stream
- Concurrent client connections
- Daemon shutdown during operation

**Event Protocol (RFC-0015)**:
- Event type validation (80+ types)
- Event model schema validation
- Event registry dispatch
- Tool events (dynamic naming)
- Subagent events

**Multi-Transport & Multi-Threading**:
- Multiple transports enabled simultaneously
- Multi-client broadcast across transports
- Thread resumption from disk after restart (RFC-0017)
- Concurrent thread execution
- Thread isolation guarantees

## Implementation Approach

### Phase 1: Multi-Transport Testing

**File**: `tests/integration/test_daemon_multi_transport.py`

**Objective**: Validate daemon behavior with all transports enabled simultaneously.

**Test Cases**:

1. **test_all_transports_simultaneous_lifecycle**
   - Start daemon with Unix socket, WebSocket, and HTTP REST enabled
   - Verify all transports start successfully
   - Verify client can connect to each transport
   - Verify graceful shutdown stops all transports

2. **test_multi_transport_broadcast**
   - Connect 3 clients (one per transport)
   - Execute query on one client
   - Verify events broadcast to all clients across all transports
   - Verify client count aggregation

3. **test_multi_transport_thread_operations**
   - Create thread via Unix socket
   - Access thread via HTTP REST
   - Resume thread via WebSocket
   - Verify thread state consistent across transports

4. **test_multi_transport_client_count**
   - Connect multiple clients to each transport
   - Verify `client_count` aggregates across all transports
   - Verify disconnections update count correctly

5. **test_multi_transport_shutdown_order**
   - Start daemon with all transports
   - Initiate shutdown during active query
   - Verify transports shut down in correct order
   - Verify all clients receive shutdown notification

**Implementation Notes**:
- Use `_build_daemon_config()` helper with all transports enabled
- Allocate ephemeral ports for WebSocket/HTTP to avoid conflicts
- Reuse existing transport client patterns from current tests

### Phase 2: Security Testing

**File**: `tests/integration/test_daemon_security.py`

**Objective**: Validate security features and access controls.

**Test Cases**:

1. **test_unix_socket_permissions**
   - Start daemon with Unix socket
   - Check socket file permissions (should be 0o600)
   - Verify owner-only access
   - Verify socket location in user home directory

2. **test_websocket_cors_validation**
   - Configure WebSocket with allowed origins
   - Connect with valid origin → should succeed
   - Connect with invalid origin → should reject (close code 1008)
   - Test pattern matching (glob syntax)

3. **test_message_size_limit**
   - Send message larger than 10MB
   - Verify error response with appropriate error code
   - Verify daemon remains stable
   - Test exact boundary (10MB - 1 byte should succeed)

4. **test_rate_limiting** (if implemented)
   - Configure rate limiting in daemon config
   - Send messages rapidly exceeding limit
   - Verify `RATE_LIMITED` error response
   - Verify cooldown period

5. **test_pid_lock_enforcement**
   - Start daemon instance 1
   - Attempt to start daemon instance 2
   - Verify second instance fails with PID lock error
   - Verify first instance remains operational

**Implementation Notes**:
- Use `stat.S_IMODE()` to check Unix socket permissions
- Use `websockets.connect()` with custom `origin` header for CORS tests
- Generate large payload with `"x" * (10 * 1024 * 1024 + 1)`
- Create second daemon fixture with same config for PID lock test

### Phase 3: Error Handling Testing

**File**: `tests/integration/test_daemon_error_handling.py`

**Objective**: Validate error handling and edge cases.

**Test Cases**:

1. **test_malformed_json_handling**
   - Send invalid JSON to Unix socket
   - Send invalid JSON to WebSocket
   - Send invalid JSON to HTTP REST
   - Verify error responses with `INVALID_JSON` code
   - Verify daemon remains operational

2. **test_missing_required_fields**
   - Send message without `type` field
   - Send `input` message without `text` field
   - Send `thread_get` without `thread_id` field
   - Verify error responses with `INVALID_MESSAGE` code
   - Verify error details contain missing field info

3. **test_invalid_message_type**
   - Send message with unknown `type` field
   - Verify error response with `UNKNOWN_MESSAGE_TYPE` code
   - Verify daemon continues processing subsequent messages

4. **test_thread_not_found_error**
   - Attempt to get non-existent thread
   - Attempt to resume non-existent thread
   - Attempt to archive non-existent thread
   - Verify error responses with `THREAD_NOT_FOUND` code
   - Verify error details contain thread_id

5. **test_client_disconnection_during_stream**
   - Start long-running query
   - Disconnect client mid-stream
   - Verify daemon continues execution
   - Verify other clients still receive events
   - Verify resources cleaned up

6. **test_concurrent_client_connections**
   - Connect 10 clients simultaneously to same transport
   - Send requests from all clients
   - Verify all clients receive responses
   - Verify no race conditions or deadlocks

7. **test_daemon_shutdown_during_operation**
   - Start long-running query
   - Send shutdown signal during execution
   - Verify graceful shutdown
   - Verify thread state preserved
   - Verify clients receive shutdown notification

**Implementation Notes**:
- Use `json.dumps()` with malformed strings for JSON tests
- Use `asyncio.gather()` for concurrent client tests
- Use `asyncio.wait_for()` with timeout for disconnection tests
- Reuse `_await_event_type()` helper for event validation

### Phase 4: Event Protocol Testing

**File**: `tests/integration/test_daemon_event_protocol.py`

**Objective**: Validate RFC-0015 event protocol compliance.

**Test Cases**:

1. **test_lifecycle_events**
   - Create thread → verify `soothe.lifecycle.thread.created` event
   - Start query → verify `soothe.lifecycle.thread.started` event
   - Complete query → verify `soothe.lifecycle.thread.saved` event
   - Archive thread → verify `soothe.lifecycle.thread.ended` event
   - Validate event structure (type, timestamp, thread_id)

2. **test_protocol_events**
   - Execute query triggering context projection
   - Verify `soothe.protocol.context.projected` event
   - Execute query triggering memory recall
   - Verify `soothe.protocol.memory.recalled` event
   - Execute planning query
   - Verify `soothe.cognition.plan.created` event
   - Validate event payload structure per RFC-0015

3. **test_tool_events**
   - Execute tool (e.g., file read)
   - Verify `soothe.tool.read_file.started` event
   - Verify `soothe.tool.read_file.completed` event
   - Execute failing tool
   - Verify `soothe.tool.{name}.failed` event
   - Validate dynamic event type naming

4. **test_subagent_events**
   - Trigger subagent (e.g., browser, research)
   - Verify `soothe.subagent.browser.step` events
   - Verify `soothe.subagent.research.web_search` events
   - Validate event payload contains subagent-specific data
   - Verify event hierarchy (subagent prefix)

5. **test_error_events**
   - Trigger error during execution
   - Verify `soothe.error.runtime` event
   - Validate error event structure (type, message, traceback)
   - Verify error events don't crash daemon

6. **test_event_registry_dispatch**
   - Collect all emitted events
   - Verify each event type is registered
   - Verify domain classification (lifecycle/protocol/tool/subagent/error)
   - Verify verbosity metadata

**Implementation Notes**:
- Use event capture helper to collect all events during query
- Import event models from `src/soothe/core/events.py`
- Use `EventRegistry` for validation
- Focus on high-value event types (don't test all 80+)

### Phase 5: Thread Recovery Testing

**File**: `tests/integration/test_daemon_thread_recovery.py`

**Objective**: Validate RFC-0017 thread resumption and recovery.

**Test Cases**:

1. **test_thread_resume_from_disk**
   - Create thread and execute query
   - Stop daemon (preserving thread state)
   - Start new daemon instance
   - Resume thread by ID
   - Verify conversation history intact
   - Verify thread can continue conversation

2. **test_thread_recovery_missing_metadata**
   - Create thread
   - Corrupt durability metadata (delete/corrupt file)
   - Resume thread
   - Verify recovery from run artifacts
   - Verify graceful degradation with warning

3. **test_concurrent_thread_execution**
   - Start daemon with `max_concurrent_threads = 3`
   - Launch 5 threads simultaneously
   - Verify 3 execute concurrently, 2 queue
   - Verify all complete successfully
   - Verify thread isolation

4. **test_thread_cancellation**
   - Start long-running query in thread
   - Send `/cancel` command
   - Verify thread execution stops
   - Verify resources cleaned up
   - Verify thread state saved

5. **test_thread_isolation**
   - Create 2 threads concurrently
   - Execute queries with different contexts
   - Verify context/memory don't leak between threads
   - Verify thread-local state isolation

**Implementation Notes**:
- Use durable backend (JsonDurability or RocksDBDurability)
- Manually corrupt durability files for recovery test
- Use `asyncio.create_task()` for concurrent thread execution
- Configure daemon with `max_concurrent_threads` setting

## Test Patterns and Utilities

### Existing Helpers (Reuse)

From `tests/integration/test_daemon_domainsocket_protocol.py`:

```python
def _build_daemon_config(
    unix_socket_path: str,
    websocket_port: Optional[int] = None,
    http_port: Optional[int] = None,
) -> SootheConfig:
    """Build isolated daemon config."""

def _force_isolated_home() -> Path:
    """Force SOOTHE_HOME to isolated directory."""

async def _await_event_type(
    client,
    event_type: str,
    timeout: float = 10.0
) -> dict:
    """Poll for specific event type."""

async def _await_status_state(
    client,
    state: str,
    timeout: float = 10.0
) -> dict:
    """Wait for daemon to reach specific state."""

async def _await_thread_user_messages(
    thread_id: str,
    expected_count: int,
    config: SootheConfig,
    timeout: float = 10.0,
) -> list:
    """Validate message persistence."""
```

### New Helpers (Create)

```python
def _alloc_ephemeral_port() -> int:
    """Allocate available TCP port."""
    import socket
    with socket.socket() as s:
        s.bind(('', 0))
        return s.getsockname()[1]

async def _collect_events_during_query(
    client,
    query: str,
    event_types: Optional[Set[str]] = None,
) -> List[dict]:
    """Collect all events during query execution."""
    events = []
    # ... implementation

def _corrupt_durability_file(thread_id: str, config: SootheConfig):
    """Corrupt thread durability file for recovery tests."""
    # ... implementation

async def _connect_multiple_clients(
    transport: str,
    count: int,
    config: SootheConfig,
) -> List:
    """Connect multiple clients to same transport."""
    # ... implementation
```

### Fixture Patterns

```python
@pytest.fixture
async def multi_transport_daemon(test_config, tmp_path):
    """Daemon with all transports enabled."""
    unix_path = str(tmp_path / "soothe.sock")
    ws_port = _alloc_ephemeral_port()
    http_port = _alloc_ephemeral_port()

    config = _build_daemon_config(
        unix_socket_path=unix_path,
        websocket_port=ws_port,
        http_port=http_port,
    )

    daemon = SootheDaemon(config)
    await daemon.start()

    yield {
        "daemon": daemon,
        "unix_path": unix_path,
        "ws_port": ws_port,
        "http_port": http_port,
        "config": config,
    }

    await daemon.stop()
```

## Verification Checklist

### Pre-Commit

- [ ] All tests pass locally
- [ ] Code follows project style (ruff format)
- [ ] Type hints on all public functions
- [ ] No bare `except:` clauses
- [ ] Google-style docstrings

### Test Execution

```bash
# Run all new integration tests
pytest tests/integration/test_daemon_multi_transport.py -v
pytest tests/integration/test_daemon_security.py -v
pytest tests/integration/test_daemon_error_handling.py -v
pytest tests/integration/test_daemon_event_protocol.py -v
pytest tests/integration/test_daemon_thread_recovery.py -v

# Run all daemon tests
pytest tests/integration/test_daemon_*.py -v

# Run with coverage
pytest tests/integration/test_daemon_*.py \
  --cov=src/soothe/daemon \
  --cov-report=html \
  --cov-report=term-missing
```

### Coverage Validation

After implementation, verify coverage improvements:

| Category | Before | Target | After |
|----------|--------|--------|-------|
| Core Operations | 85% | 90% | ___% |
| Security | 5% | 70% | ___% |
| Error Handling | 20% | 75% | ___% |
| Event Protocol | 10% | 60% | ___% |
| Multi-Transport | 0% | 80% | ___% |
| Thread Recovery | 0% | 70% | ___% |

### RFC Compliance

- [ ] RFC-0013: All protocol message types tested
- [ ] RFC-0013: All transports tested simultaneously
- [ ] RFC-0013: Security features validated
- [ ] RFC-0015: Event types validated
- [ ] RFC-0015: Event models validated
- [ ] RFC-0017: Thread resumption tested
- [ ] RFC-0017: Thread recovery tested
- [ ] RFC-0017: Multi-threading tested

## Success Criteria

1. ✅ All 28 new test cases pass
2. ✅ Coverage targets met (see table above)
3. ✅ No test flakiness (run 3x to verify)
4. ✅ All tests use real SootheRunner (no mocks for daemon)
5. ✅ Multi-transport scenarios validated
6. ✅ Security features tested
7. ✅ Error handling comprehensive
8. ✅ Event protocol compliance verified
9. ✅ Thread recovery validated
10. ✅ Documentation updated (this guide)

## Related Documents

- RFC-0013: Unified Daemon Communication Protocol
- RFC-0015: Progress Event Protocol
- RFC-0017: Unified Thread Management Architecture
- `tests/integration/README.md`: Integration test overview
- `src/soothe/daemon/server.py`: Main daemon implementation
- `src/soothe/core/events.py`: Event models and registry

## Conclusion

This implementation guide provides a comprehensive roadmap for closing test coverage gaps in Soothe's daemon protocol implementation. By adding 28 targeted test cases across 5 new test files, we will achieve:

- **Security**: 70% coverage (up from 5%)
- **Error Handling**: 75% coverage (up from 20%)
- **Event Protocol**: 60% coverage (up from 10%)
- **Multi-Transport**: 80% coverage (up from 0%)
- **Thread Recovery**: 70% coverage (up from 0%)

These improvements will ensure production reliability and RFC compliance across all daemon protocol features.
