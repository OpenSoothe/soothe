# IG-505: Identity Service Implementation

**RFC**: RFC-307 (IdentityProtocol Architecture)
**Created**: 2026-06-25
**Status**: Implemented
**Target**: soothe-daemon, soothe core packages
**Completed**: 2026-06-26
**Verification**: `./scripts/verify_finally.sh` — all checks pass (workspace sync, dependency validation, formatting, linting, unit tests)

**Related**: [Identity config placement (`daemon.yml` vs `config.yml`)](../identity-config-placement.md)

---

## Overview

Implement IdentityProtocol for AKSK-based authentication and JWT token management in soothe-daemon. This guide covers:

- Protocol definition and implementation
- JWT token generation/validation
- AKSK credential management
- IdentityMiddleware for request validation
- External channel identity mapping
- CLI commands for identity management
- WebSocket auth message handling

---

## Module Structure

```
packages/soothe-sdk/src/soothe_sdk/
├── protocols/
│   ├── identity.py              # NEW: IdentityProtocol definition
│   └── __init__.py              # MODIFY: export IdentityProtocol

packages/soothe/src/soothe/
├── core/security/               # NEW directory
│   ├── __init__.py
│   ├── identity_service.py      # IdentityProtocol implementation
│   ├── tokens.py                # JWT generation/validation
│   ├── credentials.py           # AKSK generation, hashing
│   ├── models.py                # User, AKSKPair, TokenClaims, etc.
│   └── errors.py                # IdentityError classes
│
├── protocols/
│   └── __init__.py              # MODIFY: re-export IdentityProtocol
│
├── middleware/
│   ├── identity.py              # NEW: IdentityMiddleware
│   └── __init__.py              # MODIFY: export IdentityMiddleware

packages/soothe-daemon/src/soothe_daemon/
├── cli/
│   ├── identity.py              # NEW: soothed identity commands
│   └── __init__.py              # MODIFY: register identity app
│
├── config/
│   └── models.py                # MODIFY: add IdentityConfig
│
├── server/
│   ├── auth_handler.py          # NEW: WebSocket auth handler
│   └── ws_server.py             # MODIFY: register auth handler
│
├── runtime/
│   └── thread_state.py          # MODIFY: add user_id, aksk_id fields

packages/soothe/tests/unit/core/security/   # NEW directory
├── test_identity_service.py
├── test_tokens.py
├── test_credentials.py
├── test_identity_middleware.py

packages/soothe-daemon/tests/
├── unit/cli/
│   └── test_identity_cli.py     # NEW
├── integration/
│   ├── test_identity_websocket.py   # NEW
│   └── test_identity_external.py    # NEW
```

---

## Type Definitions

### Core Data Models (models.py)

```python
"""Identity service data models. RFC-307 §Data Models."""

from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


class User(BaseModel):
    """Soothe user identity. RFC-307 §User."""
    user_id: str
    created_at: datetime
    metadata: dict = Field(default_factory=dict)


class AKSKPair(BaseModel):
    """Access Key / Secret Key pair. RFC-307 §AKSKPair."""
    aksk_id: str
    user_id: str
    access_key: str
    secret_key_hash: str  # SHA-256 hash, plaintext never stored
    created_at: datetime
    expires_at: datetime | None = None
    revoked: bool = False
    revoked_at: datetime | None = None


class TokenClaims(BaseModel):
    """JWT token claims. RFC-307 §TokenClaims."""
    jti: str
    user_id: str
    aksk_id: str
    token_type: Literal["access", "refresh"]
    issued_at: datetime
    expires_at: datetime


class ExternalIdentityMapping(BaseModel):
    """External channel identity mapping. RFC-307 §ExternalIdentityMapping."""
    mapping_id: str
    channel: str
    sender_id: str
    user_id: str
    created_at: datetime


class AuthResult(BaseModel):
    """Authentication result. RFC-307 §Result Types."""
    access_token: str
    refresh_token: str
    user_id: str
    expires_in: int


class TokenRefreshResult(BaseModel):
    """Token refresh result. RFC-307 §Result Types."""
    access_token: str
    refresh_token: str
    expires_in: int


class TokenInfo(BaseModel):
    """Token info for listing. RFC-307 §Result Types."""
    jti: str
    user_id: str
    aksk_id: str
    token_type: str
    issued_at: datetime
    expires_at: datetime
    revoked: bool


class IdentityStatus(BaseModel):
    """Service status. RFC-307 §Result Types."""
    enabled: bool
    storage_backend: str
    jwt_key_source: str
    users_count: int
    active_aksk_count: int
    active_tokens_count: int
```

