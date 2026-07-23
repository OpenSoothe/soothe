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
from soothe_sdk.protocols.identity import (
    AKSKPair,
    AuthResult,
    ExternalIdentityMapping,
    IdentityStatus,
    TokenClaims,
    TokenInfo,
    TokenRefreshResult,
    User,
)

from soothe.identity.credentials import (
    generate_access_key,
    generate_secret_key,
    hash_secret_key,
    verify_secret_key,
)
from soothe.identity.identity_service import (
    IdentityService,
    initialize_identity_tables_sync,
)
from soothe.identity.middleware import IdentityMiddleware
from soothe.identity.runtime import (
    AKSKConfig,
    IdentityConfig,
    IdentityRuntime,
    ThreadContextProvider,
    TokenConfig,
)
from soothe.identity.tokens import (
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
    # Runtime and middleware wiring
    "IdentityMiddleware",
    "IdentityRuntime",
    "IdentityConfig",
    "TokenConfig",
    "AKSKConfig",
    "ThreadContextProvider",
    # Service
    "IdentityService",
    "initialize_identity_tables_sync",
]
