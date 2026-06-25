# Identity Service Design Draft

> AKSK-based authentication with JWT tokens for soothe-daemon

**Date**: 2026-06-25
**Status**: Draft for review
**Target**: RFC formalization (Platonic Coding Phase 1)

---

## Overview

Add identity service to soothe-daemon providing:

- **AKSK authentication**: Admin-provisioned access key + secret key
- **JWT tokens**: Access token (short-lived) + refresh token (medium-lived)
- **External channel support**: Map platform sender_id to soothe user_id
- **Workspace isolation**: User context for existing workspace resolution

**Scope**: WebSocket channel + external channels (Telegram, DingTalk, Feishu, etc.)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        soothe-daemon                             │
├─────────────────────────────────────────────────────────────────┤
│  Daemon CLI Commands (admin only)                                │
│  ├── soothed identity create-user                                │
│  ├── soothed identity create-aksk --user <user> [--expiry-days]  │
│  ├── soothed identity revoke-aksk --aksk-id <id>                 │
│  ├── soothed identity revoke-token --jti <id>                    │
│  ├── soothed identity map-external --channel --sender-id --user  │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                     IdentityProtocol                             │
│  (packages/soothe/src/soothe/core/security/)                     │
├─────────────────────────────────────────────────────────────────┤
│  Methods:                                                        │
│  ├── create_user(user_id) → User                                 │
│  ├── create_aksk(user_id, expiry_days) → AKSK                    │
│  ├── authenticate(aksk) → (access_token, refresh_token)          │
│  ├── validate_token(token) → TokenClaims | None                  │
│  ├── refresh_token(refresh_token) → (access_token, refresh_token)│
│  ├── revoke_token(jti)                                           │
│  ├── revoke_aksk(aksk_id)                                        │
│  ├── map_external_identity(channel, sender_id, user_id)          │
│  ├── resolve_identity(channel, sender_id) → user_id | None       │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│              Existing PersistenceProtocol                         │
│  (SQLite or Postgres, shared with loop state)                    │
├─────────────────────────────────────────────────────────────────┤
│  Tables: users, aksk_pairs, issued_tokens,                       │
│          external_identity_mappings, revoked_jtis                │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                     IdentityMiddleware                           │
│  (First middleware in stack, before PolicyMiddleware)            │
├─────────────────────────────────────────────────────────────────┤
│  For WebSocket: validate auth_token → user_id                    │
│  For External Channels: resolve sender_id → user_id              │
│  Result: ThreadState.user_id populated                           │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│              Workspace Isolation (existing)                      │
│  $SOOTHE_HOME/data/workspaces/<user>/ws_<hash>                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Data Models

### User

```python
@dataclass
class User:
    user_id: str          # Unique identifier
    created_at: datetime
    metadata: dict        # Optional: display_name, email, etc.
```

### AKSK Pair

```python
@dataclass
class AKSKPair:
    aksk_id: str          # UUID, internal reference
    user_id: str          # Owner
    access_key: str       # Public: "AK-{16 chars}"
    secret_key_hash: str  # Hashed (SHA-256)
    created_at: datetime
    expires_at: datetime | None  # Configurable, None = never
    revoked: bool
    revoked_at: datetime | None
```

**Format**:
- Access key: `AK-x7k2m9p4q1w8` (16 chars)
- Secret key: `SK-a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6` (32 chars)

### Token Claims

```python
@dataclass
class TokenClaims:
    jti: str              # JWT ID (UUID) for revocation
    user_id: str
    aksk_id: str          # Source AKSK
    token_type: str       # "access" | "refresh"
    issued_at: datetime
    expires_at: datetime
```

**JWT Payload**:
```json
{
  "jti": "550e8400-e29b-41d4-a716-446655440000",
  "sub": "alice",
  "aksk_id": "abc123",
  "typ": "access",
  "iat": 1700000000,
  "exp": 1700003600
}
```

### External Identity Mapping

```python
@dataclass
class ExternalIdentityMapping:
    mapping_id: str
    channel: str          # "telegram", "feishu", etc.
    sender_id: str        # Platform user ID
    user_id: str          # soothe user_id
    created_at: datetime
```