### Error Classes (errors.py)

```python
"""Identity service error classes. RFC-307 §Error Handling."""

class IdentityError(Exception):
    """Base error for identity service."""
    error_code: str = "identity_error"
    message: str = "Identity error"


class IdentityDisabledError(IdentityError):
    """Identity service is disabled."""
    error_code = "identity_disabled"
    message = "Identity service is disabled"


class InvalidCredentialsError(IdentityError):
    """AKSK credentials invalid."""
    error_code = "invalid_credentials"
    message = "Access key or secret key is invalid"


class AKSKExpiredError(IdentityError):
    """AKSK has expired."""
    error_code = "aksk_expired"
    message = "AKSK has expired"


class AKSKRevokedError(IdentityError):
    """AKSK has been revoked."""
    error_code = "aksk_revoked"
    message = "AKSK has been revoked"


class TokenError(IdentityError):
    """Base token error."""
    error_code = "token_invalid"
    message = "Token is invalid"


class TokenExpiredError(TokenError):
    """Token has expired."""
    error_code = "token_expired"
    message = "Token has expired"


class TokenRevokedError(TokenError):
    """Token has been revoked."""
    error_code = "token_revoked"
    message = "Token has been revoked"


class UnmappedIdentityError(IdentityError):
    """External identity not mapped."""
    error_code = "unmapped_identity"
    message = "No identity mapping for this sender"
```

### Config Models (daemon config)

```python
# Add to packages/soothe-daemon/src/soothe_daemon/config/models.py

class TokenConfig(BaseModel):
    """Token configuration. RFC-307 §Configuration."""
    access_token_expiry_hours: int = Field(default=1, ge=1, le=24)
    refresh_token_expiry_days: int = Field(default=7, ge=1, le=365)
    jwt_signing_key: str | None = None


class AKSKConfig(BaseModel):
    """AKSK configuration. RFC-307 §Configuration."""
    default_expiry_days: int | None = Field(default=90)
    max_expiry_days: int = Field(default=365)


class IdentityConfig(BaseModel):
    """Identity service configuration. RFC-307 §Configuration."""
    enabled: bool = False  # Disabled by default for backward compatibility
    tokens: TokenConfig = Field(default_factory=TokenConfig)
    aksk: AKSKConfig = Field(default_factory=AKSKConfig)
    unmapped_sender_policy: Literal["anonymous", "reject", "use_sender_id"] = "anonymous"
```

---

## Protocol Definition

### SDK Protocol (protocols/identity.py)

```python
"""IdentityProtocol definition. RFC-307 §Protocol Interface."""

from __future__ import annotations
from typing import Protocol, runtime_checkable
from soothe_sdk.identity.models import (
    User, AKSKPair, TokenClaims, ExternalIdentityMapping,
    AuthResult, TokenRefreshResult, TokenInfo, IdentityStatus,
)


@runtime_checkable
class IdentityProtocol(Protocol):
    """
    Identity service protocol for AKSK authentication.

    Provides user creation, AKSK provisioning, JWT token management,
    and external channel identity mapping.

    RFC-307 §Protocol Interface.
    """

    # User management
    def create_user(self, user_id: str, metadata: dict | None = None) -> User:
        """Create a new user. RFC-307 §User."""
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
        """
        Create AKSK pair for user.

        Returns AKSKPair with plaintext secret_key (one-time only).
        RFC-307 §AKSKPair.
        """
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

        Returns AuthResult with tokens or None if invalid.
        RFC-307 §Authentication Flow.
        """
        ...

    def validate_token(self, token: str) -> TokenClaims | None:
        """
        Validate JWT token.

        Returns TokenClaims if valid, None if invalid/expired/revoked.
        RFC-307 §Authentication Flow.
        """
        ...

    def refresh_token(self, refresh_token: str) -> TokenRefreshResult | None:
        """
        Refresh tokens using refresh_token.

        Returns new tokens, revokes old ones.
        RFC-307 §Token Refresh Flow.
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
        """Map external channel sender to soothe user. RFC-307 §ExternalIdentityMapping."""
        ...

    def resolve_identity(
        self,
        channel: str,
        sender_id: str,
    ) -> str | None:
        """Resolve external sender to user_id. RFC-307 §External Channel Resolution."""
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

## Implementation Details

### Credential Generation (credentials.py)

```python
"""AKSK credential generation and hashing. RFC-307 §AKSKPair."""

