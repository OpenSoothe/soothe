"""Unified filesystem interface for Soothe.

This module defines the abstract base class for all filesystem operations,
providing a consistent API across different backends and implementations.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from .exceptions import (
    InvalidPathError,
    PathTraversalError,
)
from .protocol import (
    BatchedEditOperation,
    BatchedEditResult,
    DeleteResult,
    EditResult,
    FileInfo,
    GlobResult,
    GrepResult,
    ReadResult,
    WriteResult,
)


class UnifiedFilesystem(ABC):
    """Abstract base class for unified filesystem operations.

    This interface provides a consistent API for filesystem operations across
    all Soothe components. Implementations must handle:

    - Path validation and normalization
    - Security checks (traversal, permissions)
    - Workspace isolation
    - Async/sync operation support
    - Error handling with typed exceptions

    Example:
        >>> class MyFilesystem(UnifiedFilesystem):
        ...     def read(
        ...         self, path: str, *, offset: int = 0, limit: int | None = None
        ...     ) -> ReadResult:
        ...         # Implementation
        ...         pass
        >>> fs = MyFilesystem(workspace="/workspace")
        >>> result = fs.read("config.json")
        >>> print(result.content)

    Attributes:
        workspace: The root workspace directory for this filesystem.
        virtual_mode: Whether to sandbox paths to the workspace.
        max_file_size_mb: Maximum file size in megabytes.
    """

    def __init__(
        self,
        workspace: str | Path,
        *,
        virtual_mode: bool = False,
        max_file_size_mb: int = 10,
    ) -> None:
        """Initialize the filesystem.

        Args:
            workspace: Root workspace directory.
            virtual_mode: Whether to sandbox paths to workspace.
            max_file_size_mb: Maximum file size in MB.
        """
        self._workspace = Path(workspace).resolve()
        self._virtual_mode = virtual_mode
        self._max_file_size_mb = max_file_size_mb

    @property
    def workspace(self) -> Path:
        """Get the workspace root directory."""
        return self._workspace

    @property
    def virtual_mode(self) -> bool:
        """Get virtual mode setting."""
        return self._virtual_mode

    @property
    def max_file_size_mb(self) -> int:
        """Get maximum file size in MB."""
        return self._max_file_size_mb

    @property
    def max_file_size_bytes(self) -> int:
        """Get maximum file size in bytes."""
        return self._max_file_size_mb * 1024 * 1024

    # =======================================================================
    # Path Operations
    # =======================================================================

    @abstractmethod
    def resolve_path(self, path: str) -> Path:
        """Resolve a path relative to workspace.

        Args:
            path: Input path (may be absolute, relative, or virtual).

        Returns:
            Resolved Path object.

        Raises:
            InvalidPathError: If path contains invalid characters.
            PathTraversalError: If path attempts to escape workspace.
        """
        ...

    @abstractmethod
    def exists(self, path: str) -> bool:
        """Check if a path exists.

        Args:
            path: Path to check.

        Returns:
            True if path exists, False otherwise.
        """
        ...

    @abstractmethod
    def is_file(self, path: str) -> bool:
        """Check if path is a file.

        Args:
            path: Path to check.

        Returns:
            True if path exists and is a file.
        """
        ...

    @abstractmethod
    def is_dir(self, path: str) -> bool:
        """Check if path is a directory.

        Args:
            path: Path to check.

        Returns:
            True if path exists and is a directory.
        """
        ...

    # =======================================================================
    # Read Operations
    # =======================================================================

    @abstractmethod
    def read(
        self,
        path: str,
        *,
        offset: int = 0,
        limit: int | None = None,
        encoding: str = "utf-8",
    ) -> ReadResult:
        """Read file contents.

        Args:
            path: Path to read.
            offset: Byte offset to start reading from.
            limit: Maximum bytes to read (None for unlimited).
            encoding: Text encoding for text files.

        Returns:
            ReadResult with content and metadata.

        Raises:
            PathNotFoundError: If file does not exist.
            PermissionDeniedError: If read permission denied.
            FilesystemError: For other errors.
        """
        ...

    @abstractmethod
    async def aread(
        self,
        path: str,
        *,
        offset: int = 0,
        limit: int | None = None,
        encoding: str = "utf-8",
    ) -> ReadResult:
        """Async read file contents.

        See read() for details.
        """
        ...

    # =======================================================================
    # Write Operations
    # =======================================================================

    @abstractmethod
    def write(
        self,
        path: str,
        content: str | bytes,
        *,
        encoding: str = "utf-8",
        backup: bool = False,
    ) -> WriteResult:
        """Write content to file.

        Args:
            path: Path to write.
            content: Content to write (str or bytes).
            encoding: Encoding for text content.
            backup: Whether to create backup before writing.

        Returns:
            WriteResult with operation details.

        Raises:
            PermissionDeniedError: If write permission denied.
            FilesystemError: For other errors.
        """
        ...

    @abstractmethod
    async def awrite(
        self,
        path: str,
        content: str | bytes,
        *,
        encoding: str = "utf-8",
        backup: bool = False,
    ) -> WriteResult:
        """Async write content to file.

        See write() for details.
        """
        ...

    # =======================================================================
    # Edit Operations
    # =======================================================================

    @abstractmethod
    def edit(
        self,
        path: str,
        old_string: str,
        new_string: str,
        *,
        backup: bool = True,
    ) -> EditResult:
        """Replace old_string with new_string in file.

        Args:
            path: Path to edit.
            old_string: String to find.
            new_string: String to replace with.
            backup: Whether to create backup before editing.

        Returns:
            EditResult with operation details.

        Raises:
            PathNotFoundError: If file does not exist.
            FilesystemError: If old_string not found or multiple matches.
        """
        ...

    @abstractmethod
    async def aedit(
        self,
        path: str,
        old_string: str,
        new_string: str,
        *,
        backup: bool = True,
    ) -> EditResult:
        """Async replace old_string with new_string in file.

        See edit() for details.
        """
        ...

    @abstractmethod
    def edit_lines(
        self,
        path: str,
        start_line: int,
        end_line: int,
        new_content: str,
        *,
        backup: bool = True,
    ) -> EditResult:
        """Replace specific line range in file.

        Args:
            path: Path to edit.
            start_line: First line to replace (1-indexed, inclusive).
            end_line: Last line to replace (1-indexed, inclusive).
            new_content: New content to insert.
            backup: Whether to create backup before editing.

        Returns:
            EditResult with operation details.

        Raises:
            PathNotFoundError: If file does not exist.
            FilesystemError: If line range invalid.
        """
        ...

    @abstractmethod
    async def aedit_lines(
        self,
        path: str,
        start_line: int,
        end_line: int,
        new_content: str,
        *,
        backup: bool = True,
    ) -> EditResult:
        """Async replace specific line range in file.

        See edit_lines() for details.
        """
        ...

    @abstractmethod
    def insert_lines(
        self,
        path: str,
        line: int,
        content: str,
        *,
        backup: bool = True,
    ) -> EditResult:
        """Insert content at specific line number.

        Args:
            path: Path to edit.
            line: Line number to insert at (1-indexed).
            content: Content to insert.
            backup: Whether to create backup before editing.

        Returns:
            EditResult with operation details.
        """
        ...

    @abstractmethod
    async def ainsert_lines(
        self,
        path: str,
        line: int,
        content: str,
        *,
        backup: bool = True,
    ) -> EditResult:
        """Async insert content at specific line number.

        See insert_lines() for details.
        """
        ...

    @abstractmethod
    def delete_lines(
        self,
        path: str,
        start_line: int,
        end_line: int,
        *,
        backup: bool = True,
    ) -> EditResult:
        """Delete specific line range from file.

        Args:
            path: Path to edit.
            start_line: First line to delete (1-indexed, inclusive).
            end_line: Last line to delete (1-indexed, inclusive).
            backup: Whether to create backup before editing.

        Returns:
            EditResult with operation details.
        """
        ...

    @abstractmethod
    async def adelete_lines(
        self,
        path: str,
        start_line: int,
        end_line: int,
        *,
        backup: bool = True,
    ) -> EditResult:
        """Async delete specific line range from file.

        See delete_lines() for details.
        """
        ...

    @abstractmethod
    def apply_diff(
        self,
        path: str,
        diff: str,
        *,
        backup: bool = True,
    ) -> EditResult:
        """Apply unified diff patch to file.

        Args:
            path: Path to patch.
            diff: Unified diff content in standard format.
            backup: Whether to create backup before patching.

        Returns:
            EditResult with operation details.

        Raises:
            FilesystemError: If diff doesn't apply cleanly.
        """
        ...

    @abstractmethod
    async def aapply_diff(
        self,
        path: str,
        diff: str,
        *,
        backup: bool = True,
    ) -> EditResult:
        """Async apply unified diff patch to file.

        See apply_diff() for details.
        """
        ...

    @abstractmethod
    async def aedit_batched(
        self,
        path: str,
        operations: list[BatchedEditOperation],
        *,
        backup: bool = True,
    ) -> BatchedEditResult:
        """Apply multiple edit operations to a file in one read/modify/write cycle.

        Operations are applied in order: deletions → insertions → replacements.
        Replacements are sorted by line number descending (bottom-to-top) to preserve
        line indices during modification.

        Args:
            path: Path to the file to edit.
            operations: List of edit operations to apply.
            backup: Whether to create a backup before editing.

        Returns:
            BatchedEditResult with details of all operations applied.

        Raises:
            PathNotFoundError: If file does not exist.
            FilesystemError: If operations have overlapping line ranges.
        """
        ...

    # =======================================================================
    # Directory Operations
    # =======================================================================

    @abstractmethod
    def ls(
        self,
        path: str = ".",
        *,
        include_info: bool = False,
    ) -> list[str] | list[FileInfo]:
        """List directory contents.

        Args:
            path: Directory path to list.
            include_info: Whether to include file metadata.

        Returns:
            List of file names or FileInfo objects.

        Raises:
            PathNotFoundError: If directory does not exist.
            NotADirectoryError: If path is not a directory.
        """
        ...

    @abstractmethod
    async def als(
        self,
        path: str = ".",
        *,
        include_info: bool = False,
    ) -> list[str] | list[FileInfo]:
        """Async list directory contents.

        See ls() for details.
        """
        ...

    @abstractmethod
    def mkdir(
        self,
        path: str,
        *,
        recursive: bool = False,
        exist_ok: bool = False,
    ) -> FileInfo:
        """Create directory.

        Args:
            path: Directory path to create.
            recursive: Whether to create parent directories.
            exist_ok: Whether to succeed if directory exists.

        Returns:
            FileInfo for created directory.

        Raises:
            FilesystemError: If creation fails.
        """
        ...

    @abstractmethod
    async def amkdir(
        self,
        path: str,
        *,
        recursive: bool = False,
        exist_ok: bool = False,
    ) -> FileInfo:
        """Async create directory.

        See mkdir() for details.
        """
        ...

    @abstractmethod
    def rmdir(
        self,
        path: str,
        *,
        recursive: bool = False,
        backup: bool = False,
    ) -> DeleteResult:
        """Remove directory.

        Args:
            path: Directory path to remove.
            recursive: Whether to remove contents recursively.
            backup: Whether to backup before removal.

        Returns:
            DeleteResult with operation details.

        Raises:
            DirectoryNotEmptyError: If directory not empty and recursive=False.
        """
        ...

    @abstractmethod
    async def armdir(
        self,
        path: str,
        *,
        recursive: bool = False,
        backup: bool = False,
    ) -> DeleteResult:
        """Async remove directory.

        See rmdir() for details.
        """
        ...

    # =======================================================================
    # File Operations
    # =======================================================================

    @abstractmethod
    def delete(
        self,
        path: str,
        *,
        backup: bool = True,
    ) -> DeleteResult:
        """Delete file.

        Args:
            path: Path to delete.
            backup: Whether to create backup before deletion.

        Returns:
            DeleteResult with operation details.

        Raises:
            PathNotFoundError: If file does not exist.
            NotAFileError: If path is not a file.
        """
        ...

    @abstractmethod
    async def adelete(
        self,
        path: str,
        *,
        backup: bool = True,
    ) -> DeleteResult:
        """Async delete file.

        See delete() for details.
        """
        ...

    @abstractmethod
    def info(self, path: str) -> FileInfo:
        """Get file/directory information.

        Args:
            path: Path to get info for.

        Returns:
            FileInfo with metadata.

        Raises:
            PathNotFoundError: If path does not exist.
        """
        ...

    @abstractmethod
    async def ainfo(self, path: str) -> FileInfo:
        """Async get file/directory information.

        See info() for details.
        """
        ...

    @abstractmethod
    def copy(
        self,
        src: str,
        dst: str,
        *,
        overwrite: bool = False,
    ) -> FileInfo:
        """Copy file or directory.

        Args:
            src: Source path.
            dst: Destination path.
            overwrite: Whether to overwrite existing destination.

        Returns:
            FileInfo for destination.
        """
        ...

    @abstractmethod
    async def acopy(
        self,
        src: str,
        dst: str,
        *,
        overwrite: bool = False,
    ) -> FileInfo:
        """Async copy file or directory.

        See copy() for details.
        """
        ...

    @abstractmethod
    def move(
        self,
        src: str,
        dst: str,
        *,
        overwrite: bool = False,
    ) -> FileInfo:
        """Move/rename file or directory.

        Args:
            src: Source path.
            dst: Destination path.
            overwrite: Whether to overwrite existing destination.

        Returns:
            FileInfo for destination.
        """
        ...

    @abstractmethod
    async def amove(
        self,
        src: str,
        dst: str,
        *,
        overwrite: bool = False,
    ) -> FileInfo:
        """Async move/rename file or directory.

        See move() for details.
        """
        ...

    # =======================================================================
    # Search Operations
    # =======================================================================

    @abstractmethod
    def glob(
        self,
        pattern: str,
        *,
        path: str = ".",
        include_ignored: bool = False,
    ) -> GlobResult:
        """Glob pattern matching.

        Args:
            pattern: Glob pattern (e.g., "**/*.py").
            path: Directory to search in.
            include_ignored: Whether to include gitignored files.

        Returns:
            GlobResult with matches.
        """
        ...

    @abstractmethod
    async def aglob(
        self,
        pattern: str,
        *,
        path: str = ".",
        include_ignored: bool = False,
    ) -> GlobResult:
        """Async glob pattern matching.

        See glob() for details.
        """
        ...

    @abstractmethod
    def grep(
        self,
        pattern: str,
        *,
        path: str = ".",
        glob: str | None = None,
        output_mode: str = "files_with_matches",
    ) -> GrepResult | list[str] | str:
        """Search for pattern in files.

        Args:
            pattern: Regex pattern to search for.
            path: Directory to search in.
            glob: Optional glob pattern to filter files.
            output_mode: Output format (files_with_matches, content, count).

        Returns:
            GrepResult, list of files, or count string depending on mode.
        """
        ...

    @abstractmethod
    async def agrep(
        self,
        pattern: str,
        *,
        path: str = ".",
        glob: str | None = None,
        output_mode: str = "files_with_matches",
    ) -> GrepResult | list[str] | str:
        """Async search for pattern in files.

        See grep() for details.
        """
        ...

    # =======================================================================
    # Utility Methods
    # =======================================================================

    def _validate_path(self, path: str) -> None:
        """Validate path for security issues.

        This is a helper method that implementations can use.
        Subclasses may override for custom validation.

        Args:
            path: Path to validate.

        Raises:
            InvalidPathError: If path contains invalid characters.
            PathTraversalError: If path attempts traversal.
        """
        if not path:
            raise InvalidPathError("Path cannot be empty", path=path)

        # Check for null bytes
        if "\x00" in path:
            raise InvalidPathError(
                "Path contains null bytes",
                path=path,
                reason="null_bytes",
            )

        # Check for traversal patterns
        normalized = path.replace("\\", "/")
        parts = normalized.split("/")
        if ".." in parts:
            raise PathTraversalError(
                path=path,
                attempted_path=path,
                workspace=str(self.workspace),
            )

        # Check for home directory expansion
        if path.startswith("~"):
            raise InvalidPathError(
                "Home directory references not allowed",
                path=path,
                reason="home_reference",
            )

    def _is_within_workspace(self, path: Path) -> bool:
        """Check if a resolved path is within the workspace.

        Args:
            path: Resolved Path to check.

        Returns:
            True if path is within workspace.
        """
        try:
            path.resolve().relative_to(self.workspace)
            return True
        except ValueError:
            return False
