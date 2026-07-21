"""Host alias for shared identity data models.

The canonical identity data models live in :mod:`soothe_sdk.protocols.identity`
(the protocol-contracts layer shared with the daemon and clients). This module
re-exports them so host consumers keep the ``soothe.foundation.identity.models``
import path.

Previously this module re-declared the 8 classes as a local copy, which
produced two distinct class objects in the same process: ``identity_service``
imported the SDK versions while ``tokens`` instantiated the local
``TokenClaims``, so ``isinstance`` across them failed silently. The local copy
also drifted (``IdentityStatus`` was missing fields the SDK owns).
"""

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

__all__ = [
    "AKSKPair",
    "AuthResult",
    "ExternalIdentityMapping",
    "IdentityStatus",
    "TokenClaims",
    "TokenInfo",
    "TokenRefreshResult",
    "User",
]