import hashlib
import hmac
import secrets


def generate_access_key() -> str:
    """
    Generate access key: AK-{16 chars}.

    Uses secrets.token_urlsafe for cryptographic randomness.
    RFC-307 §AKSKPair format.
    """
    random_chars = secrets.token_urlsafe(12)[:16]
    return f"AK-{random_chars}"


def generate_secret_key() -> str:
    """
    Generate secret key: SK-{32 chars}.

    Uses secrets.token_urlsafe for cryptographic randomness.
    RFC-307 §AKSKPair format.
    """
    random_chars = secrets.token_urlsafe(24)[:32]
    return f"SK-{random_chars}"


def hash_secret_key(secret_key: str) -> str:
    """
    Hash secret key for storage using SHA-256.

    Plaintext secret_key is never stored in database.
    RFC-307 §Security Checklist.
    """
    return hashlib.sha256(secret_key.encode()).hexdigest()


def verify_secret_key(secret_key: str, hash_value: str) -> bool:
    """
    Verify secret key against stored hash.

    Uses hmac.compare_digest for constant-time comparison
    to prevent timing attacks. RFC-307 §Security Checklist.
    """
    expected = hash_secret_key(secret_key)
    return hmac.compare_digest(expected.encode(), hash_value.encode())
```

### JWT Token Management (tokens.py)

```python
"""JWT token generation and validation. RFC-307 §TokenClaims."""

import jwt
import uuid
from datetime import datetime, timedelta
from typing import Literal

from soothe_sdk.identity.models import TokenClaims


