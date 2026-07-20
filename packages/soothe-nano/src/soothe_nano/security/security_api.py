"""Public API surface for `soothe_nano.security`."""

from __future__ import annotations

from .operation_guard import WorkspaceToolOperationSecurity
from .path_security import (
    PathValidationError,
    PathValidator,
    ValidationResult,
    ValidationSeverity,
    create_permissive_validator,
    create_strict_validator,
)
from .policy_models import (
    PolicyAction,
    PolicyDecision,
    PolicyScope,
    PolicyViolation,
    SecurityPolicy,
)
from .policy_profiles import (
    DEFAULT_PROFILES,
    PERMISSIVE_POLICY,
    PRIVILEGED_PROFILE,
    READONLY_POLICY,
    READONLY_PROFILE,
    SANDBOX_POLICY,
    STANDARD_PROFILE,
    STRICT_POLICY,
    ConfigDrivenPolicy,
    _extract_required_permission,
)
from .security_enforcer import (
    OperationRecord,
    RateLimiter,
    SecurityContext,
    SecurityEnforcer,
    SecurityError,
    create_enforcer,
)

__all__ = [
    "PathValidator",
    "ValidationResult",
    "ValidationSeverity",
    "PathValidationError",
    "create_strict_validator",
    "create_permissive_validator",
    "PolicyAction",
    "PolicyScope",
    "PolicyViolation",
    "PolicyDecision",
    "SecurityPolicy",
    "STRICT_POLICY",
    "PERMISSIVE_POLICY",
    "READONLY_POLICY",
    "SANDBOX_POLICY",
    "ConfigDrivenPolicy",
    "STANDARD_PROFILE",
    "READONLY_PROFILE",
    "PRIVILEGED_PROFILE",
    "DEFAULT_PROFILES",
    "_extract_required_permission",
    "WorkspaceToolOperationSecurity",
    "OperationRecord",
    "RateLimiter",
    "SecurityEnforcer",
    "SecurityError",
    "SecurityContext",
    "create_enforcer",
]
