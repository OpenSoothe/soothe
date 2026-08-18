"""Identity service error classes."""

from typing import ClassVar


class IdentityError(Exception):
    """Base error for identity service."""

    error_code: ClassVar[str] = "identity_error"
    """Error code for WebSocket/API responses."""
    message: ClassVar[str] = "Identity error"
    """Default error message."""

    def __init__(self, detail: str | None = None) -> None:
        self.detail = detail
        super().__init__(detail or self.message)


class IdentityDisabledError(IdentityError):
    """
    Identity service is disabled.

    When identity.enabled = false, identity operations are unavailable.
    """

    error_code = "identity_disabled"
    message = "Identity service is disabled"


class InvalidCredentialsError(IdentityError):
    """
    AKSK credentials are invalid.

    Generic error - does not reveal whether access_key exists or
    secret_key is wrong (security principle).
    """

    error_code = "invalid_credentials"
    message = "Access key or secret key is invalid"


class AKSKExpiredError(IdentityError):
    """
    AKSK has expired.

    The AKSK pair's expires_at timestamp is in the past.
    """

    error_code = "aksk_expired"
    message = "AKSK has expired"


class AKSKRevokedError(IdentityError):
    """
    AKSK has been revoked.

    The AKSK pair's revoked flag is True.
    """

    error_code = "aksk_revoked"
    message = "AKSK has been revoked"


class TokenError(IdentityError):
    """Base error for token-related issues."""

    error_code = "token_invalid"
    message = "Token is invalid"


class TokenExpiredError(TokenError):
    """
    Token has expired.

    JWT exp claim is in the past.
    """

    error_code = "token_expired"
    message = "Token has expired"


class TokenRevokedError(TokenError):
    """
    Token has been revoked.

    JTI found in revoked_jtis table.
    """

    error_code = "token_revoked"
    message = "Token has been revoked"


class MissingTokenError(TokenError):
    """
    No token provided in request.

    WebSocket message missing auth_token field.
    """

    error_code = "missing_token"
    message = "Authentication token required"


class UnmappedIdentityError(IdentityError):
    """
    External channel sender not mapped to soothe user.

    When unmapped_sender_policy = reject and sender_id
    has no mapping in external_identity_mappings table.
    """

    error_code = "unmapped_identity"
    message = "No identity mapping for this sender"


class UserNotFoundError(IdentityError):
    """
    User not found.

    Used in CLI operations, not returned to API clients
    (security principle - no user existence hints).
    """

    error_code = "user_not_found"
    message = "User not found"


class AKSKNotFoundError(IdentityError):
    """
    AKSK not found.

    Used in CLI operations for revoke_aksk, etc.
    """

    error_code = "aksk_not_found"
    message = "AKSK not found"


class MappingNotFoundError(IdentityError):
    """
    External identity mapping not found.

    Used in CLI operations for unmap_external.
    """

    error_code = "mapping_not_found"
    message = "External identity mapping not found"


class MappingConflictError(IdentityError):
    """
    External identity mapping already exists.

    When mapping (channel, sender_id) already exists with different user.
    """

    error_code = "mapping_conflict"
    message = "External identity mapping already exists"


__all__ = [
    "AKSKExpiredError",
    "AKSKNotFoundError",
    "AKSKRevokedError",
    "IdentityDisabledError",
    "IdentityError",
    "InvalidCredentialsError",
    "MappingConflictError",
    "MappingNotFoundError",
    "MissingTokenError",
    "TokenError",
    "TokenExpiredError",
    "TokenRevokedError",
    "UnmappedIdentityError",
    "UserNotFoundError",
]