class JWTManager:
    """
    JWT token generation and validation.

    RFC-307 §TokenClaims, §Authentication Flow.
    """

    def __init__(
        self,
        signing_key: str,
        access_expiry_hours: int = 1,
        refresh_expiry_days: int = 7,
    ) -> None:
        self.signing_key = signing_key
        self.access_expiry_hours = access_expiry_hours
        self.refresh_expiry_days = refresh_expiry_days

    def generate_access_token(
        self,
        user_id: str,
        aksk_id: str,
    ) -> tuple[str, TokenClaims]:
        """
        Generate access token (short-lived, 1 hour default).

        Returns (token, claims). RFC-307 §JWT payload structure.
        """
        now = datetime.utcnow()
        expiry = now + timedelta(hours=self.access_expiry_hours)
        jti = str(uuid.uuid4())

        payload = {
            "jti": jti,
            "sub": user_id,
            "aksk_id": aksk_id,
            "typ": "access",
            "iat": int(now.timestamp()),
            "exp": int(expiry.timestamp()),
        }

        token = jwt.encode(payload, self.signing_key, algorithm="HS256")
        claims = TokenClaims(
            jti=jti,
            user_id=user_id,
            aksk_id=aksk_id,
            token_type="access",
            issued_at=now,
            expires_at=expiry,
        )
        return token, claims

    def generate_refresh_token(
        self,
        user_id: str,
        aksk_id: str,
    ) -> tuple[str, TokenClaims]:
        """
        Generate refresh token (longer-lived, 7 days default).

        Returns (token, claims). RFC-307 §JWT payload structure.
        """
        now = datetime.utcnow()
        expiry = now + timedelta(days=self.refresh_expiry_days)
        jti = str(uuid.uuid4())

        payload = {
            "jti": jti,
            "sub": user_id,
            "aksk_id": aksk_id,
            "typ": "refresh",
            "iat": int(now.timestamp()),
            "exp": int(expiry.timestamp()),
        }

        token = jwt.encode(payload, self.signing_key, algorithm="HS256")
        claims = TokenClaims(
            jti=jti,
            user_id=user_id,
            aksk_id=aksk_id,
            token_type="refresh",
            issued_at=now,
            expires_at=expiry,
        )
        return token, claims

    def validate_token(self, token: str) -> TokenClaims | None:
        """
        Validate JWT token signature and expiry.

        Returns TokenClaims if valid, None if invalid/expired.
        Does NOT check revocation status (that's IdentityService responsibility).
        RFC-307 §Authentication Flow.
        """
        try:
            payload = jwt.decode(
                token,
                self.signing_key,
                algorithms=["HS256"],
            )
            return TokenClaims(
                jti=payload["jti"],
                user_id=payload["sub"],
                aksk_id=payload["aksk_id"],
                token_type=payload["typ"],
                issued_at=datetime.fromtimestamp(payload["iat"]),
                expires_at=datetime.fromtimestamp(payload["exp"]),
            )
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None
```

### Identity Service Implementation (identity_service.py)

Key implementation responsibilities:

1. **AKSK Authentication Flow**:
   - Lookup by access_key
   - Verify secret_key using constant-time comparison
   - Check AKSK not expired/revoked
   - Generate JWT tokens
   - Store JTIs in issued_tokens table

2. **Token Validation Flow**:
   - JWT signature validation (JWTManager)
   - Check JTI in revoked_jtis table
   - Return TokenClaims or None

3. **Token Refresh Flow**:
   - Validate refresh_token JWT
   - Check JTI not revoked
   - Generate new tokens
   - Mark old JTIs as revoked

4. **External Identity Resolution**:
   - Lookup channel:sender_id in external_identity_mappings
   - Return user_id or None

**Database Operations**:
- Use existing `PersistenceProtocol` backend
- Tables: users, aksk_pairs, issued_tokens, external_identity_mappings, revoked_jtis
- Follow SQLite backend pattern from `packages/soothe/src/soothe/sloop/checkpoints/sqlite_backend.py`

---

## Middleware Implementation

### IdentityMiddleware (middleware/identity.py)

```python
"""IdentityMiddleware for request validation. RFC-307 §Middleware Integration."""

from langchain.agents.middleware.types import AgentMiddleware
from soothe_sdk.identity import IdentityProtocol, IdentityConfig
from soothe_daemon.runtime.thread_state import ThreadState


class IdentityMiddleware(AgentMiddleware):
    """
    First middleware in stack for identity validation.

    WebSocket: Validate JWT auth_token
    External channels: Resolve sender_id via mapping

    RFC-307 §Middleware Integration.
    """

    def __init__(
        self,
        identity: IdentityProtocol,
        config: IdentityConfig,
    ) -> None:
        self._identity = identity
        self._config = config

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Any],
    ) -> ToolMessage | Command[Any]:
        """
        Validate identity before tool execution.

        RFC-307 §Middleware order: IdentityMiddleware before PolicyMiddleware.
        """
        # Skip when disabled
        if not self._config.enabled:
            return await handler(request)

        # Extract context from request
        configurable = request.runtime.config.get("configurable", {})
        channel_type = configurable.get("channel_type", "websocket")

        if channel_type == "websocket":
            token = configurable.get("auth_token")
            if not token:
                # Check if auth message (skip validation)
                message_type = configurable.get("message_type")
                if message_type in ("auth", "auth_refresh"):
                    return await handler(request)
                raise IdentityDisabledError("missing_token")

            claims = self._identity.validate_token(token)
            if not claims:
                raise TokenError("token_invalid")

            user_id = claims.user_id
            aksk_id = claims.aksk_id

        else:
            # External channel
            sender_id = configurable.get("sender_id")
            user_id = self._identity.resolve_identity(channel_type, sender_id)

            if not user_id:
                policy = self._config.unmapped_sender_policy
                if policy == "reject":
                    raise UnmappedIdentityError()
                elif policy == "use_sender_id":
                    user_id = f"{channel_type}:{sender_id}"
                else:  # anonymous
                    user_id = None

            aksk_id = None

        # Populate ThreadState
        thread_id = configurable.get("thread_id")
        if thread_id:
            ThreadState.set_user_id(thread_id, user_id, aksk_id)

        return await handler(request)
