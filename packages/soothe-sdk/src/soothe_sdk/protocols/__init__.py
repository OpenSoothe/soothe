"""Protocol definitions for Soothe plugin authors.

These runtime-agnostic protocols define the stable interfaces that
community plugins can depend on without requiring the full daemon runtime.
"""

from soothe_sdk.protocols.persistence import PersistStore
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
    "PersistStore",
    # Policy
    "Permission",
    "PermissionSet",
    "ActionRequest",
    "PolicyContext",
    "PolicyDecision",
    "PolicyProfile",
    "PolicyProtocol",
    # Vector store
    "VectorRecord",
    "VectorStoreProtocol",
]