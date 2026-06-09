"""Filesystem exceptions for UnifiedFilesystem interface."""

from __future__ import annotations

from typing import Any


class FilesystemError(Exception):
    """Base exception for filesystem operations."""

    def __init__(
        self, message: str, *, path: str | None = None, details: dict[str, Any] | None = None
    ) -> None:
        """Initialize filesystem error.

        Args:
            message: Error message.
            path: Path that caused the error, if applicable.
            details: Additional error details.
        """
        super().__init__(message)
        self.path = path
        self.details = details or {}

    def __str__(self) -> str:
        parts = [super().__str__()]
        if self.path:
            parts.append(f" (path: {self.path})")
        return "".join(parts)


class PathNotFoundError(FilesystemError):
    """Raised when a path does not exist."""

    pass


class PermissionDeniedError(FilesystemError):
    """Raised when permission is denied for an operation."""

    pass


class PathTraversalError(FilesystemError):
    """Raised when a path traversal attempt is detected."""

    def __init__(
        self,
        message: str = "Path traversal detected",
        *,
        path: str | None = None,
        attempted_path: str | None = None,
        workspace: str | None = None,
    ) -> None:
        """Initialize path traversal error.

        Args:
            message: Error message.
            path: Original path that was checked.
            attempted_path: Resolved path that attempted traversal.
            workspace: Workspace root that was being protected.
        """
        details: dict[str, Any] = {}
        if attempted_path:
            details["attempted_path"] = attempted_path
        if workspace:
            details["workspace"] = workspace
        super().__init__(message, path=path, details=details)
        self.attempted_path = attempted_path
        self.workspace = workspace


class InvalidPathError(FilesystemError):
    """Raised when a path is invalid (null bytes, control chars, etc.)."""

    def __init__(
        self,
        message: str,
        *,
        path: str | None = None,
        reason: str | None = None,
    ) -> None:
        """Initialize invalid path error.

        Args:
            message: Error message.
            path: Invalid path.
            reason: Specific reason for invalidity.
        """
        details: dict[str, Any] = {}
        if reason:
            details["reason"] = reason
        super().__init__(message, path=path, details=details)
        self.reason = reason


class FileTooLargeError(FilesystemError):
    """Raised when a file exceeds the maximum allowed size."""

    def __init__(
        self,
        message: str | None = None,
        *,
        path: str | None = None,
        size: int | None = None,
        max_size: int | None = None,
    ) -> None:
        """Initialize file too large error.

        Args:
            message: Error message (auto-generated if None).
            path: Path to the file.
            size: Actual file size in bytes.
            max_size: Maximum allowed size in bytes.
        """
        if message is None:
            size_mb = (size or 0) / (1024 * 1024)
            max_mb = (max_size or 0) / (1024 * 1024)
            message = f"File too large: {size_mb:.1f}MB (max: {max_mb:.1f}MB)"
        details: dict[str, Any] = {}
        if size is not None:
            details["size"] = size
        if max_size is not None:
            details["max_size"] = max_size
        super().__init__(message, path=path, details=details)
        self.size = size
        self.max_size = max_size


class DirectoryNotEmptyError(FilesystemError):
    """Raised when attempting to delete a non-empty directory."""

    pass


class NotAFileError(FilesystemError):
    """Raised when a path is expected to be a file but isn't."""

    pass


class NotADirectoryError(FilesystemError):
    """Raised when a path is expected to be a directory but isn't."""

    pass
