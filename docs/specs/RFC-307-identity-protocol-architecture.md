# RFC-307: IdentityProtocol Architecture

**RFC**: 307
**Title**: IdentityProtocol: AKSK Authentication & JWT Token Management
**Status**: Draft
**Kind**: Architecture Design
**Created**: 2026-06-25
**Dependencies**: RFC-000, RFC-001, RFC-305
**Related**: RFC-620 (Channel Architecture), RFC-621 (Workspace Isolation)

---

## Abstract

This RFC defines IdentityProtocol, Soothe's identity service for AKSK-based authentication and JWT token management. IdentityProtocol provides user creation, AKSK provisioning, token issuance/validation, and external channel identity mapping. When enabled, IdentityMiddleware validates tokens before PolicyMiddleware, ensuring workspace isolation is tied to authenticated user identity rather than message-provided user_id fields.

---

## Motivation

Current authentication in soothe-daemon relies on:

1. **WebSocket**: Client provides `user_id` field in messages (unverified)
2. **External channels**: Platform sender_id used directly or mapped via loop_id

This lacks:
- Credential-based authentication
- Token lifecycle management
- Revocation capability
- Admin-controlled identity provisioning
- Unified identity across internal and external channels

IdentityProtocol addresses these with industry-standard patterns (AKSK + JWT) while preserving backward compatibility.

---

## Protocol Interface

```python
class IdentityProtocol(Protocol):
    """Identity service protocol for AKSK authentication."""

    # User management
    def create_user(self, user_id: str, metadata: dict | None = None) -> User:
        """Create a new user."""
        ...

    def get_user(self, user_id: str) -> User | None:
        """Get user by ID."""
        ...

    def list_users(self) -> list[User]:
        """List all users."""
        ...

    def delete_user(self, user_id: str) -> None:
        """Delete user and revoke all credentials."""
        ...

    # AKSK management
    def create_aksk(
        self,
        user_id: str,
        expiry_days: int | None = None,
    ) -> AKSKPair:
        """Create AKSK pair for user. Returns plaintext secret_key once."""
        ...

    def list_aksk(self, user_id: str) -> list[AKSKPair]:
        """List AKSK pairs for user."""
        ...

    def revoke_aksk(self, aksk_id: str) -> None:
        """Revoke AKSK and all related tokens."""
        ...

    # Authentication
    def authenticate(
        self,
        access_key: str,
        secret_key: str,
    ) -> AuthResult | None:
        """
        Authenticate with AKSK credentials.

        Returns access_token, refresh_token, user_id or None.
        """
        ...

    def validate_token(self, token: str) -> TokenClaims | None:
        """
        Validate JWT token.

        Returns TokenClaims if valid, None if invalid/expired/revoked.
        """
        ...

    def refresh_token(self, refresh_token: str) -> TokenRefreshResult | None:
        """
        Refresh tokens using refresh_token.

        Returns new tokens, revokes old ones.
        """
        ...

    # Token management
    def revoke_token(self, jti: str) -> None:
        """Revoke token by JTI."""
        ...

    def revoke_all_tokens(self, user_id: str) -> None:
        """Revoke all tokens for user."""
        ...

    def list_tokens(
        self,
        user_id: str,
        active_only: bool = False,
    ) -> list[TokenInfo]:
        """List tokens for user."""
        ...

    # External identity mapping
    def map_external_identity(
        self,
        channel: str,
        sender_id: str,
        user_id: str,
    ) -> ExternalIdentityMapping:
        """Map external channel sender to soothe user."""
        ...

    def resolve_identity(
        self,
        channel: str,
        sender_id: str,
    ) -> str | None:
        """Resolve external sender to user_id."""
        ...

    def list_mappings(
        self,
        channel: str | None = None,
        user_id: str | None = None,
    ) -> list[ExternalIdentityMapping]:
        """List external identity mappings."""
        ...

    def unmap_external(self, channel: str, sender_id: str) -> None:
        """Remove external identity mapping."""
        ...

    # Status
    def get_status(self) -> IdentityStatus:
        """Get identity service status."""
        ...
```

---

## Data Models

### User

