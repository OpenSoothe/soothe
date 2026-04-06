# Authentication

**Important**: Soothe does not include built-in authentication. All authentication and authorization is handled by external services (reverse proxies, API gateways, etc.).

## Authentication Architecture

As of RFC-400 and RFC-402, Soothe follows a "security by delegation" model:

- **No built-in authentication**: Soothe daemon does not validate API keys, JWT tokens, or user credentials
- **No authorization layer**: All clients that can reach the daemon are trusted
- **External security**: Authentication, TLS, rate limiting handled by reverse proxy

## Transport Security

### Unix Socket (Local)

**Security Model**: OS-level filesystem permissions

```bash
# Socket location
~/.soothe/soothe.sock

# Permissions: user-only by default (mode 0600)
# Only the user running Soothe can connect
```

**Best for**:
- Local CLI/TUI clients
- Single-user development environments
- Maximum performance (~0.1ms latency)

**No additional security needed**: Filesystem permissions provide isolation.

### WebSocket and HTTP REST (Remote)

**Security Model**: Reverse proxy handles all security

```
Client → Reverse Proxy (Auth + TLS) → Soothe Daemon
```

**Reverse proxy responsibilities**:
- **TLS termination**: HTTPS/WSS encryption
- **Authentication**: API keys, JWT, OAuth, etc.
- **Authorization**: Role-based access control
- **Rate limiting**: Prevent abuse
- **Request filtering**: Block malicious requests

**Soothe daemon**: Trusts all connections from reverse proxy

## Deployment Patterns

### Pattern 1: Local Development (No Auth)

```
┌─────────────┐
│ CLI/TUI     │
│ (Unix Socket)│
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Soothe     │
│  Daemon     │
└─────────────┘
```

**Configuration**:
```yaml
daemon:
  transports:
    unix_socket:
      enabled: true
      path: "~/.soothe/soothe.sock"
```

**Security**: Filesystem permissions (user-only access)

### Pattern 2: Production Deployment (Auth via Reverse Proxy)

```
┌──────────────┐
│ Web/Mobile   │
│   Client     │
└──────┬───────┘
       │ HTTPS/WSS
       ▼
┌──────────────┐
│  Reverse     │  ← Authentication, TLS, Rate Limiting
│  Proxy       │
└──────┬───────┘
       │ HTTP/WS (trusted)
       ▼
┌──────────────┐
│  Soothe      │  ← No auth (trusts reverse proxy)
│  Daemon      │
└──────────────┘
```

**Recommended reverse proxies**:
- **nginx**: Industry standard, highly configurable
- **Caddy**: Automatic HTTPS, simple config
- **Traefik**: Cloud-native, auto-discovery
- **Cloudflare Tunnel**: Zero-trust access, no open ports

## Example: nginx Configuration

### WebSocket + HTTP REST with API Key Auth

**nginx.conf**:
```nginx
# WebSocket endpoint
upstream soothe_ws {
    server 127.0.0.1:8765;
}

# HTTP REST endpoint
upstream soothe_http {
    server 127.0.0.1:8766;
}

# WebSocket server
server {
    listen 8765 ssl;
    server_name soothe.example.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        # Validate API key
        if ($http_x_api_key = "") {
            return 401 "API key required";
        }

        proxy_pass http://soothe_ws;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }
}

# HTTP REST server
server {
    listen 8766 ssl;
    server_name soothe.example.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        # Validate API key
        if ($http_x_api_key = "") {
            return 401 "API key required";
        }

        proxy_pass http://soothe_http;
        proxy_set_header Host $host;
    }
}
```

**Soothe config**:
```yaml
daemon:
  transports:
    unix_socket:
      enabled: true
    websocket:
      enabled: true
      host: "127.0.0.1"  # Only accessible to nginx
      port: 8765
    http_rest:
      enabled: true
      host: "127.0.0.1"  # Only accessible to nginx
      port: 8766
```

**Client usage**:
```bash
# WebSocket
wss://soothe.example.com:8765
Headers: X-API-Key: your-api-key

# HTTP REST
curl -H "X-API-Key: your-api-key" \
  https://soothe.example.com:8766/api/v1/threads
```

## Example: Caddy Configuration

### Automatic HTTPS with JWT Auth

**Caddyfile**:
```
soothe.example.com {
    # Automatic HTTPS via Let's Encrypt
    encode gzip

    # JWT authentication (using caddy-auth-jwt plugin)
    jwt {
        secret YOUR_JWT_SECRET
        signalg HS256
    }

    # WebSocket proxy
    handle /ws {
        reverse_proxy localhost:8765
    }

    # HTTP REST proxy
    handle /api/* {
        reverse_proxy localhost:8766
    }
}
```

**Soothe config**:
```yaml
daemon:
  transports:
    websocket:
      enabled: true
      host: "127.0.0.1"
      port: 8765
    http_rest:
      enabled: true
      host: "127.0.0.1"
      port: 8766
```

## CORS Configuration

Configure allowed origins for WebSocket (still needed even with reverse proxy):

```yaml
daemon:
  transports:
    websocket:
      cors_origins:
        - "https://app.example.com"
        - "https://soothe.example.com"
```

## Security Best Practices

1. **Never expose daemon directly**: Always use reverse proxy for remote access
2. **Enable TLS**: All remote connections should use HTTPS/WSS
3. **Strong authentication**: Use proven auth solutions (OAuth, OIDC, API keys)
4. **Rate limiting**: Prevent abuse at the reverse proxy level
5. **Network isolation**: Daemon should only listen on localhost
6. **Monitor access**: Log all requests at reverse proxy level
7. **Regular updates**: Keep reverse proxy and auth libraries updated

## Migration from Built-in Auth

If you were using the removed `soothe auth` commands:

1. **Remove auth config** from Soothe:
   ```yaml
   # Remove this section
   daemon:
     auth:
       enabled: true
       mode: "api_key"
   ```

2. **Choose a reverse proxy** (nginx, Caddy, Traefik)

3. **Configure authentication** at reverse proxy level

4. **Update client code** to send auth headers to reverse proxy

5. **Verify**: Test that unauthenticated requests are rejected

## Related Guides

- [Multi-Transport Setup](multi-transport.md) - Enable WebSocket and HTTP REST
- [Configuration Guide](configuration.md) - Daemon configuration
- [Troubleshooting](troubleshooting.md) - Connection issues
- [RFC-400](../specs/RFC-400-daemon-communication.md) - Daemon communication protocol
- [RFC-402](../specs/RFC-402-unified-thread-management.md) - Unified thread management