---

## Database Schema

Identity tables coexist with loop state tables in existing persistence database:

```sql
CREATE TABLE users (
    user_id TEXT PRIMARY KEY,
    created_at TIMESTAMP NOT NULL,
    metadata JSON
);

CREATE TABLE aksk_pairs (
    aksk_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(user_id),
    access_key TEXT NOT NULL UNIQUE,
    secret_key_hash TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    expires_at TIMESTAMP,
    revoked BOOLEAN DEFAULT FALSE,
    revoked_at TIMESTAMP
);

CREATE TABLE issued_tokens (
    jti TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    aksk_id TEXT NOT NULL REFERENCES aksk_pairs(aksk_id),
    token_type TEXT NOT NULL,
    issued_at TIMESTAMP NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    revoked BOOLEAN DEFAULT FALSE,
    revoked_at TIMESTAMP
);

CREATE TABLE external_identity_mappings (
    mapping_id TEXT PRIMARY KEY,
    channel TEXT NOT NULL,
    sender_id TEXT NOT NULL,
    user_id TEXT NOT NULL REFERENCES users(user_id),
    created_at TIMESTAMP NOT NULL,
    UNIQUE(channel, sender_id)
);

CREATE TABLE revoked_jtis (
    jti TEXT PRIMARY KEY,
    revoked_at TIMESTAMP NOT NULL,
    reason TEXT NOT NULL
);

-- Indexes
CREATE INDEX idx_aksk_user ON aksk_pairs(user_id);
CREATE INDEX idx_tokens_user ON issued_tokens(user_id);
CREATE INDEX idx_mappings_channel_sender ON external_identity_mappings(channel, sender_id);
```

---

## Authentication Flows

### WebSocket AKSK Authentication

```
1. Admin provisions AKSK:
   soothed identity create-aksk --user alice --expiry-days 90

2. Client authenticates via WebSocket:
   { "type": "auth", "access_key": "AK-x7k2...", "secret_key": "SK-a1b2..." }

3. IdentityService:
   - Lookup by access_key
   - Verify secret_key against hash (constant-time)
   - Check AKSK not expired/revoked
   - Generate access_token (JWT, 1 hour)
   - Generate refresh_token (JWT, 7 days)
   - Store JTIs in issued_tokens

4. Response to client:
   {
     "type": "auth_response",
     "success": true,
     "access_token": "...",
     "refresh_token": "...",
     "expires_in": 3600,
     "user_id": "alice"
   }

5. Client uses token in subsequent requests:
   { "type": "loop_new", "auth_token": "<access_token>", "payload": {...} }

6. IdentityMiddleware validates token:
   - Verify JWT signature + expiry
   - Check JTI not in revoked_jtis
   - Populate ThreadState.user_id

7. Token refresh:
   { "type": "auth_refresh", "refresh_token": "<refresh_jwt>" }
   - Returns new tokens
   - Revokes old JTIs
```

### External Channel Resolution

```
1. Admin maps external identity:
   soothed identity map-external --channel telegram --sender-id 12345 --user alice

2. Message arrives from Telegram:
   - TelegramChannel receives message
   - Extracts sender_id = "12345"

3. IdentityMiddleware resolves:
   - resolve_identity("telegram", "12345") → "alice"
   - ThreadState.user_id = "alice"
   - Workspace isolation applies

4. Unmapped sender policy (configurable):
   - "anonymous": user_id = None (existing behavior)
   - "reject": reject message
   - "use_sender_id": user_id = "telegram:12345"
```

### Two Auth Layers for External Channels

| Layer | Purpose | Managed By |
|-------|---------|------------|
| Platform bot credentials | Daemon authenticates TO platform | Channel config (app_id, app_secret, bot_token) |
| User identity mapping | Platform user → soothe user_id | IdentityService (external_identity_mappings) |

---

## WebSocket Message Types

