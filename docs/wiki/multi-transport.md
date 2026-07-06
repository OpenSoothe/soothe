---
title: "WebSocket Transport Setup"
parent: Wiki
nav_order: 4.3
description: Configure the WebSocket transport for the Soothe daemon — currently the only supported transport.
---

# WebSocket Transport Setup

Configure the WebSocket transport for the Soothe daemon.

> **Note**: WebSocket is currently the only supported transport. HTTP REST transport was removed in 0.6.x. Future transports may be added, but none are planned for the near term.

## Transport Overview

The Soothe daemon uses WebSocket as its sole transport protocol:

| Transport | Status | Use Case | Performance |
|-----------|--------|----------|-------------|
| **WebSocket** | ✅ Default (only) | All clients (CLI, TUI, web apps) | ~1-5ms latency |

All clients share the same:
- Authentication system (via reverse proxy)
- Protocol layer
- Thread management
- Event streaming

## WebSocket (Default)

**Status**: ✅ Enabled by default

**Configuration** (`~/.soothe/config/daemon.yml`):
```yaml
transports:
  websocket:
    enabled: true
    host: "127.0.0.1"
    port: 8765
    tls_enabled: false
    tls_cert: null
    tls_key: null
    cors_origins: ["http://localhost:*", "http://127.0.0.1:*"]
    max_frame_size: 10485760
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

## TLS Configuration

Enable TLS for direct remote connections (without reverse proxy):

```yaml
# ~/.soothe/config/daemon.yml
transports:
  websocket:
    enabled: true
    host: "0.0.0.0"
    port: 8765
    tls_enabled: true
    tls_cert: "/path/to/cert.pem"
    tls_key: "/path/to/key.pem"
```

**Note**: For production, prefer a reverse proxy (nginx, Caddy) for TLS termination. See [Authentication Guide](authentication.md).

## CORS Configuration

Configure allowed origins for browser-based clients:

```yaml
# ~/.soothe/config/daemon.yml
transports:
  websocket:
    cors_origins:
      - "http://localhost:3000"
      - "https://app.example.com"
```

## Status Output

```bash
soothed status
```

**Output**:
```
Daemon Status: running
PID: 12345
Uptime: 2 hours
Transports:
  - WebSocket: ✅ Enabled (ws://127.0.0.1:8765)
Active Threads: 3
```

## Security Model

### Localhost Connections

- **WebSocket localhost**: No built-in authentication; bind to 127.0.0.1 for local-only access

### Remote Connections

**Important**: Soothe does not include built-in authentication. For remote access, always use a reverse proxy to handle:
- **Authentication**: API keys, JWT, OAuth, etc.
- **TLS/SSL**: HTTPS/WSS encryption
- **Rate limiting**: Prevent abuse
- **Request filtering**: Block malicious requests

See [Authentication Guide](authentication.md) for deployment patterns with nginx, Caddy, or Traefik.
