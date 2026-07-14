# Implementation Guide: Unified Daemon Communication Protocol (RFC-400)

**RFC**: 0013
**Status**: Draft
**Created**: 2026-03-22
**Implementation Start**: TBD
**Estimated Duration**: 4 weeks (160 hours)

## Overview

This implementation guide translates RFC-400 (Unified Daemon Communication Protocol) into concrete implementation tasks for adding multi-transport support to the Soothe daemon.

### Goals

1. **Transport Independence**: Support Unix socket, WebSocket, and HTTP REST simultaneously
2. **Backward Compatibility**: Existing Unix socket clients continue working unchanged
3. **Security Tiers**: Appropriate authentication for each transport mode
4. **Clean Architecture**: Separation between transport, protocol, and business logic

### Non-Goals

- Remote deployment infrastructure (out of scope)
- Mobile/desktop client implementations (future work)
- Advanced authorization/permissions (future enhancement)

## Architecture

### Current Architecture (Unix Socket Only)

**Module Structure** (needs migration):
```
Current:  src/soothe/cli/daemon/   ❌ Nested under CLI
Target:   src/soothe/daemon/       ✅ Top-level module
```

**Architecture Flow**:
```
┌─────────────────────────────────────────┐
│         SootheDaemon (server.py)        │
│                                         │
│  asyncio.start_unix_server()            │
│         ↓                               │
│  _handle_client() → DaemonHandlersMixin │
│         ↓                               │
│  SootheRunner.astream()                 │
│         ↓                               │
│  Broadcast to _clients                  │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│         DaemonClient (client.py)        │
│                                         │
│  asyncio.open_unix_connection()         │
│         ↓                               │
│  send_input(), read_event()             │
└─────────────────────────────────────────┘
```

### Target Architecture (Multi-Transport)

**Module Structure**:
```
src/soothe/
├── daemon/              # Top-level daemon module
│   ├── server.py
│   ├── client.py
│   ├── protocol.py
│   ├── protocol_v2.py   # New: Abstract interfaces
│   ├── auth.py          # New: Authentication
│   ├── transport_manager.py  # New: Coordination
│   └── transports/      # New: Transport implementations
│       ├── base.py
│       ├── unix_socket.py
│       ├── websocket.py
│       └── http_rest.py
├── config/
│   ├── models.py
│   └── daemon_config.py  # New: Daemon configuration
└── cli/
    └── commands/
        └── auth_cmd.py   # New: API key management
```

**Architecture Flow**:
```
┌──────────────────────────────────────────────────────────────┐
│                    SootheDaemon (server.py)                  │
│                                                              │
│  TransportManager                                            │
│    ├─ UnixSocketTransport (existing)                        │
│    ├─ WebSocketTransport (new)                              │
│    └─ HttpRestTransport (new)                               │
│         ↓                                                    │
│  Unified Protocol Handler (protocol_v2.py)                  │
│         ↓                                                    │
│  DaemonHandlersMixin (existing, unchanged)                  │
│         ↓                                                    │
│  SootheRunner.astream()                                      │
│         ↓                                                    │
│  Broadcast to all transports                                 │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│                    DaemonClient (client.py)                  │
│                                                              │
│  Transport Selection (config-based)                          │
│    ├─ UnixSocketClient (existing)                           │
│    └─ WebSocketClient (new)                                 │
│         ↓                                                    │
│  send_input(), read_event() (same interface)               │
└──────────────────────────────────────────────────────────────┘
```

## Component Design

### 1. Transport Abstraction Layer

**Location**: `src/soothe/cli/daemon/transports/base.py`

**Purpose**: Define abstract interface for all transports

**Key Classes**:

```python
from abc import ABC, abstractmethod
from typing import Any, Callable, AsyncGenerator

class TransportServer(ABC):
    """Abstract base for transport servers."""

    @abstractmethod
    async def start(self, message_handler: Callable) -> None:
        """Start listening for connections."""
        pass

    @abstractmethod
    async def broadcast(self, message: dict) -> None:
        """Broadcast message to all connected clients."""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop the server and close all connections."""
        pass

    @property
    @abstractmethod
    def transport_type(self) -> str:
        """Return transport type identifier."""
        pass
```

**Dependencies**: None (abstract interface)

### 2. Unix Socket Transport

**Location**: `src/soothe/cli/daemon/transports/unix_socket.py`

**Purpose**: Wrap existing Unix socket implementation

