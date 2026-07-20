"""Unified filesystem interface for Soothe.

This module provides a consistent, abstract interface for filesystem operations
across all Soothe components. It unifies the various filesystem backends and
provides a common API for file operations.
"""

from __future__ import annotations

from .exceptions import (
    DirectoryNotEmptyError,
    FilesystemError,
    FileTooLargeError,
    InvalidPathError,
    NotADirectoryError,
    NotAFileError,
    PathNotFoundError,
    PathTraversalError,
    PermissionDeniedError,
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
from .unified import UnifiedFilesystem
from .workspace import WorkspaceFilesystem

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
