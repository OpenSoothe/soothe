"""Security enforcement layer with policy application.

This module provides SecurityEnforcer which applies security policies
to filesystem operations with comprehensive logging and audit trails.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from soothe.foundation.workspace.tool_path_resolution import join_workspace_normalized_path

from .policy import (
    PolicyAction,
    PolicyDecision,
    PolicyViolation,
    SecurityPolicy,
)
from .validator import PathValidator

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


@dataclass
class OperationRecord:
    """Record of a filesystem operation for audit and rate limiting."""

    operation: str
    path: str
    timestamp: float = field(default_factory=time.time)
    allowed: bool = True
    violations: list[PolicyViolation] = field(default_factory=list)


class RateLimiter:
    """Rate limiter for filesystem operations."""

    def __init__(self, window_seconds: int = 60) -> None:
        """Initialize rate limiter.

        Args:
            window_seconds: Time window for rate limiting in seconds.
        """
        self.window_seconds = window_seconds
        self.operations: defaultdict[str, list[float]] = defaultdict(list)
        self.path_operations: defaultdict[str, list[float]] = defaultdict(list)

    def record(self, operation: str, path: str) -> None:
        """Record an operation for rate limiting."""
        now = time.time()
        self.operations[operation].append(now)
        self.path_operations[path].append(now)

    def check_rate(
        self,
        operation: str,
        max_count: int,
        path: str | None = None,
    ) -> tuple[bool, int]:
        """Check if operation is within rate limit.

        Args:
            operation: Operation type to check.
            max_count: Maximum allowed operations in window.
            path: Optional specific path to check.

        Returns:
            Tuple of (allowed, current_count).
        """
        now = time.time()
        cutoff = now - self.window_seconds

        # Clean old entries
        self.operations[operation] = [t for t in self.operations[operation] if t > cutoff]

        count = len(self.operations[operation])
        if count >= max_count:
            return False, count

        if path:
            self.path_operations[path] = [t for t in self.path_operations[path] if t > cutoff]
            path_count = len(self.path_operations[path])
            if path_count >= max_count:
                return False, path_count

        return True, count

    def get_stats(self) -> dict[str, dict[str, int]]:
        """Get current rate limiting statistics."""
        now = time.time()
        cutoff = now - self.window_seconds

        return {
            "operations": {
                op: len([t for t in times if t > cutoff]) for op, times in self.operations.items()
            },
            "paths": {
                path: len([t for t in times if t > cutoff])
                for path, times in self.path_operations.items()
            },
        }


class SecurityEnforcer:
    """Enforces security policies on filesystem operations.

    This class provides comprehensive security enforcement including:
    - Path validation with traversal protection
    - Policy-based access control
    - Rate limiting
    - Audit logging
    - Violation reporting

    Example:
        >>> enforcer = SecurityEnforcer(
        ...     workspace="/safe/path",
        ...     policy=STRICT_POLICY,
        ... )
        >>> result = enforcer.check_access("../etc/passwd", "read")
        >>> if result.is_denied:
        ...     print(f"Access denied: {result.reason}")
    """

    def __init__(
        self,
        workspace: Path | str,
        policy: SecurityPolicy | None = None,
        validator: PathValidator | None = None,
        enable_audit_log: bool = True,
        enable_rate_limiting: bool = True,
        violation_callback: Callable[[PolicyViolation], None] | None = None,
    ) -> None:
        """Initialize security enforcer.

        Args:
            workspace: Base workspace directory.
            policy: Security policy to enforce (default: STRICT_POLICY).
            validator: PathValidator instance (default: strict validator).
            enable_audit_log: Whether to enable audit logging.
            enable_rate_limiting: Whether to enable rate limiting.
            violation_callback: Optional callback for violations.
        """
        self.workspace = Path(workspace).resolve()
        self.policy = policy or self._default_policy()
        self.validator = validator or self._default_validator()
        self.enable_audit_log = enable_audit_log
        self.enable_rate_limiting = enable_rate_limiting
        self.violation_callback = violation_callback

        self.rate_limiter = RateLimiter() if enable_rate_limiting else None
        self.audit_log: list[OperationRecord] = []
        self.max_audit_entries = 10000

        logger.info(
            "SecurityEnforcer initialized: workspace=%s, policy=%s",
            self.workspace,
            self.policy.name,
        )

    def _default_policy(self) -> SecurityPolicy:
        """Get default security policy."""
        from .policy import STRICT_POLICY

        return STRICT_POLICY

    def _default_validator(self) -> PathValidator:
        """Get default path validator."""
        return PathValidator(
            workspace=self.workspace,
            allow_absolute=self.policy.allow_absolute,
            allow_home_expansion=self.policy.allow_home_expansion,
            follow_symlinks=self.policy.allow_symlinks,
            max_path_length=self.policy.max_path_length,
            max_components=self.policy.max_components,
            custom_blocked_paths=self.policy.blocked_paths,
        )

    def check_access(
        self,
        path: str,
        operation: str,
        context: dict[str, Any] | None = None,
    ) -> PolicyDecision:
        """Check if operation on path is allowed.

        This is the main entry point for security checks. It performs:
        1. Path validation
        2. Policy evaluation
        3. Rate limiting
        4. Audit logging

        Args:
            path: Path to check.
            operation: Operation type (read, write, delete, etc.).
            context: Additional context for policy evaluation.

        Returns:
            PolicyDecision indicating if operation is allowed.
        """
        # Step 1: Path validation
        validation = self.validator.validate(path, operation, strict=True)

        if not validation.is_valid:
            violation = PolicyViolation(
                policy_name=self.policy.name,
                violation_type=validation.violation_type or "validation_failed",
                message=validation.message or "Path validation failed",
                path=path,
                operation=operation,
                severity=self._severity_from_validation(validation.severity),
                details=validation.details,
            )
            decision = PolicyDecision(
                allowed=False,
                action=PolicyAction.DENY,
                reason=validation.message,
                violations=[violation],
            )
            self._log_operation(path, operation, decision)
            return decision

        # Step 2: Policy evaluation
        policy_decision = self.policy.evaluate(path, operation, context)

        # Step 3: Rate limiting
        if self.enable_rate_limiting and self.rate_limiter:
            allowed, count = self.rate_limiter.check_rate(
                operation,
                self.policy.max_operations_per_minute,
                path,
            )
            if not allowed:
                violation = PolicyViolation(
                    policy_name=self.policy.name,
                    violation_type="rate_limit_exceeded",
                    message=f"Rate limit exceeded: {count} operations",
                    path=path,
                    operation=operation,
                    severity="high",
                )
                decision = PolicyDecision(
                    allowed=False,
                    action=PolicyAction.DENY,
                    reason="Rate limit exceeded",
                    violations=[violation],
                )
                self._log_operation(path, operation, decision)
                return decision

            self.rate_limiter.record(operation, path)

        # Step 4: Audit logging
        self._log_operation(path, operation, policy_decision)

        # Step 5: Violation callback
        if policy_decision.violations and self.violation_callback:
            for violation in policy_decision.violations:
                try:
                    self.violation_callback(violation)
                except Exception as e:
                    logger.error("Violation callback failed: %s", e)

        return policy_decision

    def _log_operation(
        self,
        path: str,
        operation: str,
        decision: PolicyDecision,
    ) -> None:
        """Log operation to audit log."""
        if not self.enable_audit_log:
            return

        record = OperationRecord(
            operation=operation,
            path=path,
            allowed=decision.allowed,
            violations=decision.violations,
        )

        self.audit_log.append(record)

        # Trim audit log if too large
        if len(self.audit_log) > self.max_audit_entries:
            self.audit_log = self.audit_log[-self.max_audit_entries :]

        # Log to standard logger
        if decision.is_denied:
            logger.warning(
                "SECURITY: Blocked %s on %s: %s",
                operation,
                path,
                decision.reason,
            )
            for violation in decision.violations:
                logger.warning(
                    "  Violation [%s]: %s",
                    violation.violation_type,
                    violation.message,
                )
        elif decision.violations:
            logger.info(
                "SECURITY: Allowed %s on %s with violations: %s",
                operation,
                path,
                decision.reason,
            )
        else:
            logger.debug(
                "SECURITY: Allowed %s on %s",
                operation,
                path,
            )

    def _severity_from_validation(
        self,
        severity: Any | None,
    ) -> str:
        """Convert validation severity to policy severity string."""
        from .validator import ValidationSeverity

        if severity is None:
            return "medium"
        if severity == ValidationSeverity.CRITICAL:
            return "critical"
        if severity == ValidationSeverity.HIGH:
            return "high"
        if severity == ValidationSeverity.MEDIUM:
            return "medium"
        return "low"

    def get_safe_path(self, path: str, operation: str = "read") -> Path:
        """Get validated safe path or raise SecurityError.

        Args:
            path: Path to validate.
            operation: Operation type.

        Returns:
            Validated Path object.

        Raises:
            SecurityError: If access is denied.
        """
        decision = self.check_access(path, operation)

        if decision.is_denied:
            violations = ", ".join(v.violation_type for v in decision.violations)
            raise SecurityError(
                f"Access denied for {operation} on {path}: {decision.reason}",
                violations=violations,
                decision=decision,
            )

        # Return the normalized path on disk (avoid ``workspace / absolute`` pitfall).
        normalized = self.validator.sanitize(path)
        return join_workspace_normalized_path(self.workspace, normalized)

    def get_audit_log(
        self,
        since: float | None = None,
        operation: str | None = None,
        allowed_only: bool | None = None,
    ) -> list[OperationRecord]:
        """Get filtered audit log entries.

        Args:
            since: Only entries after this timestamp.
            operation: Filter by operation type.
            allowed_only: Filter by allowed status.

        Returns:
            List of matching operation records.
        """
        results = self.audit_log

        if since is not None:
            results = [r for r in results if r.timestamp >= since]

        if operation is not None:
            results = [r for r in results if r.operation == operation]

        if allowed_only is not None:
            results = [r for r in results if r.allowed == allowed_only]

        return results

    def get_violations(
        self,
        since: float | None = None,
    ) -> list[PolicyViolation]:
        """Get all policy violations from audit log.

        Args:
            since: Only violations after this timestamp.

        Returns:
            List of policy violations.
        """
        violations: list[PolicyViolation] = []
        for record in self.audit_log:
            if since is not None and record.timestamp < since:
                continue
            violations.extend(record.violations)
        return violations

    def get_stats(self) -> dict[str, Any]:
        """Get security statistics."""
        stats = {
            "total_operations": len(self.audit_log),
            "blocked_operations": len([r for r in self.audit_log if not r.allowed]),
            "policy_name": self.policy.name,
            "workspace": str(self.workspace),
        }

        if self.enable_rate_limiting and self.rate_limiter:
            stats["rate_limits"] = self.rate_limiter.get_stats()

        # Count violations by type
        violation_counts: defaultdict[str, int] = defaultdict(int)
        for record in self.audit_log:
            for violation in record.violations:
                violation_counts[violation.violation_type] += 1

        stats["violation_counts"] = dict(violation_counts)

        return stats

    def clear_audit_log(self) -> None:
        """Clear the audit log."""
        self.audit_log.clear()
        logger.info("Audit log cleared")

    def update_policy(self, policy: SecurityPolicy) -> None:
        """Update the security policy.

        Args:
            policy: New security policy to apply.
        """
        old_name = self.policy.name
        self.policy = policy
        self.validator = self._default_validator()
        logger.info(
            "Security policy updated: %s -> %s",
            old_name,
            policy.name,
        )


class SecurityError(Exception):
    """Exception raised when security check fails."""

    def __init__(
        self,
        message: str,
        violations: str | None = None,
        decision: PolicyDecision | None = None,
    ) -> None:
        super().__init__(message)
        self.violations = violations
        self.decision = decision


class SecurityContext:
    """Context manager for temporary security policy changes."""

    def __init__(
        self,
        enforcer: SecurityEnforcer,
        policy: SecurityPolicy | None = None,
    ) -> None:
        """Initialize security context.

        Args:
            enforcer: Security enforcer to modify.
            policy: Temporary policy to apply (None = use current).
        """
        self.enforcer = enforcer
        self.policy = policy
        self._original_policy: SecurityPolicy | None = None

    def __enter__(self) -> SecurityEnforcer:
        """Enter context with temporary policy."""
        if self.policy:
            self._original_policy = self.enforcer.policy
            self.enforcer.update_policy(self.policy)
        return self.enforcer

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit context and restore original policy."""
        if self._original_policy:
            self.enforcer.update_policy(self._original_policy)


def create_enforcer(
    workspace: Path | str,
    policy_name: str = "strict",
    **kwargs: Any,
) -> SecurityEnforcer:
    """Create a security enforcer with named policy.

    Args:
        workspace: Base workspace directory.
        policy_name: Name of predefined policy (strict, permissive, readonly, sandbox).
        **kwargs: Additional arguments for SecurityEnforcer.

    Returns:
        Configured SecurityEnforcer instance.
    """
    from .policy import (
        PERMISSIVE_POLICY,
        READONLY_POLICY,
        SANDBOX_POLICY,
        STRICT_POLICY,
    )

    policies = {
        "strict": STRICT_POLICY,
        "permissive": PERMISSIVE_POLICY,
        "readonly": READONLY_POLICY,
        "sandbox": SANDBOX_POLICY,
    }

    policy = policies.get(policy_name, STRICT_POLICY)
    return SecurityEnforcer(workspace=workspace, policy=policy, **kwargs)