**Implementation**:
- Extract Unix socket logic from `server.py` lines 73-108
- Implement `TransportServer` interface
- Maintain exact same behavior (10MB limit, newline-delimited JSON)

**Files Modified**:
- `src/soothe/cli/daemon/server.py` - Remove direct Unix socket creation
- `src/soothe/cli/daemon/client.py` - Use transport abstraction

**Backward Compatibility**: 100% - all existing tests must pass unchanged

### 3. WebSocket Transport

**Location**: `src/soothe/cli/daemon/transports/websocket.py`

**Purpose**: Implement WebSocket server for web/remote clients

**Key Features**:
- WebSocket server using `websockets` library
- Native text frames (no newline delimiter)
- CORS validation
- Authentication integration
- Rate limiting

**Configuration**:
```yaml
websocket:
  enabled: true
  host: "127.0.0.1"
  port: 8765
  tls_enabled: false
  cors_origins: ["http://localhost:*", "http://127.0.0.1:*"]
```

**Dependencies**: `websockets>=12.0`

### 4. HTTP REST Transport

**Location**: `src/soothe/cli/daemon/transports/http_rest.py`

**Purpose**: Implement REST API for CRUD operations

**Key Endpoints** (per RFC-400):
- `GET /api/v1/threads` - List threads
- `GET /api/v1/threads/{id}` - Get thread details
- `POST /api/v1/threads` - Create thread
- `DELETE /api/v1/threads/{id}` - Archive thread
- `POST /api/v1/threads/{id}/resume` - Resume thread
- `GET /api/v1/threads/{id}/messages` - Get messages
- `GET /api/v1/threads/{id}/artifacts` - List artifacts
- `GET /api/v1/config` - Get configuration
- `PUT /api/v1/config` - Update configuration
- `POST /api/v1/files/upload` - Upload file
- `GET /api/v1/files/{id}` - Download file
- `GET /api/v1/health` - Health check
- `GET /api/v1/status` - Daemon status
- `POST /api/v1/auth/api-keys` - Create API key
- `GET /api/v1/auth/api-keys` - List API keys
- `DELETE /api/v1/auth/api-keys/{id}` - Revoke API key

**Dependencies**: `fastapi>=0.104.0`, `uvicorn[standard]>=0.24.0`

### 5. Transport Manager

**Location**: `src/soothe/cli/daemon/transport_manager.py`

**Purpose**: Coordinate multiple transport servers

**Responsibilities**:
- Initialize enabled transports from config
- Broadcast events to all connected clients
- Manage client lifecycle
- Route incoming messages to unified handler

**Implementation**:
```python
class TransportManager:
    def __init__(self, config: DaemonConfig):
        self._transports: list[TransportServer] = []
        self._build_transports(config)

    async def start_all(self, handler: Callable) -> None:
        for transport in self._transports:
            await transport.start(handler)

    async def broadcast(self, message: dict) -> None:
        for transport in self._transports:
            await transport.broadcast(message)
```

### 6. Authentication System

**Location**: `src/soothe/cli/daemon/auth.py`

**Purpose**: Manage API keys and JWT tokens

**Components**:

1. **API Key Storage** (`~/.soothe/api_keys.json`):
```json
{
  "version": 1,
  "keys": [
    {
      "id": "key_001",
      "token": "sk_live_abc123...",
      "description": "Web UI",
      "created_at": "2026-03-19T00:00:00Z",
      "last_used_at": "2026-03-19T12:00:00Z",
      "permissions": ["read", "write"]
    }
  ]
}
```

2. **AuthManager Class**:
```python
class AuthManager:
    def validate_api_key(self, token: str) -> AuthContext | None:
        """Validate API key token."""

    def validate_jwt(self, token: str) -> AuthContext | None:
        """Validate JWT token."""

    def create_api_key(self, description: str, permissions: list[str]) -> dict:
        """Generate new API key."""

    def revoke_api_key(self, key_id: str) -> bool:
        """Revoke an API key."""
```

3. **Rate Limiter** (token bucket algorithm):
```python
class RateLimiter:
    def __init__(self, max_per_second: int = 10):
        self._tokens = max_per_second
        self._max = max_per_second
        self._last_refill = time.time()

    def consume(self) -> bool:
        """Return True if rate limit not exceeded."""
```

**Dependencies**: `pyjwt>=2.8.0` (optional, for JWT)

### 7. Protocol Handler