```json
// Auth request
{ "type": "auth", "access_key": "AK-...", "secret_key": "SK-..." }

// Auth response (success)
{
  "type": "auth_response",
  "success": true,
  "access_token": "...",
  "refresh_token": "...",
  "expires_in": 3600,
  "user_id": "alice"
}

// Auth response (failure)
{
  "type": "auth_response",
  "success": false,
  "error": "invalid_credentials" | "aksk_expired" | "aksk_revoked"
}

// Refresh request
{ "type": "auth_refresh", "refresh_token": "..." }

// Refresh response
{
  "type": "auth_refresh_response",
  "success": true,
  "access_token": "...",
  "refresh_token": "...",
  "expires_in": 3600
}

// Token validation error
{
  "type": "error",
  "error": "token_expired" | "token_revoked" | "token_invalid",
  "message": "...",
  "action": "refresh_token" | "re_auth"
}
```

---

## Configuration

**Location**: daemon_config.yml (not core config.yml)

```yaml
identity:
  # Disabled by default for backward compatibility
  enabled: false

  # Token settings
  tokens:
    access_token_expiry_hours: 1
    refresh_token_expiry_days: 7
    jwt_signing_key: "${SOOTHE_JWT_KEY}"

  # AKSK defaults
  aksk:
    default_expiry_days: 90
    max_expiry_days: 365

  # External channel policy
  unmapped_sender_policy: "anonymous"  # anonymous | reject | use_sender_id

  # Storage uses existing persistence config (no separate storage section)
```

**JWT Key Resolution** (when enabled):
1. Environment variable: `SOOTHE_JWT_KEY`
2. Config value: `identity.tokens.jwt_signing_key`
3. Auto-generated: `$SOOTHE_HOME/.jwt_key` (first startup)

**Backward Compatibility**:
- `enabled = false` (default): Existing auth behavior unchanged
- WebSocket without auth_token: Falls back to message-provided user_id
- External channels without mapping: Falls back to sender_id or anonymous

---

## Middleware Integration

**Order**: IdentityMiddleware first, before PolicyMiddleware

```
WebSocket message received
    ↓
IdentityMiddleware
    ↓ (validate token / resolve external identity)
ThreadState.user_id populated
    ↓
PolicyMiddleware
    ↓ (uses user_id for permission context)
Request Handler
    ↓
Workspace Resolution ($SOOTHE_HOME/data/workspaces/<user>/ws_<hash>)
```

**IdentityMiddleware behavior**:
- WebSocket: Extract `auth_token`, validate JWT, populate user_id
- External channel: Get channel + sender_id, resolve via mapping
- Disabled: Skip middleware, continue with existing behavior

**ThreadState extension**:
```python
class ThreadState:
    workspace: Path | None
    loop_id: str | None
    user_id: str | None      # NEW: from IdentityMiddleware
    aksk_id: str | None      # NEW: for audit tracking
```

---

## CLI Commands

```bash
# User management
soothed identity create-user --user <user_id>
soothed identity list-users
soothed identity delete-user --user <user_id>

# AKSK management
soothed identity create-aksk --user <user_id> [--expiry-days <days>]
soothed identity list-aksk --user <user_id>
soothed identity revoke-aksk --aksk-id <id>

# Token management
soothed identity list-tokens --user <user_id> [--active-only]
soothed identity revoke-token --jti <jti>
soothed identity revoke-all-tokens --user <user_id>

# External mapping
soothed identity map-external --channel <name> --sender-id <id> --user <user_id>
soothed identity list-mappings [--channel <name>] [--user <user_id>]
soothed identity unmap-external --channel <name> --sender-id <id>

# Status
soothed identity status
```

**Output example**:
```bash
$ soothed identity create-aksk --user alice --expiry-days 90
AKSK created for user: alice
  aksk_id:       a7f8e9c2-1234-5678-90ab-cdef12345678
  access_key:    AK-x7k2m9p4q1w8
  secret_key:    SK-a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6
  expires_at:    2024-03-25T00:00:00Z

WARNING: Save the secret_key securely. It cannot be retrieved later.
```

---

## Error Handling

