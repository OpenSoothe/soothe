"""Identity service data models. RFC-307 §Data Models."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class User(BaseModel):
    """
    Soothe user identity.

    RFC-307 §User.
    """

    user_id: str
    """Unique identifier."""
    created_at: datetime
    """Creation timestamp."""
    metadata: dict = Field(default_factory=dict)
    """Optional metadata (display_name, email, etc.)."""


class AKSKPair(BaseModel):
    """
    Access Key / Secret Key credential pair.

    RFC-307 §AKSKPair.
    """

    aksk_id: str
    """UUID, internal reference for revocation."""
    user_id: str
    """Owner user_id."""
    access_key: str
    """Public identifier: AK-{16 chars}."""
    secret_key_hash: str
    """SHA-256 hash of secret_key (plaintext never stored)."""
    created_at: datetime
    """Creation timestamp."""
    expires_at: datetime | None = None
    """Expiry timestamp, None = never expires."""
    revoked: bool = False
    """Revoked status."""
    revoked_at: datetime | None = None
    """Revocation timestamp."""


class TokenClaims(BaseModel):
    """
    JWT token claims structure.

    RFC-307 §TokenClaims.
    """

    jti: str
    """JWT ID (UUID) for revocation tracking."""
    user_id: str
    """Subject (soothe user)."""
    aksk_id: str
    """Source AKSK that issued this token."""
    token_type: Literal["access", "refresh"]
    """Token type: access (short-lived) or refresh (long-lived)."""
    issued_at: datetime
    """Issued at timestamp (iat claim)."""
    expires_at: datetime
    """Expires at timestamp (exp claim)."""


class ExternalIdentityMapping(BaseModel):
    """
    External channel identity mapping.

    Maps platform sender_id to soothe user_id for workspace isolation
    on external channels (Telegram, Feishu, etc.).

    RFC-307 §ExternalIdentityMapping.
    """

    mapping_id: str
    """Mapping UUID."""
    channel: str
    """Channel name (telegram, feishu, dingtalk, etc.)."""
    sender_id: str
    """Platform-specific user ID."""
    user_id: str
    """Mapped soothe user_id."""
    created_at: datetime
    """Creation timestamp."""


class AuthResult(BaseModel):
    """
    Authentication result containing tokens.

    RFC-307 §Result Types.
    """

    access_token: str
    """JWT access token (short-lived)."""
    refresh_token: str
    """JWT refresh token (long-lived)."""
    user_id: str
    """Authenticated user_id."""
    expires_in: int
    """Access token expiry in seconds."""


class TokenRefreshResult(BaseModel):
    """
    Token refresh result with new tokens.

    RFC-307 §Result Types.
    """

    access_token: str
    """New JWT access token."""
    refresh_token: str
    """New JWT refresh token (old one revoked)."""
    expires_in: int
    """Access token expiry in seconds."""


class TokenInfo(BaseModel):
    """
    Token info for listing.

    RFC-307 §Result Types.
    """

    jti: str
    """JWT ID."""
    user_id: str
    """Token owner."""
    aksk_id: str
    """Source AKSK."""
    token_type: str
    """Token type: access or refresh."""
    issued_at: datetime
    """Issued timestamp."""
    expires_at: datetime
    """Expiry timestamp."""
    revoked: bool
    """Revoked status."""


class IdentityStatus(BaseModel):
    """
    Identity service status info.

    RFC-307 §Result Types.
    """

    enabled: bool
    """Service enabled status."""
    storage_backend: str
    """Storage backend type (sqlite/postgres)."""
    jwt_key_source: str
    """JWT key source (env/config/file)."""
    users_count: int
    """Total users count."""
    active_aksk_count: int
    """Active AKSK pairs count."""
    active_tokens_count: int
    """Active tokens count."""


class IssuedToken(BaseModel):
    """
    Issued token record for revocation tracking.

    Stored in issued_tokens table for JTI tracking.
    """

    jti: str
    """JWT ID (primary key)."""
    user_id: str
    """Token owner."""
    aksk_id: str
    """Source AKSK."""
    token_type: Literal["access", "refresh"]
    """Token type."""
    issued_at: datetime
    """Issued timestamp."""
    expires_at: datetime
    """Expiry timestamp."""
    revoked: bool = False
    """Revoked status."""
    revoked_at: datetime | None = None
    """Revocation timestamp."""


class RevokedJTI(BaseModel):
    """
    Revoked JTI record for fast lookup.

    Stored in revoked_jtis table for token revocation checks.
    """

    jti: str
    """JWT ID (primary key)."""
    revoked_at: datetime
    """Revocation timestamp."""
    reason: str
    """Revocation reason (admin_revoked, aksk_revoked, refresh_used, expired)."""