```

### ThreadState Extension

```python
# Add to packages/soothe-daemon/src/soothe_daemon/runtime/thread_state.py

# Add fields to ThreadState dataclass:
user_id: str | None = None
aksk_id: str | None = None

# Add method to ThreadStateRegistry:
def set_user_id(
    self,
    thread_id: str,
    user_id: str | None,
    aksk_id: str | None = None,
) -> None:
    """Set user context from IdentityMiddleware. RFC-307 §Middleware Integration."""
    state = self.get(thread_id)
    if state:
        state.user_id = user_id
        state.aksk_id = aksk_id
```

---

## CLI Commands

### Identity CLI (cli/identity.py)

```python
"""soothed identity commands. RFC-307 §CLI Commands."""

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(name="identity", help="Identity service management")
console = Console()


@app.command("create-user")
def create_user(
    user: str,
    metadata: str | None = None,
) -> None:
    """Create a new user."""
    ...


@app.command("create-aksk")
def create_aksk(
    user: str,
    expiry_days: int | None = None,
) -> None:
    """Create AKSK pair for user."""
    ...


@app.command("list-aksk")
def list_aksk(user: str) -> None:
    """List AKSK pairs for user."""
    ...


@app.command("revoke-aksk")
def revoke_aksk(aksk_id: str) -> None:
    """Revoke an AKSK pair."""
    ...


@app.command("map-external")
def map_external(
    channel: str,
    sender_id: str,
    user: str,
) -> None:
    """Map external channel sender to soothe user."""
    ...


@app.command("status")
def status() -> None:
    """Show identity service status."""
    ...
```

---

## WebSocket Auth Handler

### Auth Handler (server/auth_handler.py)

```python
"""WebSocket auth message handler. RFC-307 §WebSocket Message Types."""

from soothe_sdk.identity import IdentityProtocol


class AuthHandler:
    """Handle WebSocket auth/auth_refresh messages. RFC-307 §Authentication Flow."""

    def __init__(self, identity: IdentityProtocol) -> None:
        self._identity = identity

    async def handle_auth(
        self,
        access_key: str,
        secret_key: str,
    ) -> dict:
        """
        Process auth message with AKSK credentials.

        Returns auth_response message. RFC-307 §WebSocket Message Types.
        """
        result = self._identity.authenticate(access_key, secret_key)

        if not result:
            return {
                "type": "auth_response",
                "success": False,
                "error": "invalid_credentials",
            }

        return {
            "type": "auth_response",
            "success": True,
            "access_token": result.access_token,
            "refresh_token": result.refresh_token,
            "expires_in": result.expires_in,
            "user_id": result.user_id,
        }

    async def handle_refresh(
        self,
        refresh_token: str,
    ) -> dict:
        """
        Process auth_refresh message.

        Returns auth_refresh_response message. RFC-307 §WebSocket Message Types.
        """
        result = self._identity.refresh_token(refresh_token)

        if not result:
            return {
                "type": "auth_refresh_response",
                "success": False,
                "error": "invalid_refresh_token",
            }

        return {
            "type": "auth_refresh_response",
            "success": True,
            "access_token": result.access_token,
            "refresh_token": result.refresh_token,
            "expires_in": result.expires_in,
        }
