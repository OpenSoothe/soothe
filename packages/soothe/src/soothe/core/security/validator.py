"""Path validation with comprehensive security checks.

This module provides PathValidator for detecting and preventing path traversal
attacks, symlink attacks, and other filesystem-based security vulnerabilities.
"""

from __future__ import annotations

import enum
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from soothe.core.workspace.tool_path_resolution import join_workspace_normalized_path

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class PathValidationError(Exception):
    """Raised when path validation fails."""

    def __init__(self, message: str, violation_type: str, path: str) -> None:
        super().__init__(message)
        self.violation_type = violation_type
        self.path = path


class ValidationSeverity(enum.IntEnum):
    """Severity levels for validation violations."""

    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


@dataclass(frozen=True)
class ValidationResult:
    """Result of path validation."""

    is_valid: bool
    normalized_path: str | None = None
    violation_type: str | None = None
    message: str | None = None
    severity: ValidationSeverity | None = None
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def is_blocked(self) -> bool:
        """Check if this validation blocks the operation."""
        return not self.is_valid


class PathValidator:
    """Comprehensive path validator with traversal protection.

    This validator implements multiple layers of defense against path-based
    attacks including directory traversal, symlink following, and null byte
    injection.

    Example:
        >>> validator = PathValidator(workspace="/safe/workspace")
        >>> result = validator.validate("../etc/passwd")
        >>> result.is_valid
        False
        >>> result.violation_type
        'path_traversal'
    """

    # Dangerous patterns that indicate path traversal attempts
    TRAVERSAL_PATTERNS: tuple[tuple[str, str], ...] = (
        (r"\.\./", "dot_dot_slash"),
        (r"\.\.\\", "dot_dot_backslash"),
        (r"\.\.$", "dot_dot_end"),
        (r"^\.\./", "leading_dot_dot_slash"),
        (r"^\.\.\\", "leading_dot_dot_backslash"),
        (r"/\.\./", "mid_dot_dot_slash"),
        (r"\\\.\.\\", "mid_dot_dot_backslash"),
        (r"%2e%2e%2f", "url_encoded_dot_dot_slash"),
        (r"%2e%2e%5c", "url_encoded_dot_dot_backslash"),
        (r"\.\.\.\.+", "multiple_dots"),
    )

    # Suspicious characters and sequences
    SUSPICIOUS_PATTERNS: tuple[tuple[str, str, ValidationSeverity], ...] = (
        (r"\x00", "null_byte", ValidationSeverity.CRITICAL),
        (r"\n", "newline", ValidationSeverity.HIGH),
        (r"\r", "carriage_return", ValidationSeverity.HIGH),
        (r"\t", "tab", ValidationSeverity.LOW),
        (r"\x00-\x1f", "control_chars", ValidationSeverity.HIGH),
        (r"\x7f", "delete_char", ValidationSeverity.MEDIUM),
        (r"\ufff0-\uffff", "unicode_special", ValidationSeverity.MEDIUM),
    )

    # Path components that should be blocked
    DANGEROUS_COMPONENTS: frozenset[str] = frozenset(
        {
            "..",
            ".",
            "~",
            "",
            ".git",
            ".svn",
            ".hg",
            "__pycache__",
            ".DS_Store",
            "Thumbs.db",
        }
    )

    # System paths that should never be accessed
    BLOCKED_SYSTEM_PATHS: frozenset[str] = frozenset(
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
            "/home/..",
            "C:\\Windows",
            "C:\\Windows\\System32",
            "C:\\Program Files",
            "C:\\Program Files (x86)",
            "C:\\Users\\..",
        }
    )

    def __init__(
        self,
        workspace: Path | str,
        allow_absolute: bool = False,
        allow_home_expansion: bool = False,
        follow_symlinks: bool = False,
        max_path_length: int = 4096,
        max_components: int = 256,
        custom_blocked_paths: frozenset[str] | None = None,
    ) -> None:
        """Initialize path validator.

        Args:
            workspace: Base workspace directory for validation.
            allow_absolute: Whether to allow absolute paths (False = block).
            allow_home_expansion: Whether to allow ~ expansion (False = block).
            follow_symlinks: Whether symlinks are followed (security risk).
            max_path_length: Maximum allowed path length.
            max_components: Maximum number of path components.
            custom_blocked_paths: Additional paths to block.
        """
        self.workspace = Path(workspace).resolve()
        self.allow_absolute = allow_absolute
        self.allow_home_expansion = allow_home_expansion
        self.follow_symlinks = follow_symlinks
        self.max_path_length = max_path_length
        self.max_components = max_components
        self.blocked_paths = self.BLOCKED_SYSTEM_PATHS | (custom_blocked_paths or frozenset())

        # Compile regex patterns for performance
        self._traversal_regex = [
            (re.compile(pattern, re.IGNORECASE), name) for pattern, name in self.TRAVERSAL_PATTERNS
        ]
        self._suspicious_regex = [
            (re.compile(pattern), name, severity)
            for pattern, name, severity in self.SUSPICIOUS_PATTERNS
        ]

    def validate(
        self,
        path: str,
        operation: str = "read",
        strict: bool = False,
    ) -> ValidationResult:
        """Validate a path for security issues.

        Args:
            path: The path to validate.
            operation: Type of operation (read, write, delete, etc.).
            strict: If True, fail on any suspicious pattern.

        Returns:
            ValidationResult with validation status and details.
        """
        if not isinstance(path, str):
            return ValidationResult(
                is_valid=False,
                violation_type="invalid_type",
                message="Path must be a string",
                severity=ValidationSeverity.CRITICAL,
            )

        # Check for empty paths
        if not path or not path.strip():
            return ValidationResult(
                is_valid=False,
                violation_type="empty_path",
                message="Path cannot be empty",
                severity=ValidationSeverity.HIGH,
            )

        # Check path length
        if len(path) > self.max_path_length:
            return ValidationResult(
                is_valid=False,
                violation_type="path_too_long",
                message=f"Path exceeds maximum length of {self.max_path_length}",
                severity=ValidationSeverity.HIGH,
                details={"length": len(path), "max_length": self.max_path_length},
            )

        # Check for null bytes and control characters
        suspicious_result = self._check_suspicious_patterns(path)
        if suspicious_result:
            if strict or suspicious_result.severity >= ValidationSeverity.HIGH:
                return suspicious_result

        # Check for traversal patterns
        traversal_result = self._check_traversal_patterns(path)
        if traversal_result:
            return traversal_result

        # Normalize and resolve the path
        try:
            normalized = self._normalize_path(path)
        except PathValidationError as e:
            return ValidationResult(
                is_valid=False,
                violation_type=e.violation_type,
                message=str(e),
                severity=ValidationSeverity.HIGH,
            )

        # Check component count
        components = len(Path(normalized).parts)
        if components > self.max_components:
            return ValidationResult(
                is_valid=False,
                violation_type="too_many_components",
                message=f"Path has {components} components, max is {self.max_components}",
                severity=ValidationSeverity.HIGH,
                details={"components": components, "max_components": self.max_components},
            )

        # Check for dangerous components
        dangerous = self._check_dangerous_components(normalized)
        if dangerous:
            return dangerous

        # Check against blocked system paths
        blocked = self._check_blocked_paths(normalized)
        if blocked:
            return blocked

        # Verify path stays within workspace
        boundary_result = self._check_workspace_boundary(normalized)
        if boundary_result:
            return boundary_result

        # Check symlink safety if not following symlinks
        if not self.follow_symlinks:
            symlink_result = self._check_symlink_safety(normalized)
            if symlink_result:
                return symlink_result

        return ValidationResult(
            is_valid=True,
            normalized_path=normalized,
            message="Path validation passed",
        )

    def _check_suspicious_patterns(self, path: str) -> ValidationResult | None:
        """Check for suspicious characters and sequences."""
        for pattern, name, severity in self._suspicious_regex:
            if pattern.search(path):
                return ValidationResult(
                    is_valid=False,
                    violation_type=f"suspicious_{name}",
                    message=f"Suspicious pattern detected: {name}",
                    severity=severity,
                    details={"pattern": name, "matched": pattern.pattern},
                )
        return None

    def _check_traversal_patterns(self, path: str) -> ValidationResult | None:
        """Check for path traversal patterns."""
        for pattern, name in self._traversal_regex:
            if pattern.search(path):
                return ValidationResult(
                    is_valid=False,
                    violation_type=f"path_traversal_{name}",
                    message=f"Path traversal pattern detected: {name}",
                    severity=ValidationSeverity.CRITICAL,
                    details={"pattern": name, "matched": pattern.pattern},
                )
        return None

    def _normalize_path(self, path: str) -> str:
        """Normalize path while preserving security checks."""
        # Block home expansion unless explicitly allowed
        if "~" in path and not self.allow_home_expansion:
            raise PathValidationError(
                "Home directory expansion not allowed",
                "home_expansion_blocked",
                path,
            )

        # Expand user if allowed
        expanded = Path(path).expanduser() if self.allow_home_expansion else Path(path)

        # Handle absolute paths
        if expanded.is_absolute():
            if not self.allow_absolute:
                raise PathValidationError(
                    "Absolute paths not allowed",
                    "absolute_path_blocked",
                    path,
                )
            # Convert to relative from workspace if within workspace
            try:
                relative = expanded.resolve().relative_to(self.workspace)
                return str(relative)
            except ValueError:
                # Path is outside workspace
                if not self.allow_absolute:
                    raise PathValidationError(
                        f"Path outside workspace: {path}",
                        "outside_workspace",
                        path,
                    )
                return str(expanded)

        # Normalize relative path
        normalized = os.path.normpath(str(expanded))
        return normalized

    def _check_dangerous_components(self, path: str) -> ValidationResult | None:
        """Check for dangerous path components."""
        path_obj = Path(path)
        for part in path_obj.parts:
            if part in self.DANGEROUS_COMPONENTS:
                return ValidationResult(
                    is_valid=False,
                    violation_type="dangerous_component",
                    message=f"Dangerous path component: {part}",
                    severity=ValidationSeverity.HIGH,
                    details={"component": part},
                )
        return None

    def _check_blocked_paths(self, path: str) -> ValidationResult | None:
        """Check against blocked system paths."""
        path_lower = path.lower()
        for blocked in self.blocked_paths:
            if path_lower.startswith(blocked.lower()) or blocked.lower() in path_lower:
                return ValidationResult(
                    is_valid=False,
                    violation_type="blocked_system_path",
                    message=f"Access to system path blocked: {blocked}",
                    severity=ValidationSeverity.CRITICAL,
                    details={"blocked_path": blocked},
                )
        return None

    def _check_workspace_boundary(self, path: str) -> ValidationResult | None:
        """Verify path stays within workspace boundary."""
        try:
            full_path = (self.workspace / path).resolve()
            # Check if resolved path is still within workspace
            full_path.relative_to(self.workspace.resolve())
        except (ValueError, RuntimeError) as e:
            return ValidationResult(
                is_valid=False,
                violation_type="workspace_boundary_violation",
                message=f"Path escapes workspace boundary: {e}",
                severity=ValidationSeverity.CRITICAL,
                details={"workspace": str(self.workspace), "path": path},
            )
        return None

    def _check_symlink_safety(self, path: str) -> ValidationResult | None:
        """Check if path contains symlinks that could escape workspace."""
        full_path = self.workspace / path
        current = full_path

        # Walk up the path checking for symlinks
        try:
            while current != self.workspace and current != current.parent:
                if current.is_symlink():
                    target = current.readlink()
                    # Check if symlink target is outside workspace
                    if target.is_absolute():
                        try:
                            target.relative_to(self.workspace)
                        except ValueError:
                            return ValidationResult(
                                is_valid=False,
                                violation_type="symlink_escape",
                                message=f"Symlink points outside workspace: {current} -> {target}",
                                severity=ValidationSeverity.CRITICAL,
                                details={"link": str(current), "target": str(target)},
                            )
                current = current.parent
        except OSError:
            # Path doesn't exist, can't check symlinks
            pass

        return None

    def is_safe(
        self,
        path: str,
        operation: str = "read",
        strict: bool = False,
    ) -> bool:
        """Quick check if path is safe (returns boolean only)."""
        result = self.validate(path, operation, strict)
        return result.is_valid

    def get_safe_path(
        self,
        path: str,
        operation: str = "read",
    ) -> Path:
        """Get validated safe path or raise exception."""
        result = self.validate(path, operation, strict=True)
        if not result.is_valid:
            raise PathValidationError(
                result.message or "Path validation failed",
                result.violation_type or "validation_failed",
                path,
            )
        return join_workspace_normalized_path(self.workspace, result.normalized_path)

    def sanitize(self, path: str) -> str:
        """Sanitize path by removing dangerous components."""
        # Remove null bytes
        sanitized = path.replace("\x00", "")

        # Replace traversal patterns
        for pattern, name in self.TRAVERSAL_PATTERNS:
            sanitized = pattern.sub("_", sanitized)

        # Normalize
        sanitized = os.path.normpath(sanitized)

        # Remove leading slashes unless absolute allowed
        if not self.allow_absolute:
            sanitized = sanitized.lstrip("/\\")

        return sanitized


def create_strict_validator(workspace: Path | str) -> PathValidator:
    """Create a strict validator for maximum security.

    This validator blocks:
    - All absolute paths
    - Home directory expansion
    - Symlink following
    - Any suspicious patterns

    Use this for untrusted user input.
    """
    return PathValidator(
        workspace=workspace,
        allow_absolute=False,
        allow_home_expansion=False,
        follow_symlinks=False,
        max_path_length=1024,
        max_components=64,
    )


def create_permissive_validator(workspace: Path | str) -> PathValidator:
    """Create a permissive validator for internal use.

    This validator allows:
    - Absolute paths within workspace
    - Home expansion
    - Longer paths

    Use this only for trusted internal operations.
    """
    return PathValidator(
        workspace=workspace,
        allow_absolute=True,
        allow_home_expansion=True,
        follow_symlinks=False,
        max_path_length=8192,
        max_components=512,
    )
