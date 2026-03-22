# Authentication

Manage API keys and JWT authentication for WebSocket and HTTP REST transports.

## Authentication Overview

The Soothe daemon supports two authentication modes for WebSocket and HTTP REST:
- **API Key Authentication**: Simple token-based authentication
- **JWT Authentication**: Token-based authentication with expiration

**Unix Socket**: No authentication required (filesystem permissions provide security)

## API Key Authentication

### Create API Key

Create a new API key:

```bash
soothe auth create-key --description "Web UI" --permissions read,write
```

**Output**:
```
API Key: sk_live_abc123def456ghi789
Key ID: key_001
Description: Web UI
Permissions: read, write
Created: 2026-03-22 10:00:00

Save this key securely - it will not be shown again.
```

**Options**:
- `--description` - Human-readable description
- `--permissions` - Comma-separated permissions: `read`, `write`

### Permissions

| Permission | Access |
|------------|--------|
| `read` | Read threads, messages, configuration |
| `write` | Create threads, send input, modify configuration |

### List API Keys

View all API keys:

```bash
soothe auth list-keys
```

**Output**:
```
Key ID    Description    Permissions    Created              Last Used
key_001   Web UI         read, write    2026-03-22 10:00    2026-03-22 14:30
key_002   Mobile App     read           2026-03-21 09:15    2026-03-21 18:45
```

### Revoke API Key

Revoke an API key:

```bash
soothe auth revoke-key key_001
```

**Output**:
```
API key 'key_001' revoked successfully
```

### API Key Storage

API keys are stored in `~/.soothe/api_keys.json`:
- Keys are hashed for security
- Original keys are not stored (only shown once)
- Keys can be revoked immediately

## Using API Keys

### WebSocket Authentication

```javascript
const ws = new WebSocket("ws://localhost:8765");

ws.onopen = () => {
  // Authenticate
  ws.send(JSON.stringify({
    type: "auth",
    token: "sk_live_abc123..."
  }));
};
```

### HTTP REST Authentication

```bash
# Using Authorization header
curl -H "Authorization: Bearer sk_live_abc123..." \
  http://localhost:8766/api/v1/threads

# Using X-API-Key header (alternative)
curl -H "X-API-Key: sk_live_abc123..." \
  http://localhost:8766/api/v1/threads
```

## JWT Authentication

### Configuration

Enable JWT authentication:

```yaml
daemon:
  auth:
    enabled: true
    mode: "jwt"
    jwt_secret: "${JWT_SECRET}"
    jwt_algorithm: "HS256"
    jwt_expiry_hours: 24
```

**Environment Variable**:
```bash
export JWT_SECRET=your-secret-key-here
```

### Generate JWT Token

JWT tokens are generated externally (e.g., by your authentication service):

```python
import jwt
import datetime

token = jwt.encode({
    'sub': 'user_123',
    'permissions': ['read', 'write'],
    'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=24)
}, 'your-secret-key-here', algorithm='HS256')
```

### Use JWT Token

**WebSocket**:
```javascript
ws.send(JSON.stringify({
  type: "auth",
  token: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}));
```

**HTTP REST**:
```bash
curl -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..." \
  http://localhost:8766/api/v1/threads
```

## Security Model

### Localhost Connections

**Unix Socket**:
- No authentication required
- Security via filesystem permissions (`~/.soothe/soothe.sock`)
- Only accessible by the user running Soothe

**WebSocket/HTTP localhost**:
- Optional authentication (configurable)
- Set `require_auth_for_localhost: true` to enforce

```yaml
daemon:
  auth:
    require_for_localhost: true
```

### Remote Connections

For remote access, authentication is **mandatory**:

**WebSocket**:
- Authentication required
- TLS mandatory (`tls_enabled: true`)
- CORS validation enforced

**HTTP REST**:
- Authentication required
- HTTPS recommended (configure reverse proxy)

### CORS Configuration

Configure allowed origins for WebSocket:

```yaml
daemon:
  transports:
    websocket:
      cors_origins:
        - "http://localhost:3000"
        - "http://127.0.0.1:3000"
        - "https://myapp.example.com"
```

## Rate Limiting

Prevent abuse with rate limiting:

```yaml
daemon:
  auth:
    rate_limit:
      enabled: true
      requests_per_second: 10
      burst_size: 20
```

**Default**: 10 messages/second with burst of 20

## Example: Web Application Integration

### Backend Configuration

**`~/.soothe/config.yml`**:
```yaml
daemon:
  transports:
    unix_socket:
      enabled: true
    websocket:
      enabled: true
      host: "127.0.0.1"
      port: 8765
      cors_origins: ["http://localhost:3000"]
    http_rest:
      enabled: true
      host: "127.0.0.1"
      port: 8766
  auth:
    enabled: true
    mode: "api_key"
```

### Frontend Integration

**React Example**:
```javascript
import { useState, useEffect } from 'react';

function App() {
  const [ws, setWs] = useState(null);
  const [messages, setMessages] = useState([]);

  useEffect(() => {
    const socket = new WebSocket('ws://localhost:8765');

    socket.onopen = () => {
      // Authenticate
      socket.send(JSON.stringify({
        type: 'auth',
        token: 'sk_live_abc123...'
      }));
    };

    socket.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.type === 'event') {
        setMessages(prev => [...prev, msg.data]);
      }
    };

    setWs(socket);

    return () => socket.close();
  }, []);

  const sendMessage = (text) => {
    ws.send(JSON.stringify({
      type: 'input',
      text
    }));
  };

  return (
    <div>
      {/* Your UI */}
    </div>
  );
}
```

## Best Practices

1. **Rotate Keys Regularly**: Create new keys and revoke old ones periodically
2. **Use Minimal Permissions**: Only grant `write` permission when needed
3. **Store Keys Securely**: Never commit API keys to version control
4. **Use Environment Variables**: Store secrets in `.env` files or secret managers
5. **Enable TLS**: Always use TLS for remote connections
6. **Monitor Usage**: Check `last_used` timestamps for anomalies

## Related Guides

- [Multi-Transport Setup](multi-transport.md) - Enable WebSocket and HTTP REST
- [Configuration Guide](configuration.md) - Authentication configuration
- [Troubleshooting](troubleshooting.md) - Authentication errors