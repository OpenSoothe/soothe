"""PolicyProtocol -- permission-based access control (RFC-0002 Module 4).

Re-exported from soothe_sdk for backwards compatibility.
"""

from soothe_sdk.protocols.policy import (  # noqa: F401
    ActionRequest,
    Permission,
    PermissionSet,
    PolicyContext,
    PolicyDecision,
    PolicyProfile,
    PolicyProtocol,
)

__all__ = [
    "Permission",
    "PermissionSet",
    "ActionRequest",
    "PolicyContext",
    "PolicyDecision",
    "PolicyProfile",
    "PolicyProtocol",
]