**Location**: `src/soothe/cli/daemon/protocol_v2.py`

**Purpose**: Message validation and transport-agnostic handling

**Key Features**:
- Message schema validation
- Reuse existing `protocol.py` for serialization
- Transport-specific framing strategies

**Message Validation**:
```python
def validate_message(msg: dict) -> list[str]:
    """Validate message structure. Returns list of errors."""
    errors = []
    if "type" not in msg:
        errors.append("Missing required field: type")
        return errors

    msg_type = msg["type"]
    if msg_type == "input" and "text" not in msg:
        errors.append("Input message missing required field: text")
    elif msg_type == "command" and "cmd" not in msg:
        errors.append("Command message missing required field: cmd")
    # ... other validations

    return errors
```

### 8. Configuration Schema

**Location**: `src/soothe/config/transport_config.py`

**Models**:

```python
from pydantic import BaseModel
from typing import Literal

class UnixSocketConfig(BaseModel):
    enabled: bool = True
    path: str = "~/.soothe/soothe.sock"

class WebSocketConfig(BaseModel):
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8765
    tls_enabled: bool = False
    tls_cert: str | None = None
    tls_key: str | None = None
    cors_origins: list[str] = ["http://localhost:*", "http://127.0.0.1:*"]

class HttpRestConfig(BaseModel):
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8766
    tls_enabled: bool = False
    tls_cert: str | None = None
    tls_key: str | None = None
    cors_origins: list[str] = ["http://localhost:*", "http://127.0.0.1:*"]
    require_auth_for_localhost: bool = False

class AuthConfig(BaseModel):
    enabled: bool = False
    mode: Literal["api_key", "jwt"] = "api_key"
    api_keys_file: str = "~/.soothe/api_keys.json"
    require_for_localhost: bool = False
    jwt_secret: str | None = None
    jwt_algorithm: str = "HS256"
    jwt_expiry_hours: int = 24

class TransportConfig(BaseModel):
    unix_socket: UnixSocketConfig = UnixSocketConfig()
    websocket: WebSocketConfig = WebSocketConfig()
    http_rest: HttpRestConfig = HttpRestConfig()

class DaemonConfig(BaseModel):
    transports: TransportConfig = TransportConfig()
    auth: AuthConfig = AuthConfig()
```

### 9. CLI Commands for Auth

**Location**: `src/soothe/cli/commands/auth_cmd.py`

**Commands**:

```bash
# Create API key
soothe auth create-key --description "Web UI" --permissions read,write

# List API keys
soothe auth list-keys

# Revoke API key
soothe auth revoke-key <key-id>
```

**Implementation**:
```python
import typer

app = typer.Typer()

@app.command("create-key")
def create_key(description: str, permissions: str = "read,write"):
    """Create a new API key."""
    auth = AuthManager()
    key = auth.create_api_key(description, permissions.split(","))
    typer.echo(f"API Key: {key['token']}")
    typer.echo(f"Key ID: {key['key_id']}")

@app.command("list-keys")
def list_keys():
    """List all API keys."""
    auth = AuthManager()
    keys = auth.list_api_keys()
    for key in keys:
        typer.echo(f"{key['id']}: {key['description']}")

@app.command("revoke-key")
def revoke_key(key_id: str):
    """Revoke an API key."""
    auth = AuthManager()
    auth.revoke_api_key(key_id)
    typer.echo(f"Revoked key {key_id}")
```

## Implementation Tasks

### Phase 0: Module Migration (Day 1, 8h)

**Task 0.1: Move Daemon Module** (2h)
- [ ] Move `src/soothe/cli/daemon/` → `src/soothe/daemon/`
- [ ] Verify all files moved correctly
- [ ] Update `__init__.py` exports

**Task 0.2: Create Daemon Configuration** (2h)
- [ ] Create `src/soothe/config/daemon_config.py`
- [ ] Define `TransportConfig`, `AuthConfig`, `DaemonConfig`
- [ ] Add `daemon: DaemonConfig` field to `SootheConfig` in `models.py`
- [ ] Write unit tests for config validation

**Task 0.3: Update Imports** (3h)
- [ ] Update all imports from `soothe.daemon` → `soothe.daemon`
- [ ] Files to update:
  - `src/soothe/cli/execution/daemon_runner.py`
  - `src/soothe/cli/tui/app.py`
  - `src/soothe/cli/commands/server_cmd.py`
  - `src/soothe/cli/commands/thread_cmd.py`
  - `tests/unit_tests/test_cli_daemon.py`
  - All other references (grep for `soothe.daemon`)

