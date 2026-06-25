"""Protocol definitions for Soothe plugin authors.

These runtime-agnostic protocols define the stable interfaces that
community plugins can depend on without requiring the full daemon runtime.
"""

from soothe_sdk.protocols.identity import (
    AKSKPair,
    AuthResult,
    ExternalIdentityMapping,
    IdentityProtocol,
    IdentityStatus,
    TokenClaims,
    TokenInfo,
    TokenRefreshResult,
    User,
)
from soothe_sdk.protocols.persistence import AsyncPersistStore
from soothe_sdk.protocols.policy import (
    ActionRequest,
    Permission,
    PermissionSet,
    PolicyContext,
    PolicyDecision,
    PolicyProfile,
    PolicyProtocol,
)
from soothe_sdk.protocols.vector_store import VectorRecord, VectorStoreProtocol

__all__ = [
    # Persistence
    "AsyncPersistStore",
    # Policy
    "Permission",
    "PermissionSet",
    "ActionRequest",
    "PolicyContext",
    "PolicyDecision",
    "PolicyProfile",
    "PolicyProtocol",
    # Identity (RFC-307)
    "User",
    "AKSKPair",
    "TokenClaims",
    "ExternalIdentityMapping",
    "AuthResult",
    "TokenRefreshResult",
    "TokenInfo",
    "IdentityStatus",
    "IdentityProtocol",
    # Vector store
    "VectorRecord",
    "VectorStoreProtocol",
]