```

---

## Testing Strategy

### Unit Tests

**test_credentials.py**:
- `test_generate_access_key_format()` - Verify AK-{16 chars} format
- `test_generate_secret_key_format()` - Verify SK-{32 chars} format
- `test_hash_secret_key_sha256()` - Verify SHA-256 output
- `test_verify_secret_key_correct()` - Constant-time comparison works
- `test_verify_secret_key_wrong()` - Wrong key fails

**test_tokens.py**:
- `test_generate_access_token_claims()` - JWT has all claims
- `test_generate_refresh_token_claims()` - JWT has all claims
- `test_validate_token_valid()` - Valid token returns claims
- `test_validate_token_expired()` - Expired token returns None
- `test_validate_token_wrong_key()` - Wrong signature returns None

**test_identity_service.py**:
- `test_create_user()` - User stored correctly
- `test_create_aksk()` - AKSK generated, secret hashed
- `test_authenticate_valid()` - Returns tokens
- `test_authenticate_invalid_secret()` - Returns None
- `test_authenticate_expired_aksk()` - Returns None
- `test_validate_token_revoked_jti()` - Revoked token returns None
- `test_refresh_token()` - Old JTIs revoked
- `test_map_external_identity()` - Mapping created
- `test_resolve_identity()` - Returns mapped user_id

**test_identity_middleware.py**:
- `test_skip_when_disabled()` - Passes through
- `test_websocket_valid_token()` - Populates user_id
- `test_websocket_missing_token()` - Raises error
- `test_external_mapped_sender()` - Resolves identity
- `test_external_unmapped_anonymous()` - Falls back to None

### Integration Tests

**test_identity_websocket.py**:
- Full WebSocket auth flow
- Token refresh flow
- Request with valid/invalid tokens
- Identity disabled mode

**test_identity_external.py**:
- External channel message with mapping
- Unmapped sender policy tests

---

## Error Handling Strategy

| Error | HTTP/WS Response | Action |
|-------|------------------|--------|
| `invalid_credentials` | auth_response success=false | Re-auth required |
| `aksk_expired` | auth_response success=false | New AKSK needed |
| `token_invalid` | error message | Re-auth required |
| `token_expired` | error message | Refresh or re-auth |
| `token_revoked` | error message | Re-auth required |
| `missing_token` | error message | Send auth first |

**Security principles**:
- Generic error messages (no "AKSK found but secret wrong" hints)
- Constant-time secret comparison
- JWT signature validated before any other checks

---

## Dependencies

| Package | Purpose | Version |
|---------|---------|---------|
| `pyjwt` | JWT generation/validation | >= 2.8.0 |
| Existing `PersistenceProtocol` | Storage backend | - |
| Existing middleware stack | Integration | - |

Add to `packages/soothe/pyproject.toml`:
```toml
dependencies = [
    # ... existing deps ...
    "pyjwt >= 2.8.0",
]
```

---

## Backward Compatibility

- `identity.enabled = false` (default): No auth required, existing behavior
- WebSocket without auth_token: Uses message-provided user_id
- External channel unmapped: Falls back to sender_id or anonymous
- Identity tables added to existing persistence DB on first enable

---

## Implementation Order

1. **Phase 1 - Core Protocol**:
   - Create models.py, errors.py
   - Create credentials.py, tokens.py
   - Create IdentityProtocol in SDK
   - Create IdentityService implementation
   - Add pyjwt dependency

2. **Phase 2 - Middleware**:
   - Extend ThreadState
   - Create IdentityMiddleware
   - Integrate with middleware stack builder

3. **Phase 3 - Daemon Integration**:
   - Add IdentityConfig to daemon config
   - Create AuthHandler
   - Register auth messages in WebSocket server

4. **Phase 4 - CLI**:
   - Create identity CLI commands
   - Register in main CLI app

5. **Phase 5 - Tests**:
   - Unit tests for all components
   - Integration tests for auth flow

---

## References

- RFC-307: IdentityProtocol Architecture
- RFC-305: PolicyProtocol (middleware order, permission context)
- RFC-620: Channel Architecture (external channels)
- RFC-621: Workspace Isolation (user_id → workspace)
- RFC-801: SQLite Backend (persistence pattern)

---

## Implementation Status

**Status**: Implemented (2026-06-26)

All phases of the Implementation Order are complete. The module locations differ slightly from the original plan (some modules were placed in more appropriate packages to respect the one-way dependency rule `soothe → soothe-daemon`), but every component is implemented and verified.

### Phase Completion

| Phase | Status | Notes |
|-------|--------|-------|
| Phase 1 — Core Protocol | ✅ Done | models, errors, credentials, tokens, IdentityProtocol (SDK), IdentityService |
| Phase 2 — Middleware | ✅ Done | ThreadState extended, IdentityMiddleware, integrated with middleware stack |
| Phase 3 — Daemon Integration | ✅ Done | IdentityConfig, AuthHandler, registered in server core |
| Phase 4 — CLI | ✅ Done | identity CLI commands, registered in main CLI app |
| Phase 5 — Tests | ✅ Done | Unit + WebSocket auth tests, all passing |

### Implemented Modules

**SDK (`packages/soothe-sdk`)**:
- `src/soothe_sdk/protocols/identity.py` — `IdentityProtocol` Protocol with full method surface
- `src/soothe_sdk/protocols/__init__.py` — exports `IdentityProtocol` and related models

**soothe core (`packages/soothe`)**:
- `src/soothe/core/security/__init__.py` — package exports
- `src/soothe/core/security/models.py` — User, AKSKPair, TokenClaims, ExternalIdentityMapping, result types
- `src/soothe/core/security/errors.py` — IdentityError hierarchy
- `src/soothe/core/security/credentials.py` — AKSK generation, SHA-256 hashing, constant-time verification
- `src/soothe/core/security/tokens.py` — JWT generation/validation (PyJWT)
- `src/soothe/core/security/identity_service.py` — `IdentityService` implementation (SQLite-backed)
- `src/soothe/protocols/__init__.py` — re-exports `IdentityProtocol` from SDK
- `src/soothe/middleware/identity.py` — `IdentityMiddleware`, `IdentityConfig`, `TokenConfig`, `AKSKConfig`
- `src/soothe/middleware/__init__.py` — exports `IdentityMiddleware`
- `pyproject.toml` — `pyjwt>=2.8.0,<3.0.0` dependency added

**soothe-daemon (`packages/soothe-daemon`)**:
- `src/soothe_daemon/identity_cli.py` — Typer sub-app (users, AKSK, tokens, external mappings, status)
- `src/soothe_daemon/cli.py` — registers `identity` sub-app via `add_typer`
- `src/soothe_daemon/config/models.py` — re-exports `IdentityConfig`/`TokenConfig`/`AKSKConfig` from soothe core
- `src/soothe_daemon/server/auth_handler.py` — `AuthHandler` (WebSocket auth + refresh flow)
- `src/soothe_daemon/server/core.py` — creates `IdentityService`/`AuthHandler` when `identity.enabled`
- `src/soothe_daemon/runtime/thread_state.py` — `ThreadState` extended with `user_id`, `aksk_id` fields

### Tests (all passing)

| Test file | Tests |
|-----------|-------|
| `packages/soothe/tests/unit/core/security/test_identity_service.py` | 56 |
| `packages/soothe/tests/unit/core/security/test_tokens.py` | 38 |
| `packages/soothe/tests/unit/core/security/test_credentials.py` | 37 |
| `packages/soothe/tests/unit/middleware/test_identity_middleware.py` | 22 |
| `packages/soothe-daemon/tests/unit/server/test_identity_cli.py` | 32 |
| `packages/soothe-daemon/tests/unit/server/test_identity_websocket.py` | 30 |
| **Total** | **215** |

### Deviations from Plan

1. **CLI location**: `identity_cli.py` placed at `src/soothe_daemon/identity_cli.py` (module root) and registered in `cli.py`, rather than under a `cli/` subpackage. Functionally equivalent.
2. **IdentityConfig location**: `IdentityConfig`/`TokenConfig`/`AKSKConfig` are defined in `soothe.middleware.identity` (core) and re-exported by the daemon config, preserving the one-way dependency rule (soothe must not depend on soothe-daemon).
3. **Test locations**: identity CLI and WebSocket tests live under `packages/soothe-daemon/tests/unit/server/`; the identity middleware test lives under `packages/soothe/tests/unit/middleware/`. The planned `tests/integration/test_identity_external.py` is covered by unit-level external-mapping tests in `test_identity_service.py` and `test_identity_middleware.py`.
4. **Config files**: `IdentityConfig` is not yet surfaced in `config/config.template.yml` / `config/develop/config.yml` as a top-level key (identity defaults to disabled for backward compatibility). Consumers construct it programmatically via the daemon config model. See [identity-config-placement.md](../identity-config-placement.md) for rationale and core-code split.

### Verification

`./scripts/verify_finally.sh` — **all checks pass**:
- ✓ Workspace sync (all packages, all extras)
- ✓ Package dependency validation (CLI/SDK/soothe/daemon boundaries)
- ✓ Code formatting (all packages)
- ✓ Linting (all packages)
- ✓ Unit tests (all packages, including 215 identity tests)