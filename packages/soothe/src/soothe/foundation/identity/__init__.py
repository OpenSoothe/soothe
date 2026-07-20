"""Identity service for soothe. RFC-307.

This module provides AKSK-based authentication and JWT token management.
"""

from soothe_sdk.identity.errors import (
    AKSKExpiredError,
    AKSKRevokedError,
    IdentityDisabledError,
    IdentityError,
    InvalidCredentialsError,
    TokenError,
    TokenExpiredError,
    TokenRevokedError,
    UnmappedIdentityError,
)

from soothe.foundation.identity.credentials import (
    generate_access_key,
    generate_secret_key,
    hash_secret_key,
    verify_secret_key,
)
from soothe.foundation.identity.identity_service import (
    IdentityService,
    initialize_identity_tables_sync,
)
from soothe.foundation.identity.models import (
    AKSKPair,
    AuthResult,
    ExternalIdentityMapping,
    IdentityStatus,
    TokenClaims,
    TokenInfo,
    TokenRefreshResult,
    User,
)
from soothe.foundation.identity.tokens import (
    JWTManager,
    generate_jwt_key,
    resolve_jwt_key,
    save_jwt_key,
)

__all__ = [
    # Models
    "User",
    "AKSKPair",
    "TokenClaims",
    "ExternalIdentityMapping",
    "AuthResult",
    "TokenRefreshResult",
    "TokenInfo",
    "IdentityStatus",
    # Errors
    "IdentityError",
    "IdentityDisabledError",
    "InvalidCredentialsError",
    "AKSKExpiredError",
    "AKSKRevokedError",
    "TokenError",
    "TokenExpiredError",
    "TokenRevokedError",
    "UnmappedIdentityError",
    # Credentials
    "generate_access_key",
    "generate_secret_key",
    "hash_secret_key",
    "verify_secret_key",
    # Tokens
    "JWTManager",
    "resolve_jwt_key",
    "generate_jwt_key",
    "save_jwt_key",
    # Service
    "IdentityService",
    "initialize_identity_tables_sync",
]
