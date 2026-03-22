# Multi-Transport Setup

Configure Unix Socket, WebSocket, and HTTP REST transports for the Soothe daemon.

## Transport Overview

The Soothe daemon supports three transport protocols simultaneously:

| Transport | Status | Use Case | Performance |
|-----------|--------|----------|-------------|
| **Unix Socket** | ✅ Default | Local CLI/TUI clients | ~0.1ms latency |
| **WebSocket** | ⚙️ Opt-in | Web applications, remote clients | ~1-5ms latency |
| **HTTP REST** | ⚙️ Opt-in | CRUD operations, file management | ~5-20ms latency |

All transports share the same:
- Authentication system
- Protocol layer
- Thread management
- Event streaming

## Unix Socket (Default)

**Status**: ✅ Enabled by default

**Configuration**:
```yaml
daemon:
  transports:
    unix_socket:
      enabled: true
      path: "~/.soothe/soothe.sock"
```

**Features**:
- Local IPC via Unix domain socket
- No authentication required (filesystem permissions)
- Sub-millisecond latency (~0.1ms)
- Used by CLI and TUI clients
- Backward compatible with existing clients

**Use When**:
- Running Soothe locally
- Using CLI or TUI clients
- Maximum performance needed

## WebSocket (Opt-in)

**Status**: ❌ Disabled by default

**Configuration**:
```yaml
daemon:
  transports:
    websocket:
      enabled: true
      host: "127.0.0.1"
      port: 8765
      tls_enabled: false
      cors_origins: ["http://localhost:*", "http://127.0.0.1:*"]
```

**Features**:
- Real-time streaming for web applications
- Optional authentication (API key or JWT)
- CORS validation
- TLS support for remote connections
- Rate limiting to prevent abuse

**Use When**:
- Building web-based UIs (React, Vue, etc.)
- Remote monitoring dashboards
- Mobile app backends
- Desktop applications (Tauri, Electron)

### Enable WebSocket

1. **Update configuration** (`~/.soothe/config.yml`):
```yaml
daemon:
  transports:
    websocket:
      enabled: true
      host: "127.0.0.1"
      port: 8765
```

2. **Restart daemon**:
```bash
soothe server stop
soothe server start
```

3. **Verify**:
```bash
soothe server status
# Should show: WebSocket: ✅ Enabled (ws://127.0.0.1:8765)
```

### Web Application Integration

**JavaScript Client**:
```javascript
// Connect to WebSocket
const ws = new WebSocket("ws://localhost:8765");

ws.onopen = () => {
  // Authenticate (if enabled)
  ws.send(JSON.stringify({
    type: "auth",
    token: "sk_live_abc123..."
  }));

  // Send input
  ws.send(JSON.stringify({
    type: "input",
    text: "Analyze the codebase"
  }));
};

ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  if (msg.type === "event") {
    console.log("Received event:", msg.data);
  }
};
```

## HTTP REST API (Opt-in)

**Status**: ❌ Disabled by default

**Configuration**:
```yaml
daemon:
  transports:
    http_rest:
      enabled: true
      host: "127.0.0.1"
      port: 8766
      require_auth_for_localhost: false
```

**Features**:
- RESTful API for CRUD operations
- Thread management endpoints
- File upload/download
- Configuration management
- Health checks and monitoring
- OpenAPI documentation (Swagger UI and ReDoc)

**Use When**:
- Building integrations with other tools
- Implementing custom clients
- Performing file operations
- Checking system health

### Enable HTTP REST

1. **Update configuration**:
```yaml
daemon:
  transports:
    http_rest:
      enabled: true
      host: "127.0.0.1"
      port: 8766
```

2. **Restart daemon**:
```bash
soothe server stop
soothe server start
```

### Key Endpoints

**Thread Management**:
```bash
# List threads
GET http://localhost:8766/api/v1/threads

# Create thread
POST http://localhost:8766/api/v1/threads

# Get messages
GET http://localhost:8766/api/v1/threads/{id}/messages
```

**File Operations**:
```bash
# Upload file
POST http://localhost:8766/api/v1/files/upload

# Download file
GET http://localhost:8766/api/v1/files/{id}
```

**Health Check**:
```bash
GET http://localhost:8766/api/v1/health
```

**Authentication**:
```bash
# Create API key (requires authentication)
POST http://localhost:8766/api/v1/auth/api-keys
```

### API Documentation

When enabled, visit:
- **Swagger UI**: http://localhost:8766/docs
- **ReDoc**: http://localhost:8766/redoc

### Using the REST API

**List Threads**:
```bash
curl -H "Authorization: Bearer sk_live_abc123..." \
  http://localhost:8766/api/v1/threads
```

**Send Input**:
```bash
curl -X POST \
  -H "Authorization: Bearer sk_live_abc123..." \
  -H "Content-Type: application/json" \
  -d '{"text": "Analyze the data"}' \
  http://localhost:8766/api/v1/threads/abc123/input
```

## Enabling Multiple Transports

You can enable all three transports simultaneously:

```yaml
daemon:
  transports:
    unix_socket:
      enabled: true
      path: "~/.soothe/soothe.sock"

    websocket:
      enabled: true
      host: "127.0.0.1"
      port: 8765
      cors_origins: ["http://localhost:3000"]

    http_rest:
      enabled: true
      host: "127.0.0.1"
      port: 8766
```

**Status Output**:
```
Daemon Status: running
PID: 12345
Uptime: 2 hours
Transports:
  - Unix Socket: ✅ Enabled (~/.soothe/soothe.sock)
  - WebSocket: ✅ Enabled (ws://127.0.0.1:8765)
  - HTTP REST: ✅ Enabled (http://127.0.0.1:8766)
Active Threads: 3
```

## Security Model

### Localhost Connections

- **Unix Socket**: No authentication (filesystem permissions)
- **WebSocket localhost**: Optional authentication (configurable)
- **HTTP REST localhost**: Optional authentication (configurable)

### Remote Connections

- **WebSocket**: Authentication required, TLS mandatory
- **HTTP REST**: Authentication required
- **CORS**: Strict origin validation
- **Rate Limiting**: Prevents abuse (10 messages/second default)

## Performance Characteristics

| Transport | Latency | Throughput | Best For |
|-----------|---------|------------|----------|
| Unix Socket | ~0.1ms | Highest | Local CLI/TUI |
| WebSocket | ~1-5ms | High | Web apps, streaming |
| HTTP REST | ~5-20ms | Medium | CRUD operations |

## Related Guides

- [Authentication](authentication.md) - API keys and JWT
- [Daemon Management](daemon-management.md) - Server lifecycle
- [Configuration Guide](configuration.md) - Complete configuration reference
- [Troubleshooting](troubleshooting.md) - Connection issues