```python
class User(BaseModel):
    """Soothe user identity."""
    user_id: str
    """Unique identifier."""
    created_at: datetime
    """Creation timestamp."""
    metadata: dict = {}
    """Optional metadata (display_name, email, etc.)."""
```

### AKSKPair

```python
class AKSKPair(BaseModel):
    """Access Key / Secret Key pair."""
    aksk_id: str
    """UUID, internal reference."""
    user_id: str
    """Owner."""
    access_key: str
    """Public identifier: AK-{16 chars}."""
    secret_key_hash: str
    """SHA-256 hash of secret_key (plaintext not stored)."""
    created_at: datetime
    """Creation timestamp."""
    expires_at: datetime | None = None
    """Expiry timestamp, None = never."""
    revoked: bool = False
    """Revoked status."""
    revoked_at: datetime | None = None
    """Revocation timestamp."""
```

**Credential formats**:
- Access key: `AK-x7k2m9p4q1w8` (prefix + 16 chars)
- Secret key: `SK-a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6` (prefix + 32 chars)

### TokenClaims

```python
class TokenClaims(BaseModel):
    """JWT token claims."""
    jti: str
    """JWT ID (UUID) for revocation."""
    user_id: str
    """Subject (soothe user)."""
    aksk_id: str
    """Source AKSK."""
    token_type: Literal["access", "refresh"]
    """Token type."""
    issued_at: datetime
    """Issued at (iat)."""
    expires_at: datetime
    """Expires at (exp)."""
```

**JWT payload structure**:
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

### ExternalIdentityMapping

```python
class ExternalIdentityMapping(BaseModel):
    """External channel identity mapping."""
    mapping_id: str
    """Mapping UUID."""
    channel: str
    """Channel name (telegram, feishu, etc.)."""
    sender_id: str
    """Platform user ID."""
    user_id: str
    """Mapped soothe user."""
    created_at: datetime
    """Creation timestamp."""
```

### Result Types

```python
class AuthResult(BaseModel):
    """Authentication result."""
    access_token: str
    refresh_token: str
    user_id: str
    expires_in: int
    """Access token expiry in seconds."""

class TokenRefreshResult(BaseModel):
    """Token refresh result."""
    access_token: str
    refresh_token: str
    expires_in: int

class TokenInfo(BaseModel):
    """Token info for listing."""
    jti: str
    user_id: str
    aksk_id: str
    token_type: str
    issued_at: datetime
    expires_at: datetime
    revoked: bool

class IdentityStatus(BaseModel):
    """Service status."""
    enabled: bool
    storage_backend: str
    jwt_key_source: str
    users_count: int
    active_aksk_count: int
    active_tokens_count: int
```

---

## Storage Schema

Identity tables use existing persistence backend (SQLite/Postgres), coexisting with loop state tables:

```sql
-- Users
CREATE TABLE users (
    user_id TEXT PRIMARY KEY,
    created_at TIMESTAMP NOT NULL,
    metadata JSON
);

-- AKSK pairs
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

-- Issued tokens (for revocation tracking)
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

-- External identity mappings
CREATE TABLE external_identity_mappings (
    mapping_id TEXT PRIMARY KEY,
    channel TEXT NOT NULL,
    sender_id TEXT NOT NULL,
    user_id TEXT NOT NULL REFERENCES users(user_id),
    created_at TIMESTAMP NOT NULL,
    UNIQUE(channel, sender_id)
);

-- Revoked JTIs (fast lookup)
CREATE TABLE revoked_jtis (
    jti TEXT PRIMARY KEY,
    revoked_at TIMESTAMP NOT NULL,
    reason TEXT NOT NULL
);

-- Indexes
CREATE INDEX idx_aksk_user ON aksk_pairs(user_id);
CREATE INDEX idx_tokens_user ON issued_tokens(user_id);
CREATE INDEX idx_tokens_aksk ON issued_tokens(aksk_id);
CREATE INDEX idx_mappings_channel_sender ON external_identity_mappings(channel, sender_id);
```

---

## Authentication Flow

### WebSocket AKSK Flow