| Error | Code | Response |
|-------|------|----------|
| Identity disabled | `identity_disabled` | Skip middleware, continue |
| Invalid AKSK | `invalid_credentials` | Generic error (no hints) |
| AKSK expired | `aksk_expired` | Error response |
| AKSK revoked | `aksk_revoked` | Error response |
| Token invalid | `token_invalid` | Error + action: "re_auth" |
| Token expired | `token_expired` | Error + action: "refresh_token" |
| Token revoked | `token_revoked` | Error + action: "re_auth" |
| Missing token | `missing_token` | Error response |
| Unmapped sender | `unmapped_identity` | Policy-based handling |

**Security principles**:
- No credential hints in error messages
- Constant-time hash comparison (prevent timing attacks)
- Generic error responses (no "user exists" / "AKSK found" exposure)

---

## Security Considerations

**Threat mitigations**:

| Threat | Mitigation |
|--------|------------|
| AKSK leakage | Hashed storage; short-lived tokens reduce exposure |
| Token theft | Short expiry (1 hour); HTTPS/WSS; JWT signature |
| Timing attack | Constant-time hash comparison |
| Replay attack | JTI tracking; revocation on refresh |
| JWT key compromise | Secure storage (env/file); rotation capability (future) |

**Implementation checklist**:
- Secret key SHA-256 hashed before storage
- HMAC.compare_digest for verification
- JWT signed with HS256
- JTI uniqueness (UUID)
- Revoked JTIs checked
- Access token short expiry
- Refresh token rotation (old revoked on use)
- JWT key from secure source
- Generic error messages
- Disabled by default

---

## Testing Strategy

**Unit tests** (`packages/soothe/tests/unit/core/security/`):
- IdentityProtocol methods
- JWT generation/validation
- Secret key hashing
- Token refresh flow

**Integration tests** (`packages/soothe-daemon/tests/integration/`):
- WebSocket auth flow
- Token validation in middleware
- External channel resolution
- Identity disabled mode

**CLI tests** (`packages/soothe-daemon/tests/unit/cli/`):
- Command output format
- Error handling
- Expiry validation

---

## Implementation Structure

**New files**:

```
packages/soothe/src/soothe/
├── core/security/
│   ├── __init__.py
│   ├── identity_service.py
│   ├── tokens.py
│   ├── credentials.py
│   ├── errors.py
│   └── models.py
├── protocols/
│   └── identity.py
├── middleware/
│   └── identity.py

packages/soothe-daemon/src/soothe_daemon/
├── cli/
│   └── identity.py
├── config/
│   └── models.py (modify: add IdentityConfig)
├── server/
│   ├── auth_handler.py
│   └── ws_server.py (modify: register auth handler)
├── runtime/
│   └── thread_state.py (modify: add user_id, aksk_id)
```

**Dependencies**:
- `pyjwt >= 2.8.0` (new)
- Existing: `typer`, `rich`, persistence

---

## Rollout Plan

**Phase 1 (MVP)**:
- IdentityProtocol implementation
- JWT token generation/validation
- AKSK management (create, revoke)
- Storage tables
- CLI commands
- IdentityMiddleware
- WebSocket auth handler

**Phase 2**:
- External identity mapping
- Policy-based fallback
- Channel integration

**Phase 3 (Future)**:
- Rate limiting
- Audit logging
- JWT key rotation

---

## Migration Steps

```bash
# 1. Deploy with identity disabled (default)
# No breaking changes

# 2. Enable in config
# daemon_config.yml: identity.enabled = true

# 3. Set JWT key
export SOOTHE_JWT_KEY="your-256-bit-secret"

# 4. Restart daemon
# Tables auto-created

# 5. Create admin AKSK
soothed identity create-user --user admin
soothed identity create-aksk --user admin

# 6. Update CLI config
# Add access_key, secret_key

# 7. Map external users (optional)
soothed identity map-external --channel telegram --sender-id 12345 --user alice
```

---

## Out of Scope

- User self-registration
- OAuth/OIDC integration
- Scoped/limited token permissions
- Rate limiting
- Audit logging
- REST API (WebSocket only)
- JWT key rotation (future)