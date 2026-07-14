"""Security layer for path validation, policy enforcement, and operation security.

This module provides:
- Path validation, traversal protection, and SecurityEnforcer for filesystem ops
- Workspace filesystem path validation and banned command matching (RFC-617)
- Configuration-driven permission policy with named profiles
"""

from __future__ import annotations

from .config_policy import (
    DEFAULT_PROFILES,
    PRIVILEGED_PROFILE,
    READONLY_PROFILE,
    STANDARD_PROFILE,
    ConfigDrivenPolicy,
)
from .enforcement import SecurityEnforcer
from .operation_security import WorkspaceToolOperationSecurity
from .policy import PolicyDecision, PolicyViolation, SecurityPolicy
from .validator import PathValidationError, PathValidator, ValidationResult

__all__ = [
    "SecurityPolicy",
    "PolicyDecision",
    "PolicyViolation",
    "PathValidator",
    "ValidationResult",
    "PathValidationError",
    "SecurityEnforcer",
    "WorkspaceToolOperationSecurity",
    "ConfigDrivenPolicy",
    "STANDARD_PROFILE",
    "READONLY_PROFILE",
    "PRIVILEGED_PROFILE",
    "DEFAULT_PROFILES",
]
