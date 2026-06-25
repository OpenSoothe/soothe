"""Identity service for soothe. RFC-307."""

from soothe.core.security.credentials import (
    generate_access_key,
    generate_secret_key,
    hash_secret_key,
    verify_secret_key,
)
from soothe.core.security.errors import (
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
from soothe.core.security.identity_service import (
    IdentityService,
    initialize_identity_tables_sync,
)
from soothe.core.security.models import (
    AKSKPair,
    AuthResult,
    ExternalIdentityMapping,
    IdentityStatus,
    TokenClaims,
    TokenInfo,
    TokenRefreshResult,
    User,
)
from soothe.core.security.tokens import (
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