**Task 0.4: Verification** (1h)
- [ ] Run all tests to verify no regressions
- [ ] Verify daemon starts correctly
- [ ] Verify client connects correctly

**Phase 0 Exit Criteria**:
- ✅ Module moved to `soothe.daemon`
- ✅ All imports updated
- ✅ `SootheConfig.daemon` field available with defaults
- ✅ All tests passing

### Phase 1: Protocol Abstraction (Week 1, 40h)

**Task 1.1: Configuration Schema** (4h)
- [ ] Create `src/soothe/config/transport_config.py`
- [ ] Define all configuration models
- [ ] Add to `SootheConfig` in `models.py`
- [ ] Write unit tests for config validation

**Task 1.2: Abstract Transport Interface** (6h)
- [ ] Create `src/soothe/cli/daemon/transports/base.py`
- [ ] Define `TransportServer` abstract base class
- [ ] Define `TransportClient` abstract base class
- [ ] Write unit tests for interface contracts

**Task 1.3: Message Validation** (4h)
- [ ] Create `src/soothe/cli/daemon/protocol_v2.py`
- [ ] Implement `validate_message()` function
- [ ] Add error handling for invalid messages
- [ ] Write unit tests for all message types

**Task 1.4: Unix Socket Transport** (8h)
- [ ] Create `src/soothe/cli/daemon/transports/unix_socket.py`
- [ ] Extract Unix socket logic from `server.py`
- [ ] Implement `TransportServer` interface
- [ ] Maintain backward compatibility
- [ ] Verify all existing tests pass

**Task 1.5: Transport Manager** (6h)
- [ ] Create `src/soothe/cli/daemon/transport_manager.py`
- [ ] Implement transport coordination logic
- [ ] Add configuration-based initialization
- [ ] Write unit tests for manager

**Task 1.6: Update Daemon Server** (8h)
- [ ] Modify `server.py` to use `TransportManager`
- [ ] Remove direct Unix socket creation
- [ ] Integrate with existing `DaemonHandlersMixin`
- [ ] Verify all existing tests pass

**Task 1.7: Integration Testing** (4h)
- [ ] Create `tests/integration_tests/test_transport_abstraction.py`
- [ ] Test Unix socket still works
- [ ] Test configuration loading
- [ ] Test transport lifecycle

**Phase 1 Exit Criteria**:
- ✅ All existing tests pass
- ✅ Unix socket behavior unchanged
- ✅ Transport abstraction tested in isolation
- ✅ Configuration schema validated

### Phase 2: WebSocket Implementation (Week 2, 40h)

**Task 2.1: WebSocket Transport Server** (10h)
- [ ] Add `websockets>=12.0` to `pyproject.toml`
- [ ] Create `src/soothe/cli/daemon/transports/websocket.py`
- [ ] Implement `TransportServer` interface
- [ ] Handle WebSocket framing (no newline delimiter)
- [ ] Implement connection lifecycle
- [ ] Write unit tests

**Task 2.2: Authentication System** (12h)
- [ ] Create `src/soothe/cli/daemon/auth.py`
- [ ] Implement `AuthManager` class
- [ ] Add API key storage and validation
- [ ] Add JWT token validation (optional)
- [ ] Add rate limiting
- [ ] Write unit tests

**Task 2.3: CORS Validation** (4h)
- [ ] Add CORS origin validation to WebSocket transport
- [ ] Implement pattern matching for allowed origins
- [ ] Write unit tests for CORS

**Task 2.4: WebSocket Client** (6h)
- [ ] Update `client.py` to support WebSocket
- [ ] Add transport selection logic
- [ ] Implement WebSocket connection and framing
- [ ] Write unit tests

**Task 2.5: Integration Testing** (8h)
- [ ] Create `tests/integration_tests/test_websocket_transport.py`
- [ ] Test WebSocket connection and streaming
- [ ] Test authentication flow
- [ ] Test rate limiting
- [ ] Test CORS validation

**Phase 2 Exit Criteria**:
- ✅ WebSocket transport connects and streams events
- ✅ Authentication works for API keys and JWT
- ✅ Rate limiting prevents abuse
- ✅ CORS validation blocks unauthorized origins

### Phase 3: HTTP REST API (Week 3, 40h)