```
┌──────────┐                        ┌─────────────────┐
│  Client  │                        │ IdentityService │
└──────────┘                        └─────────────────┘
     │                                     │
     │  1. auth message                    │
     │  {access_key, secret_key}           │
     │─────────────────────────────────────│
     │                                     │
     │                          2. validate AKSK
     │                          3. check expiry/revoked
     │                          4. generate JWTs
     │                          5. store JTIs
     │                                     │
     │  6. auth_response                   │
     │  {access_token, refresh_token}      │
     │─────────────────────────────────────│
     │                                     │
     │  7. request with auth_token         │
     │─────────────────────────────────────│
     │                                     │
     │                          8. validate JWT
     │                          9. check JTI not revoked
     │                          10. return user_id
     │                                     │
     │  11. proceed with user context      │
     │                                     │
```

### Token Refresh Flow

```
Client sends: { "type": "auth_refresh", "refresh_token": "<jwt>" }

IdentityService:
1. Validate refresh_token JWT
2. Check JTI not revoked
3. Check token_type == "refresh"
4. Generate new access_token + refresh_token
5. Mark old access JTI as revoked
6. Mark old refresh JTI as revoked
7. Store new JTIs
8. Return new tokens
```

### External Channel Resolution

```
┌───────────┐    ┌──────────────┐    ┌─────────────────┐
│  Platform │    │   Channel    │    │ IdentityService │
│(Telegram) │    │              │    │                 │
└───────────┘    └──────────────┘    └─────────────────┘
     │                  │                    │
     │ message          │                    │
     │─────────────────│                    │
     │                  │                    │
     │                  │ extract sender_id  │
     │                  │────────────────────│
     │                  │                    │
     │                  │    resolve_identity│
     │                  │    ("telegram", id)│
     │                  │                    │
     │                  │    lookup mapping  │
     │                  │    return user_id  │
     │                  │                    │
     │                  │ user_id populated  │
     │                  │────────────────────│
     │                  │                    │
```

---

## Middleware Integration

IdentityMiddleware is the **first** middleware in the stack, before PolicyMiddleware:

```python
class IdentityMiddleware:
    """
    First middleware: validates identity for all requests.

    WebSocket: validate JWT auth_token
    External: resolve sender_id via mapping
    """

    async def process(self, context: RequestContext) -> MiddlewareResult:
        if not self.config.enabled:
            return MiddlewareResult.CONTINUE  # Skip when disabled

        if context.channel_type == "websocket":
            token = context.message.get("auth_token")
            if not token:
                # Check if auth message (initial authentication)
                if context.message.get("type") in ("auth", "auth_refresh"):
                    return MiddlewareResult.CONTINUE
                return MiddlewareResult.REJECT(error="missing_token")

            claims = self.identity.validate_token(token)
            if not claims:
                return MiddlewareResult.REJECT(error="token_invalid")

            context.user_id = claims.user_id
            context.aksk_id = claims.aksk_id

        else:
            # External channel
            user_id = self.identity.resolve_identity(
                context.channel_type,
                context.sender_id
            )

            if not user_id:
                policy = self.config.unmapped_sender_policy
                if policy == "reject":
                    return MiddlewareResult.REJECT(error="unmapped_identity")
                elif policy == "use_sender_id":
                    user_id = f"{context.channel_type}:{context.sender_id}"
                else:  # anonymous
                    user_id = None

            context.user_id = user_id

        ThreadState.set_user_id(context.user_id, context.aksk_id)
        return MiddlewareResult.CONTINUE
```

**Middleware order**:
```
IdentityMiddleware (token validation / identity resolution)
    ↓
PolicyMiddleware (permission checks, uses user_id)
    ↓
OtherMiddleware (logging, tracing)
    ↓
RequestHandler
    ↓
WorkspaceResolution (uses ThreadState.user_id)
```

---

## Configuration

Identity config in daemon_config.yml (not core config.yml):

