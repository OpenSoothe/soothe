"""Core policy models and evaluation logic for filesystem security."""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


def _path_is_under(path: str, prefix: str) -> bool:
    """True if `path` equals `prefix` or sits beneath it."""
    if not path or not prefix:
        return False
    prefix_norm = prefix.rstrip("/") or "/"
    if path == prefix_norm:
        return True
    return path.startswith(prefix_norm + "/")


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
    """Security policy for filesystem operations."""

    name: str
    description: str = ""
    scope: PolicyScope = PolicyScope.WORKSPACE
    allow_absolute: bool = False
    allow_traversal: bool = False
    allow_home_expansion: bool = False
    allow_symlinks: bool = False
    allow_hidden_files: bool = True
    max_file_size: int = 10 * 1024 * 1024
    max_path_length: int = 4096
    max_components: int = 256
    blocked_extensions: frozenset[str] = field(default_factory=frozenset)
    blocked_patterns: frozenset[str] = field(default_factory=frozenset)
    blocked_paths: frozenset[str] = field(default_factory=frozenset)
    allowed_paths: frozenset[str] | None = None
    allowed_operations: frozenset[str] = field(
        default_factory=lambda: frozenset({"read", "write", "delete", "ls", "glob", "mkdir"})
    )
    read_only_paths: frozenset[str] = field(default_factory=frozenset)
    no_delete_paths: frozenset[str] = field(default_factory=frozenset)
    max_operations_per_minute: int = 1000
    max_file_reads_per_minute: int = 100
    max_file_writes_per_minute: int = 50
    per_path_rate_limit: int | None = None
    on_violation: PolicyAction = PolicyAction.DENY
    on_suspicious: PolicyAction = PolicyAction.LOG
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
        violations: list[PolicyViolation] = []
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

        if path.startswith("/") and not self.allow_absolute:
            ws = (context or {}).get("workspace")
            is_virtual_under_workspace = False
            if ws is not None:
                from pathlib import Path as _Path

                from soothe_nano.workspace.workspace_paths import (
                    should_use_virtual_path_resolution,
                )

                is_virtual_under_workspace = should_use_virtual_path_resolution(path, _Path(ws))

            if not is_virtual_under_workspace:
                if self.allowed_paths is not None:
                    is_whitelisted = any(
                        _path_is_under(path, allowed_path) for allowed_path in self.allowed_paths
                    )
                    if not is_whitelisted:
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
                else:
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

        for blocked in self.blocked_paths:
            if _path_is_under(path, blocked):
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

        if self.allowed_paths is not None:
            allowed = any(_path_is_under(path, allowed_path) for allowed_path in self.allowed_paths)
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

        if operation in ("write", "edit", "delete"):
            for ro_path in self.read_only_paths:
                if _path_is_under(path, ro_path):
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

        if operation == "delete":
            for nd_path in self.no_delete_paths:
                if _path_is_under(path, nd_path):
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

        for validator in self.custom_validators:
            try:
                result = validator(path, operation)
                if result is not None:
                    if result.is_denied:
                        return result
                    violations.extend(result.violations)
            except Exception as e:
                logger.warning("Custom validator failed: %s", e)

        if violations:
            critical = any(v.severity == "critical" for v in violations)
            if critical:
                return PolicyDecision(
                    allowed=False,
                    action=PolicyAction.DENY,
                    reason="Critical policy violations detected",
                    violations=violations,
                )
            if self.on_violation == PolicyAction.DENY:
                return PolicyDecision(
                    allowed=False,
                    action=PolicyAction.DENY,
                    reason="Policy violations detected and denied by policy",
                    violations=violations,
                )
            return PolicyDecision(
                allowed=True,
                action=self.on_suspicious,
                reason="Policy violations detected but not denied",
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
