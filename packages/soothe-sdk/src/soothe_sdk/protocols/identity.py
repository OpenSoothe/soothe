"""IdentityProtocol -- AKSK authentication and JWT token management."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

# ============================================================================
# Data Models
# ============================================================================


class User(BaseModel):
    """Soothe user identity.

    Args:
        user_id: Unique identifier.
        created_at: Creation timestamp.
        metadata: Optional metadata (display_name, email, etc.).
    """

    user_id: str
    created_at: datetime
    metadata: dict = Field(default_factory=dict)


class AKSKPair(BaseModel):
    """Access Key / Secret Key credential pair.

    Args:
        aksk_id: UUID, internal reference for revocation.
        user_id: Owner user_id.
        access_key: Public identifier (AK-{16 chars}).
        secret_key_hash: SHA-256 hash (plaintext never stored).
        created_at: Creation timestamp.
        expires_at: Expiry timestamp, None = never.
        revoked: Revoked status.
        revoked_at: Revocation timestamp.
    """

    aksk_id: str
    user_id: str
    access_key: str
    secret_key_hash: str
    created_at: datetime
    expires_at: datetime | None = None
    revoked: bool = False
    revoked_at: datetime | None = None


class TokenClaims(BaseModel):
    """JWT token claims.

    Args:
        jti: JWT ID (UUID) for revocation.
        user_id: Subject (soothe user).
        aksk_id: Source AKSK.
        token_type: Token type (access or refresh).
        issued_at: Issued at (iat).
        expires_at: Expires at (exp).
    """

    jti: str
    user_id: str
    aksk_id: str
    token_type: Literal["access", "refresh"]
    issued_at: datetime
    expires_at: datetime


class ExternalIdentityMapping(BaseModel):
    """External channel identity mapping.

    Args:
        mapping_id: Mapping UUID.
        channel: Channel name (telegram, feishu, etc.).
        sender_id: Platform user ID.
        user_id: Mapped soothe user.
        created_at: Creation timestamp.
    """

    mapping_id: str
    channel: str
    sender_id: str
    user_id: str
    created_at: datetime


class AuthResult(BaseModel):
    """Authentication result.

    Args:
        access_token: JWT access token.
        refresh_token: JWT refresh token.
        user_id: Authenticated user_id.
        expires_in: Access token expiry in seconds.
    """

    access_token: str
    refresh_token: str
    user_id: str
    expires_in: int


class TokenRefreshResult(BaseModel):
    """Token refresh result.

    Args:
        access_token: New JWT access token.
        refresh_token: New JWT refresh token.
        expires_in: Access token expiry in seconds.
    """

    access_token: str
    refresh_token: str
    expires_in: int


class TokenInfo(BaseModel):
    """Token info for listing.

    Args:
        jti: JWT ID.
        user_id: Token owner.
        aksk_id: Source AKSK.
        token_type: Token type.
        issued_at: Issued timestamp.
        expires_at: Expiry timestamp.
        revoked: Revoked status.
    """

    jti: str
    user_id: str
    aksk_id: str
    token_type: str
    issued_at: datetime
    expires_at: datetime
    revoked: bool


class IdentityStatus(BaseModel):
    """Service status.

    Args:
        enabled: Service enabled status.
        storage_backend: Storage backend type.
        jwt_key_source: JWT key source.
        users_count: Total users.
        active_aksk_count: Active AKSK pairs.
        active_tokens_count: Active tokens.
    """

    enabled: bool
    storage_backend: str
    jwt_key_source: str
    users_count: int
    active_aksk_count: int
    active_tokens_count: int


# ============================================================================
# Protocol Definition
# ============================================================================


@runtime_checkable
class IdentityProtocol(Protocol):
    """Identity service protocol for AKSK authentication.

    Provides user creation, AKSK provisioning, JWT token management,
    and external channel identity mapping.

    When enabled, IdentityMiddleware validates tokens before PolicyMiddleware,
    ensuring workspace isolation is tied to authenticated user identity.
    """

    # -----------------------------------------------------------------------
    # User Management
    # -----------------------------------------------------------------------

    def create_user(
        self,
        user_id: str,
        metadata: dict | None = None,
    ) -> User:
        """Create a new user.

        Args:
            user_id: Unique user identifier.
            metadata: Optional metadata dict.

        Returns:
            Created User instance.
        """
        ...

    def get_user(self, user_id: str) -> User | None:
        """Get user by ID.

        Args:
            user_id: User identifier.

        Returns:
            User if found, None otherwise.
        """
        ...

    def list_users(self) -> list[User]:
        """List all users.

        Returns:
            List of all User instances.
        """
        ...

    def delete_user(self, user_id: str) -> None:
        """Delete user and revoke all credentials.

        Args:
            user_id: User to delete.

        Note: Also revokes all AKSK pairs and tokens for this user.
        """
        ...

    # -----------------------------------------------------------------------
    # AKSK Management
    # -----------------------------------------------------------------------

    def create_aksk(
        self,
        user_id: str,
        expiry_days: int | None = None,
    ) -> AKSKPair:
        """Create AKSK pair for user.

        Args:
            user_id: Owner user_id.
            expiry_days: Optional expiry days (None = never).

        Returns:
            AKSKPair with plaintext secret_key (one-time only!).

        Warning: Save secret_key securely - it cannot be retrieved later.
        """
        ...

    def list_aksk(self, user_id: str) -> list[AKSKPair]:
        """List AKSK pairs for user.

        Args:
            user_id: User to list AKSK for.

        Returns:
            List of AKSKPair instances (secret_key_hash not useful).
        """
        ...

    def revoke_aksk(self, aksk_id: str) -> None:
        """Revoke AKSK and all related tokens.

        Args:
            aksk_id: AKSK ID to revoke.

        Note: All tokens from this AKSK are also revoked.
        """
        ...

    # -----------------------------------------------------------------------
    # Authentication
    # -----------------------------------------------------------------------

    def authenticate(
        self,
        access_key: str,
        secret_key: str,
    ) -> AuthResult | None:
        """Authenticate with AKSK credentials.

        Args:
            access_key: Access key (AK-{16 chars}).
            secret_key: Secret key (SK-{32 chars}).

        Returns:
            AuthResult with tokens if valid, None if invalid/expired/revoked.
        """
        ...

    def validate_token(self, token: str) -> TokenClaims | None:
        """Validate JWT token.

        Args:
            token: JWT token string.

        Returns:
            TokenClaims if valid (signature, expiry, not revoked).
            None if invalid, expired, or revoked.
        """
        ...

    def refresh_token(
        self,
        refresh_token: str,
    ) -> TokenRefreshResult | None:
        """Refresh tokens using refresh_token.

        Args:
            refresh_token: JWT refresh token.

        Returns:
            TokenRefreshResult with new tokens if valid.
            None if invalid, expired, or revoked.

        Note: Old tokens are revoked after refresh (rotation).
        """
        ...

    # -----------------------------------------------------------------------
    # Token Management
    # -----------------------------------------------------------------------

    def revoke_token(self, jti: str) -> None:
        """Revoke token by JTI.

        Args:
            jti: JWT ID to revoke.
        """
        ...

    def revoke_all_tokens(self, user_id: str) -> None:
        """Revoke all tokens for user.

        Args:
            user_id: User to revoke tokens for.
        """
        ...

    def list_tokens(
        self,
        user_id: str,
        active_only: bool = False,
    ) -> list[TokenInfo]:
        """List tokens for user.

        Args:
            user_id: User to list tokens for.
            active_only: If True, exclude revoked/expired tokens.

        Returns:
            List of TokenInfo instances.
        """
        ...

    # -----------------------------------------------------------------------
    # External Identity Mapping
    # -----------------------------------------------------------------------

    def map_external_identity(
        self,
        channel: str,
        sender_id: str,
        user_id: str,
    ) -> ExternalIdentityMapping:
        """Map external channel sender to soothe user.

        Args:
            channel: Channel name (telegram, feishu, etc.).
            sender_id: Platform user ID.
            user_id: Soothe user_id to map to.

        Returns:
            Created ExternalIdentityMapping.
        """
        ...

    def resolve_identity(
        self,
        channel: str,
        sender_id: str,
    ) -> str | None:
        """Resolve external sender to user_id.

        Args:
            channel: Channel name.
            sender_id: Platform user ID.

        Returns:
            user_id if mapped, None otherwise.
        """
        ...

    def list_mappings(
        self,
        channel: str | None = None,
        user_id: str | None = None,
    ) -> list[ExternalIdentityMapping]:
        """List external identity mappings.

        Args:
            channel: Filter by channel (optional).
            user_id: Filter by user_id (optional).

        Returns:
            List of ExternalIdentityMapping instances.
        """
        ...

    def unmap_external(self, channel: str, sender_id: str) -> None:
        """Remove external identity mapping.

        Args:
            channel: Channel name.
            sender_id: Platform user ID.
        """
        ...

    # -----------------------------------------------------------------------
    # Status
    # -----------------------------------------------------------------------

    def get_status(self) -> IdentityStatus:
        """Get identity service status.

        Returns:
            IdentityStatus with counts and configuration info.
        """
        ...