**Task 3.1: HTTP REST Transport Server** (12h)
- [ ] Add `fastapi>=0.104.0` and `uvicorn[standard]>=0.24.0` to dependencies
- [ ] Create `src/soothe/cli/daemon/transports/http_rest.py`
- [ ] Implement all REST endpoints per RFC-400
- [ ] Add OpenAPI documentation
- [ ] Write unit tests

**Task 3.2: Auth CLI Commands** (6h)
- [ ] Create `src/soothe/cli/commands/auth_cmd.py`
- [ ] Implement `create-key`, `list-keys`, `revoke-key` commands
- [ ] Integrate with main CLI
- [ ] Write unit tests

**Task 3.3: File Operations** (8h)
- [ ] Implement file upload endpoint
- [ ] Implement file download endpoint
- [ ] Implement file storage and retrieval
- [ ] Write unit tests

**Task 3.4: Integration Testing** (10h)
- [ ] Create `tests/integration_tests/test_http_rest_transport.py`
- [ ] Test all REST endpoints
- [ ] Test file upload/download
- [ ] Test API key management
- [ ] Test authentication

**Task 3.5: Documentation** (4h)
- [ ] Generate OpenAPI docs
- [ ] Test Swagger UI at `/docs`
- [ ] Test ReDoc at `/redoc`

**Phase 3 Exit Criteria**:
- ✅ All RFC-400 REST endpoints implemented
- ✅ API key CLI commands work
- ✅ OpenAPI docs accessible
- ✅ File upload/download functional

### Phase 4: Testing & Documentation (Week 4, 40h)

**Task 4.1: Comprehensive Unit Tests** (12h)
- [ ] Achieve 95% coverage on auth module
- [ ] Achieve 90% coverage on transport modules
- [ ] Achieve 90% coverage on protocol module
- [ ] Add edge case tests

**Task 4.2: Integration Tests** (12h)
- [ ] Create `tests/integration_tests/test_multi_transport_daemon.py`
- [ ] Test daemon with all transports enabled
- [ ] Test backward compatibility
- [ ] Test multi-client scenarios

**Task 4.3: Performance Benchmarking** (6h)
- [ ] Benchmark Unix socket latency (<1ms)
- [ ] Benchmark WebSocket latency (<5ms localhost)
- [ ] Benchmark REST API latency (<10ms)
- [ ] Profile broadcasting performance

**Task 4.4: Documentation** (6h)
- [ ] Write migration guide
- [ ] Write security best practices
- [ ] Update RFC-400 status to "Implemented"
- [ ] Create user-facing docs

**Task 4.5: Security Review** (4h)
- [ ] Security checklist validation
- [ ] Secure defaults verification
- [ ] Authentication testing
- [ ] Rate limiting verification

**Phase 4 Exit Criteria**:
- ✅ All tests passing with 90%+ coverage
- ✅ Documentation reviewed and complete
- ✅ Security audit checklist passed
- ✅ Performance meets targets

## Testing Strategy

### Unit Tests

**Coverage Targets**:
- `auth.py`: 95%
- `protocol_v2.py`: 90%
- `transports/unix_socket.py`: 90%
- `transports/websocket.py`: 90%
- `transports/http_rest.py`: 90%
- `transport_manager.py`: 90%

**Test Categories**:
1. **Configuration validation** - Valid/invalid configs
2. **Message validation** - All message types and error cases
3. **Transport lifecycle** - Start, stop, connection handling
4. **Authentication** - API keys, JWT, rate limiting
5. **CORS validation** - Allowed/blocked origins

### Integration Tests

**Test Scenarios**:

1. **Multi-Transport Daemon**:
   - Start daemon with Unix socket + WebSocket + REST
   - Connect multiple clients simultaneously
   - Broadcast events to all clients
   - Verify each client receives events

2. **Backward Compatibility**:
   - Start daemon with new architecture
   - Connect with existing Unix socket client
   - Execute all existing client operations
   - Verify behavior unchanged

3. **WebSocket End-to-End**:
   - Connect via WebSocket
   - Authenticate with API key
   - Send input, receive events
   - Test rate limiting
   - Test CORS validation

4. **REST API Operations**:
   - Create thread via REST
   - Upload file via REST
   - List threads, messages, artifacts
   - Manage API keys via CLI

5. **Authentication Flow**:
   - Create API key
   - Authenticate WebSocket with key
   - Access REST API with key
   - Revoke key and verify access denied

### Performance Tests

