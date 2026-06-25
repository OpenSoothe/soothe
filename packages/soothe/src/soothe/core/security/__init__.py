"""Identity service for soothe. RFC-307."""

from soothe.core.security.models import (
    User,
    AKSKPair,
    TokenClaims,
    ExternalIdentityMapping,
    AuthResult,
    TokenRefreshResult,
    TokenInfo,
    IdentityStatus,
)
from soothe.core.security.errors import (
    IdentityError,
    IdentityDisabledError,
    InvalidCredentialsError,
    AKSKExpiredError,
    AKSKRevokedError,
    TokenError,
    TokenExpiredError,
    TokenRevokedError,
    UnmappedIdentityError,
)
from soothe.core.security.credentials import (
    generate_access_key,
    generate_secret_key,
    hash_secret_key,
    verify_secret_key,
)
from soothe.core.security.tokens import (
    JWTManager,
    resolve_jwt_key,
    generate_jwt_key,
    save_jwt_key,
)
from soothe.core.security.identity_service import (
    IdentityService,
    initialize_identity_tables_sync,
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
