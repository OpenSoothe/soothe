# Multi-Transport Setup

Configure WebSocket and HTTP REST transports for the Soothe daemon.

## Transport Overview

The Soothe daemon supports two transport protocols:

| Transport | Status | Use Case | Performance |
|-----------|--------|----------|-------------|
| **WebSocket** | ✅ Default | All clients (CLI, TUI, web apps) | ~1-5ms latency |
| **HTTP REST** | ⚙️ Opt-in | CRUD operations, health checks | ~5-20ms latency |

All transports share the same:
- Authentication system
- Protocol layer
- Thread management
- Event streaming

## WebSocket (Default)

**Status**: ✅ Enabled by default

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
- Real-time bidirectional streaming
- CORS validation
- TLS support for remote connections
- Used by CLI, TUI, and web clients

**Note**: Authentication is handled by reverse proxy (see [Authentication Guide](authentication.md))

**Use When**:
- Running Soothe locally or remotely
- Using CLI or TUI clients
- Building web-based UIs (React, Vue, etc.)
- Remote monitoring dashboards
- Mobile app backends
- Desktop applications (Tauri, Electron)

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
soothed stop
soothed start
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

## Enabling Both Transports

You can enable both transports simultaneously:

```yaml
daemon:
  transports:
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
  - WebSocket: ✅ Enabled (ws://127.0.0.1:8765)
  - HTTP REST: ✅ Enabled (http://127.0.0.1:8766)
Active Threads: 3
```

## Security Model

### Localhost Connections

- **WebSocket localhost**: No built-in authentication
- **HTTP REST localhost**: No built-in authentication

### Remote Connections

**Important**: Soothe does not include built-in authentication. For remote access, always use a reverse proxy to handle:
- **Authentication**: API keys, JWT, OAuth, etc.
- **TLS/SSL**: HTTPS/WSS encryption
- **Rate limiting**: Prevent abuse
- **Request filtering**: Block malicious requests

See [Authentication Guide](authentication.md) for deployment patterns with nginx, Caddy, or Traefik.

## Performance Characteristics

| Transport | Latency | Throughput | Best For |
|-----------|---------|------------|----------|
| WebSocket | ~1-5ms | High | All clients, streaming |
| HTTP REST | ~5-20ms | Medium | CRUD operations |

## Related Guides

- [Authentication](authentication.md) - API keys and JWT
- [Daemon Management](daemon-management.md) - Server lifecycle
- [Configuration Guide](configuration.md) - Complete configuration reference
- [Troubleshooting](troubleshooting.md) - Connection issues