**Benchmarks**:
```python
# Unix socket latency
async def test_unix_socket_latency():
    client = UnixSocketClient()
    start = time.perf_counter()
    await client.send_input("test")
    event = await client.read_event()
    latency_ms = (time.perf_counter() - start) * 1000
    assert latency_ms < 1.0  # <1ms

# WebSocket latency (localhost)
async def test_websocket_latency_localhost():
    client = WebSocketClient("ws://localhost:8765")
    start = time.perf_counter()
    await client.send_input("test")
    event = await client.read_event()
    latency_ms = (time.perf_counter() - start) * 1000
    assert latency_ms < 5.0  # <5ms

# REST API latency
async def test_rest_latency():
    async with httpx.AsyncClient() as client:
        start = time.perf_counter()
        response = await client.get("http://localhost:8766/api/v1/health")
        latency_ms = (time.perf_counter() - start) * 1000
        assert latency_ms < 10.0  # <10ms
```

## Security Checklist

### Authentication

- [ ] API keys use cryptographically secure random generation
- [ ] JWT tokens have reasonable expiry times (24h default)
- [ ] Authentication errors don't leak sensitive information
- [ ] Rate limiting prevents brute force attacks
- [ ] API keys can be revoked immediately

### Transport Security

- [ ] Unix socket uses secure file permissions (0o600)
- [ ] WebSocket remote requires TLS (wss://)
- [ ] CORS validation prevents unauthorized origins
- [ ] Input size limits prevent memory exhaustion (10MB)
- [ ] Message validation prevents injection attacks

### Configuration

- [ ] Secure defaults (WebSocket disabled, auth optional for localhost)
- [ ] TLS certificate validation when enabled
- [ ] CORS origins configurable
- [ ] Rate limits configurable

### Logging

- [ ] Authentication events logged (success and failure)
- [ ] Security errors logged with context
- [ ] Rate limit violations logged
- [ ] No sensitive data in logs (tokens redacted)

## Migration Guide

### For Users

**Enabling WebSocket (localhost)**:
```yaml
# ~/.soothe/config.yaml
daemon:
  transports:
    websocket:
      enabled: true
      host: "127.0.0.1"
      port: 8765
```

**Creating API Keys**:
```bash
# Create API key for web UI
soothe auth create-key --description "Web UI"

# List keys
soothe auth list-keys

# Revoke when done
soothe auth revoke-key key_001
```

**Connecting via WebSocket**:
```javascript
const ws = new WebSocket("ws://localhost:8765");
ws.onopen = () => {
  ws.send(JSON.stringify({type: "input", text: "hello"}));
};
ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  console.log(msg);
};
```

### For Developers

**Using Transport Abstraction**:
```python
from soothe.daemon.transports import UnixSocketTransport, WebSocketTransport

# Create transports
unix = UnixSocketTransport(config.unix_socket)
ws = WebSocketTransport(config.websocket)

# Start both
manager = TransportManager([unix, ws])
await manager.start_all(message_handler)

# Broadcast to all
await manager.broadcast({"type": "event", "data": {...}})
```

**Adding New Transport**:
```python
class CustomTransport(TransportServer):
    async def start(self, handler: Callable) -> None:
        # Implementation

    async def broadcast(self, message: dict) -> None:
        # Implementation

    async def stop(self) -> None:
        # Implementation
```

### 8. Daemon Configuration Schema

**Location**: `src/soothe/config/daemon_config.py`

**Purpose**: Dedicated configuration for daemon and transports

**Models**:

```python
from pydantic import BaseModel, Field
from typing import Literal

class UnixSocketConfig(BaseModel):
    """Unix domain socket configuration.

    Args:
        enabled: Enable Unix socket server.
        path: Socket file path.
    """
    enabled: bool = True
    path: str = "~/.soothe/soothe.sock"

class WebSocketConfig(BaseModel):
    """WebSocket server configuration.

    Args:
        enabled: Enable WebSocket server.
        host: Bind address.
        port: Listen port.
        tls_enabled: Enable TLS encryption.
        tls_cert: TLS certificate path.
        tls_key: TLS key path.
        cors_origins: Allowed CORS origins.
    """
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8765
    tls_enabled: bool = False
    tls_cert: str | None = None
    tls_key: str | None = None
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:*", "http://127.0.0.1:*"]
    )

class HttpRestConfig(BaseModel):
    """HTTP REST API configuration.

    Args:
        enabled: Enable HTTP REST server.
        host: Bind address.
        port: Listen port.
        tls_enabled: Enable TLS encryption.
        tls_cert: TLS certificate path.
        tls_key: TLS key path.
        cors_origins: Allowed CORS origins.
        require_auth_for_localhost: Require auth for localhost.
    """
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8766
    tls_enabled: bool = False
    tls_cert: str | None = None
    tls_key: str | None = None
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:*", "http://127.0.0.1:*"]
    )
    require_auth_for_localhost: bool = False

class TransportConfig(BaseModel):
    """Transport layer configuration.

    Args:
        unix_socket: Unix socket configuration.
        websocket: WebSocket configuration.
        http_rest: HTTP REST configuration.
    """
    unix_socket: UnixSocketConfig = Field(default_factory=UnixSocketConfig)
    websocket: WebSocketConfig = Field(default_factory=WebSocketConfig)
    http_rest: HttpRestConfig = Field(default_factory=HttpRestConfig)

class AuthConfig(BaseModel):
    """Authentication configuration.

    Args:
        enabled: Enable authentication.
        mode: Authentication mode (api_key or jwt).
        require_for_localhost: Require auth for localhost connections.
        api_keys_file: API keys storage path.
        jwt_secret: JWT signing secret (from env).
        jwt_algorithm: JWT signing algorithm.
        jwt_expiry_hours: JWT token expiry duration.
    """
    enabled: bool = False
    mode: Literal["api_key", "jwt"] = "api_key"
    require_for_localhost: bool = False
    api_keys_file: str = "~/.soothe/api_keys.json"
    jwt_secret: str | None = None
    jwt_algorithm: str = "HS256"
    jwt_expiry_hours: int = 24

class DaemonConfig(BaseModel):
    """Daemon configuration for multi-transport support.

    Args:
        transports: Transport layer configuration.
        auth: Authentication configuration.
    """
    transports: TransportConfig = Field(default_factory=TransportConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
```

**Integration in `models.py`**:
```python
# src/soothe/config/models.py
from soothe.config.daemon_config import DaemonConfig

class SootheConfig(BaseModel):
    """Main Soothe configuration."""
    # ... existing fields ...

    # Daemon configuration (new)
    daemon: DaemonConfig = Field(default_factory=DaemonConfig)
```

### Required (Already Installed)
- `asyncio` - Async I/O
- `pydantic` - Configuration models

### New Dependencies

**WebSocket**:
- `websockets>=12.0` - WebSocket server and client

**HTTP REST**:
- `fastapi>=0.104.0` - REST framework
- `uvicorn[standard]>=0.24.0` - ASGI server

**Authentication** (Optional):
- `pyjwt>=2.8.0` - JWT token handling

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Breaking Unix socket compatibility | Medium | High | Extensive testing, 100% feature parity |
| Security vulnerabilities | Medium | High | Security review, secure defaults, rate limiting |
| Performance degradation | Low | Medium | Async I/O, efficient broadcasting, benchmarks |
| Configuration complexity | Low | Low | Secure defaults, clear documentation |
| Dependency conflicts | Low | Low | Pin versions, test with existing deps |

## Success Criteria

### Functional Requirements

- [ ] Unix socket transport works exactly as before
- [ ] WebSocket transport connects and streams events
- [ ] HTTP REST API implements all RFC-400 endpoints
- [ ] Authentication system works for API keys and JWT
- [ ] Rate limiting prevents abuse
- [ ] CORS validation blocks unauthorized origins
- [ ] Multiple transports run simultaneously

### Non-Functional Requirements

- [ ] Unix socket latency <1ms (no regression)
- [ ] WebSocket latency <5ms (localhost)
- [ ] REST API latency <10ms
- [ ] Code coverage ≥90%
- [ ] All tests passing
- [ ] Documentation complete

### Backward Compatibility

- [ ] Existing Unix socket clients work unchanged
- [ ] Existing tests pass without modification
- [ ] Configuration migration not required (new features opt-in)

## References

- [RFC-400: Unified Daemon Communication Protocol](../specs/RFC-400-daemon-communication.md)
- [RFC-500: CLI TUI Architecture Design](../specs/RFC-500-cli-tui-architecture.md)
- [Implementation Plan](../../.claude/plans/jolly-growing-moon.md)

---

**Implementation Status**: Not Started
**Next Steps**: Begin Phase 1 - Protocol Abstraction