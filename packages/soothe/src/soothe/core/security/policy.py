"""Security policy definitions and enforcement rules.

This module provides policy-based security controls for filesystem operations,
including configurable rules for different security contexts.
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


class PolicyAction(enum.Enum):
    """Actions that can be taken when a policy violation is detected."""

    ALLOW = "allow"
    DENY = "deny"
    LOG = "log"
    NOTIFY = "notify"
    SANITIZE = "sanitize"


class PolicyScope(enum.Enum):
    """Scopes for policy application."""

    GLOBAL = "global"
    WORKSPACE = "workspace"
    THREAD = "thread"
    TOOL = "tool"
    OPERATION = "operation"


@dataclass(frozen=True)
class PolicyViolation:
    """Represents a policy violation."""

    policy_name: str
    violation_type: str
    message: str
    path: str | None = None
    operation: str | None = None
    severity: str = "medium"
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: __import__("datetime").datetime.now().isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "policy_name": self.policy_name,
            "violation_type": self.violation_type,
            "message": self.message,
            "path": self.path,
            "operation": self.operation,
            "severity": self.severity,
            "details": self.details,
            "timestamp": self.timestamp,
        }


@dataclass
class PolicyDecision:
    """Decision made by policy evaluation."""

    allowed: bool
    action: PolicyAction
    reason: str | None = None
    violations: list[PolicyViolation] = field(default_factory=list)
    sanitized_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_denied(self) -> bool:
        """Check if decision denies the operation."""
        return not self.allowed or self.action == PolicyAction.DENY

    @property
    def should_log(self) -> bool:
        """Check if this decision should be logged."""
        return self.action in (PolicyAction.LOG, PolicyAction.DENY, PolicyAction.NOTIFY)

    def merge(self, other: PolicyDecision) -> PolicyDecision:
        """Merge another decision into this one (most restrictive wins)."""
        if other.is_denied:
            return PolicyDecision(
                allowed=False,
                action=PolicyAction.DENY,
                reason=other.reason or self.reason,
                violations=self.violations + other.violations,
                sanitized_path=self.sanitized_path or other.sanitized_path,
                metadata={**self.metadata, **other.metadata},
            )
        return PolicyDecision(
            allowed=self.allowed,
            action=self.action if self.action != PolicyAction.ALLOW else other.action,
            reason=self.reason or other.reason,
            violations=self.violations + other.violations,
            sanitized_path=self.sanitized_path or other.sanitized_path,
            metadata={**self.metadata, **other.metadata},
        )


@dataclass
class SecurityPolicy:
    """Security policy for filesystem operations.

    Policies define rules for what operations are allowed and under what
    conditions. Multiple policies can be combined for layered security.

    Example:
        >>> policy = SecurityPolicy(
        ...     name="strict_workspace",
        ...     allow_absolute=False,
        ...     allow_traversal=False,
        ...     blocked_extensions={".exe", ".dll"},
        ... )
    """

    name: str
    description: str = ""
    scope: PolicyScope = PolicyScope.WORKSPACE

    # Path restrictions
    allow_absolute: bool = False
    allow_traversal: bool = False
    allow_home_expansion: bool = False
    allow_symlinks: bool = False
    allow_hidden_files: bool = True

    # Size limits
    max_file_size: int = 10 * 1024 * 1024  # 10 MB
    max_path_length: int = 4096
    max_components: int = 256

    # Blocked patterns
    blocked_extensions: frozenset[str] = field(default_factory=frozenset)
    blocked_patterns: frozenset[str] = field(default_factory=frozenset)
    blocked_paths: frozenset[str] = field(default_factory=frozenset)
    allowed_paths: frozenset[str] | None = None  # If set, only these paths allowed

    # Operation restrictions
    allowed_operations: frozenset[str] = field(
        default_factory=lambda: frozenset({"read", "write", "delete", "ls", "glob", "mkdir"})
    )
    read_only_paths: frozenset[str] = field(default_factory=frozenset)
    no_delete_paths: frozenset[str] = field(default_factory=frozenset)

    # Rate limiting
    max_operations_per_minute: int = 1000
    max_file_reads_per_minute: int = 100
    max_file_writes_per_minute: int = 50

    # Actions
    on_violation: PolicyAction = PolicyAction.DENY
    on_suspicious: PolicyAction = PolicyAction.LOG

    # Custom rules
    custom_validators: list[Callable[[str, str], PolicyDecision | None]] = field(
        default_factory=list,
        repr=False,
    )

    def evaluate(
        self,
        path: str,
        operation: str,
        context: dict[str, Any] | None = None,
    ) -> PolicyDecision:
        """Evaluate policy against a path and operation.

        Args:
            path: The path being accessed.
            operation: The operation being performed.
            context: Additional context for evaluation.

        Returns:
            PolicyDecision indicating whether operation is allowed.
        """
        violations: list[PolicyViolation] = []

        # Check operation is allowed
        if operation not in self.allowed_operations:
            return PolicyDecision(
                allowed=False,
                action=PolicyAction.DENY,
                reason=f"Operation '{operation}' not allowed",
                violations=[
                    PolicyViolation(
                        policy_name=self.name,
                        violation_type="operation_not_allowed",
                        message=f"Operation '{operation}' is not in allowed_operations",
                        path=path,
                        operation=operation,
                        severity="high",
                    )
                ],
            )

        # Check path length
        if len(path) > self.max_path_length:
            violations.append(
                PolicyViolation(
                    policy_name=self.name,
                    violation_type="path_too_long",
                    message=f"Path length {len(path)} exceeds maximum {self.max_path_length}",
                    path=path,
                    operation=operation,
                    severity="medium",
                )
            )

        # Check absolute path
        if path.startswith("/") and not self.allow_absolute:
            violations.append(
                PolicyViolation(
                    policy_name=self.name,
                    violation_type="absolute_path_not_allowed",
                    message="Absolute paths are not allowed",
                    path=path,
                    operation=operation,
                    severity="high",
                )
            )

        # Check traversal
        if ".." in path and not self.allow_traversal:
            violations.append(
                PolicyViolation(
                    policy_name=self.name,
                    violation_type="traversal_not_allowed",
                    message="Path traversal (..) is not allowed",
                    path=path,
                    operation=operation,
                    severity="critical",
                )
            )

        # Check home expansion
        if "~" in path and not self.allow_home_expansion:
            violations.append(
                PolicyViolation(
                    policy_name=self.name,
                    violation_type="home_expansion_not_allowed",
                    message="Home directory expansion (~) is not allowed",
                    path=path,
                    operation=operation,
                    severity="medium",
                )
            )

        # Check blocked patterns
        for pattern in self.blocked_patterns:
            import fnmatch

            if fnmatch.fnmatch(path.lower(), pattern.lower()):
                violations.append(
                    PolicyViolation(
                        policy_name=self.name,
                        violation_type="blocked_pattern",
                        message=f"Path matches blocked pattern: {pattern}",
                        path=path,
                        operation=operation,
                        severity="high",
                        details={"pattern": pattern},
                    )
                )

        # Check blocked extensions
        path_lower = path.lower()
        for ext in self.blocked_extensions:
            if path_lower.endswith(ext.lower()):
                violations.append(
                    PolicyViolation(
                        policy_name=self.name,
                        violation_type="blocked_extension",
                        message=f"File extension '{ext}' is blocked",
                        path=path,
                        operation=operation,
                        severity="medium",
                        details={"extension": ext},
                    )
                )

        # Check blocked paths
        for blocked in self.blocked_paths:
            if path.startswith(blocked) or blocked in path:
                violations.append(
                    PolicyViolation(
                        policy_name=self.name,
                        violation_type="blocked_path",
                        message=f"Path is in blocked location: {blocked}",
                        path=path,
                        operation=operation,
                        severity="critical",
                        details={"blocked_path": blocked},
                    )
                )

        # Check allowed paths (whitelist mode)
        if self.allowed_paths is not None:
            allowed = any(
                path.startswith(allowed_path) or allowed_path in path
                for allowed_path in self.allowed_paths
            )
            if not allowed:
                violations.append(
                    PolicyViolation(
                        policy_name=self.name,
                        violation_type="path_not_allowed",
                        message="Path is not in allowed paths list",
                        path=path,
                        operation=operation,
                        severity="high",
                    )
                )

        # Check read-only paths for write operations
        if operation in ("write", "edit", "delete"):
            for ro_path in self.read_only_paths:
                if path.startswith(ro_path):
                    violations.append(
                        PolicyViolation(
                            policy_name=self.name,
                            violation_type="read_only_violation",
                            message=f"Path '{path}' is read-only",
                            path=path,
                            operation=operation,
                            severity="high",
                        )
                    )

        # Check no-delete paths
        if operation == "delete":
            for nd_path in self.no_delete_paths:
                if path.startswith(nd_path):
                    violations.append(
                        PolicyViolation(
                            policy_name=self.name,
                            violation_type="delete_not_allowed",
                            message=f"Deletion not allowed in: {nd_path}",
                            path=path,
                            operation=operation,
                            severity="high",
                        )
                    )

        # Run custom validators
        for validator in self.custom_validators:
            try:
                result = validator(path, operation)
                if result is not None:
                    if result.is_denied:
                        return result
                    violations.extend(result.violations)
            except Exception as e:
                logger.warning("Custom validator failed: %s", e)

        # Determine final decision
        if violations:
            critical = any(v.severity == "critical" for v in violations)
            high = any(v.severity == "high" for v in violations)

            if critical:
                return PolicyDecision(
                    allowed=False,
                    action=PolicyAction.DENY,
                    reason="Critical policy violations detected",
                    violations=violations,
                )
            elif high and self.on_violation == PolicyAction.DENY:
                return PolicyDecision(
                    allowed=False,
                    action=PolicyAction.DENY,
                    reason="High severity policy violations detected",
                    violations=violations,
                )
            else:
                return PolicyDecision(
                    allowed=True,
                    action=self.on_suspicious,
                    reason="Policy violations detected but not critical",
                    violations=violations,
                )

        return PolicyDecision(
            allowed=True,
            action=PolicyAction.ALLOW,
            reason="Policy check passed",
        )

    def with_restrictions(
        self,
        **kwargs: Any,
    ) -> SecurityPolicy:
        """Create a new policy with additional restrictions."""
        current = {
            "name": f"{self.name}_restricted",
            "description": self.description,
            "scope": self.scope,
            "allow_absolute": self.allow_absolute,
            "allow_traversal": self.allow_traversal,
            "allow_home_expansion": self.allow_home_expansion,
            "allow_symlinks": self.allow_symlinks,
            "allow_hidden_files": self.allow_hidden_files,
            "max_file_size": self.max_file_size,
            "max_path_length": self.max_path_length,
            "max_components": self.max_components,
            "blocked_extensions": self.blocked_extensions,
            "blocked_patterns": self.blocked_patterns,
            "blocked_paths": self.blocked_paths,
            "allowed_paths": self.allowed_paths,
            "allowed_operations": self.allowed_operations,
            "read_only_paths": self.read_only_paths,
            "no_delete_paths": self.no_delete_paths,
            "on_violation": self.on_violation,
            "on_suspicious": self.on_suspicious,
        }
        current.update(kwargs)
        return SecurityPolicy(**current)


# Predefined security policies

STRICT_POLICY = SecurityPolicy(
    name="strict",
    description="Maximum security - blocks all dangerous operations",
    allow_absolute=False,
    allow_traversal=False,
    allow_home_expansion=False,
    allow_symlinks=False,
    blocked_extensions=frozenset(
        {
            ".exe",
            ".dll",
            ".so",
            ".dylib",
            ".bin",
            ".sh",
            ".bat",
            ".cmd",
            ".ps1",
            ".pyz",
            ".egg",
            ".whl",
        }
    ),
    blocked_patterns=frozenset(
        {
            "*.key",
            "*.pem",
            "*.p12",
            "*.pfx",
            ".env*",
            "*.secret",
            "*.credentials",
            ".git/*",
            ".svn/*",
            ".hg/*",
        }
    ),
    blocked_paths=frozenset(
        {
            "/etc",
            "/bin",
            "/sbin",
            "/usr",
            "/lib",
            "/lib64",
            "/dev",
            "/proc",
            "/sys",
            "/root",
            "/boot",
            "/var/log",
            "/tmp/..",
        }
    ),
    on_violation=PolicyAction.DENY,
    on_suspicious=PolicyAction.DENY,
)

PERMISSIVE_POLICY = SecurityPolicy(
    name="permissive",
    description="Permissive policy for trusted environments",
    allow_absolute=True,
    allow_traversal=False,
    allow_home_expansion=True,
    allow_symlinks=True,
    on_violation=PolicyAction.DENY,
    on_suspicious=PolicyAction.LOG,
)

READONLY_POLICY = SecurityPolicy(
    name="readonly",
    description="Read-only access only",
    allowed_operations=frozenset({"read", "ls", "glob", "exists"}),
    allow_absolute=False,
    allow_traversal=False,
    on_violation=PolicyAction.DENY,
)

SANDBOX_POLICY = SecurityPolicy(
    name="sandbox",
    description="Strict sandbox for untrusted code",
    allow_absolute=False,
    allow_traversal=False,
    allow_home_expansion=False,
    allow_symlinks=False,
    allow_hidden_files=False,
    max_file_size=1024 * 1024,  # 1 MB
    max_path_length=256,
    max_components=32,
    blocked_extensions=frozenset(
        {
            ".exe",
            ".dll",
            ".so",
            ".dylib",
            ".sh",
            ".bat",
            ".cmd",
            ".ps1",
            ".vbs",
            ".py",
            ".pyw",
            ".pyc",
            ".pyo",
            ".rb",
            ".pl",
            ".php",
            ".jsp",
            ".jar",
            ".war",
            ".ear",
        }
    ),
    blocked_patterns=frozenset(
        {
            "*..*",
            "*~*",
            "*.tmp",
            "*.temp",
            ".*",
            "*/.*",
            "*/.git/*",
            "*/.svn/*",
        }
    ),
    allowed_operations=frozenset({"read", "ls", "glob"}),
    on_violation=PolicyAction.DENY,
    on_suspicious=PolicyAction.DENY,
)