```yaml
identity:
  # Disabled by default for backward compatibility
  enabled: false

  # Token settings
  tokens:
    access_token_expiry_hours: 1      # 1-24 hours
    refresh_token_expiry_days: 7      # 1-365 days
    jwt_signing_key: "${SOOTHE_JWT_KEY}"

  # AKSK defaults
  aksk:
    default_expiry_days: 90           # None = never
    max_expiry_days: 365

  # External channel policy
  unmapped_sender_policy: "anonymous"  # anonymous | reject | use_sender_id
```

**Config model**:
```python
class IdentityConfig(BaseModel):
    enabled: bool = False  # Disabled by default
    tokens: TokenConfig = TokenConfig()
    aksk: AKSKConfig = AKSKConfig()
    unmapped_sender_policy: Literal["anonymous", "reject", "use_sender_id"] = "anonymous"
```

**JWT key resolution** (when enabled):
1. Environment: `SOOTHE_JWT_KEY`
2. Config: `identity.tokens.jwt_signing_key`
3. Auto-generated: `$SOOTHE_HOME/.jwt_key`

---

## CLI Commands

```bash
soothed identity create-user --user <user_id>
soothed identity create-aksk --user <user_id> [--expiry-days <days>]
soothed identity list-aksk --user <user_id>
soothed identity revoke-aksk --aksk-id <id>
soothed identity revoke-token --jti <jti>
soothed identity map-external --channel <name> --sender-id <id> --user <user_id>
soothed identity list-mappings [--channel <name>]
soothed identity status
```

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
```

---

## Error Handling

| Error | Code | Response Action |
|-------|------|-----------------|
| Invalid AKSK | `invalid_credentials` | Re-auth |
| AKSK expired | `aksk_expired` | Re-auth (new AKSK) |
| AKSK revoked | `aksk_revoked` | Re-auth (new AKSK) |
| Token invalid | `token_invalid` | Re-auth |
| Token expired | `token_expired` | Refresh |
| Token revoked | `token_revoked` | Re-auth |
| Missing token | `missing_token` | Auth first |
| Unmapped identity | `unmapped_identity` | Policy-based |

**Security principles**:
- Generic error messages (no credential hints)
- Constant-time hash comparison
- JWT signature always validated

---

## Backward Compatibility

| Scenario | Behavior |
|----------|----------|
| `identity.enabled = false` | Existing behavior unchanged |
| WebSocket without auth_token | Uses message-provided user_id |
| External channel unmapped | Falls back to sender_id or anonymous |
| Existing persistence DB | Identity tables added on enable |

---

## Dependencies

| Dependency | Purpose |
|------------|---------|
| `pyjwt >= 2.8.0` | JWT generation/validation |
| Existing `PersistenceProtocol` | Storage backend |
| Existing middleware stack | Integration point |

---

## Implementation Location

```
packages/soothe/src/soothe/
├── core/security/
│   ├── identity_service.py    # IdentityProtocol impl
│   ├── tokens.py              # JWT handling
│   ├── credentials.py         # AKSK generation/hashing
│   ├── models.py              # Data models
│   └── errors.py              # Error classes
├── protocols/
│   └── identity.py            # Protocol definition
├── middleware/
│   └── identity.py            # IdentityMiddleware

packages/soothe-daemon/src/soothe_daemon/
├── cli/
│   └── identity.py            # CLI commands
├── server/
│   └── auth_handler.py        # WebSocket auth handler
├── config/
│   └── models.py              # IdentityConfig
├── runtime/
│   └── thread_state.py        # user_id, aksk_id fields
```

---

## Security Checklist

- [ ] Secret key SHA-256 hashed before storage
- [ ] Constant-time hash comparison (HMAC.compare_digest)
- [ ] JWT signed with HS256
- [ ] JWT expiry validated (exp claim)
- [ ] JTI checked against revoked_jtis
- [ ] Access token short expiry (default 1 hour)
- [ ] Refresh token rotation (old revoked on use)
- [ ] JWT key from secure source
- [ ] Generic error messages
- [ ] Disabled by default

---

## References

- RFC-305: PolicyProtocol (permission checking, uses user_id)
- RFC-620: Channel Architecture (external channels, sender_id)
- RFC-621: Workspace Isolation (user_id → workspace path)
- RFC-901: OperationSecurityProtocol (file/shell security)