"""Unified filesystem interface for Soothe.

This module provides a consistent, abstract interface for filesystem operations
across all Soothe components. It unifies the various filesystem backends and
provides a common API for file operations.
"""

from __future__ import annotations

from .audit_logger import (
    AuditContext,
    AuditEvent,
    AuditEventType,
    AuditLevel,
    AuditLogger,
    AuditLoggerConfig,
    AuditedFilesystem,
)
from .factory import (
    FilesystemConfig,
    FilesystemFactory,
    FilesystemType,
    PathValidationConfig,
    SecurityConfig,
    create_filesystem,
)
from .langchain_adapter import LangChainAdapter
from .local import LocalFilesystem
from .protocol import (
    DeleteResult,
    EditResult,
    FileInfo,
    GlobResult,
    GrepMatch,
    GrepResult,
    ReadResult,
    WriteResult,
)
from .workspace import WorkspaceFilesystem
from .rate_limiter import (
    OperationRateLimiter,
    RateLimitConfig,
    RateLimitExceeded,
    RateLimiter,
    RateLimitStatus,
    RateLimitStrategy,
)
from .exceptions import (
    DirectoryNotEmptyError,
    FilesystemError,
    InvalidPathError,
    NotADirectoryError,
    NotAFileError,
    PathNotFoundError,
    PathTraversalError,
    PermissionDeniedError,
    FileTooLargeError,
)
from .unified import UnifiedFilesystem

__all__ = [
    # Core interface
    "UnifiedFilesystem",
    # Implementations
    "LocalFilesystem",
    "WorkspaceFilesystem",
    # Adapters
    "LangChainAdapter",
    # Factory and configuration
    "FilesystemFactory",
    "FilesystemConfig",
    "FilesystemType",
    "PathValidationConfig",
    "SecurityConfig",
    "create_filesystem",
    # Rate limiting
    "RateLimiter",
    "RateLimitConfig",
    "RateLimitStatus",
    "RateLimitStrategy",
    "RateLimitExceeded",
    "OperationRateLimiter",
    # Audit logging
    "AuditLogger",
    "AuditLoggerConfig",
    "AuditEvent",
    "AuditEventType",
    "AuditLevel",
    "AuditContext",
    "AuditedFilesystem",
    # Protocol types
    "FileInfo",
    "GlobResult",
    "ReadResult",
    "WriteResult",
    "EditResult",
    "DeleteResult",
    "GrepResult",
    "GrepMatch",
    # Exceptions
    "FilesystemError",
    "PathNotFoundError",
    "PermissionDeniedError",
    "PathTraversalError",
    "InvalidPathError",
    "FileTooLargeError",
    "DirectoryNotEmptyError",
    "NotADirectoryError",
    "NotAFileError",
]
