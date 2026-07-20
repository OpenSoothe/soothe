"""LangChain adapter for UnifiedFilesystem interface.

This module provides an adapter that wraps LangChain's file system tools
to implement the UnifiedFilesystem interface, enabling seamless integration
with LangChain-based applications.

Example:
    >>> from soothe_nano.filesystem import create_filesystem
    >>> from soothe_nano.filesystem.langchain_adapter import LangChainAdapter
    >>> # Create underlying filesystem
    >>> fs = create_filesystem("/workspace")
    >>> # Wrap with LangChain adapter
    >>> langchain_fs = LangChainAdapter(fs)
    >>> # Use with LangChain tools
    >>> from langchain_community.tools.file_management import ReadFileTool
    >>> tool = ReadFileTool(fs=langchain_fs)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .local import LocalFilesystem
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
from .unified import UnifiedFilesystem


class LangChainAdapter(UnifiedFilesystem):
    """Adapter that wraps a UnifiedFilesystem for LangChain compatibility.

    This adapter implements the UnifiedFilesystem interface while providing
    additional methods and properties that make it compatible with
    LangChain's file management tools and expectations.

    The adapter delegates all filesystem operations to the underlying
    UnifiedFilesystem implementation, adding any necessary translations
    for LangChain compatibility.

    Attributes:
        _underlying: The wrapped UnifiedFilesystem instance.
        workspace: The root workspace directory.
        virtual_mode: Whether paths are sandboxed to the workspace.
        max_file_size_mb: Maximum file size in megabytes.

    Example:
        >>> from soothe_nano.filesystem import LocalFilesystem
        >>> from soothe_nano.filesystem.langchain_adapter import LangChainAdapter
        >>> underlying = LocalFilesystem("/workspace")
        >>> adapter = LangChainAdapter(underlying)
        >>> # Use UnifiedFilesystem methods
        >>> result = adapter.read("config.json")
        >>> print(result.content)

        >>> # LangChain-compatible properties
        >>> print(adapter.root_dir)

        >>> # Check if LangChain tools are available
        >>> if adapter.has_langchain_tools:
        ...     tool = adapter.get_read_file_tool()
    """

    def __init__(
        self,
        underlying: UnifiedFilesystem,
        *,
        enable_langchain_tools: bool = True,
    ) -> None:
        """Initialize the LangChain adapter.

        Args:
            underlying: The UnifiedFilesystem implementation to wrap.
            enable_langchain_tools: Whether to enable LangChain tool creation.

        Raises:
            TypeError: If underlying is not a UnifiedFilesystem instance.
        """
        if not isinstance(underlying, UnifiedFilesystem):
            raise TypeError(
                f"underlying must be a UnifiedFilesystem, got {type(underlying).__name__}"
            )

        # Initialize with underlying filesystem's settings
        super().__init__(
            workspace=underlying.workspace,
            virtual_mode=underlying.virtual_mode,
            max_file_size_mb=underlying.max_file_size_mb,
        )

        self._underlying = underlying
        self._enable_langchain_tools = enable_langchain_tools
        self._langchain_tools_cache: dict[str, Any] | None = None

    # ========================================================================
    # LangChain-specific Properties
    # ========================================================================

    @property
    def underlying(self) -> UnifiedFilesystem:
        """Get the wrapped UnifiedFilesystem instance."""
        return self._underlying

    @property
    def root_dir(self) -> Path:
        """Get the root directory (LangChain-compatible alias for workspace)."""
        return self.workspace

    @property
    def has_langchain_tools(self) -> bool:
        """Check if LangChain tools are available and enabled."""
        if not self._enable_langchain_tools:
            return False
        try:
            import importlib.util

            return importlib.util.find_spec("langchain_community.tools.file_management") is not None
        except ImportError:
            return False

    # ========================================================================
    # Factory Methods
    # ========================================================================

    @classmethod
    def from_local_filesystem(
        cls,
        workspace: str | Path,
        *,
        virtual_mode: bool = True,
        max_file_size_mb: int = 10,
        enable_langchain_tools: bool = True,
    ) -> LangChainAdapter:
        """Create a LangChainAdapter with a LocalFilesystem backend.

        This is a convenience factory method for quickly creating a
        LangChainAdapter with a LocalFilesystem as the underlying storage.

        Args:
            workspace: Root workspace directory.
            virtual_mode: Whether to sandbox paths to workspace.
            max_file_size_mb: Maximum file size in MB.
            enable_langchain_tools: Whether to enable LangChain tool creation.

        Returns:
            LangChainAdapter instance with LocalFilesystem backend.

        Example:
            >>> adapter = LangChainAdapter.from_local_filesystem("/workspace")
            >>> result = adapter.read("config.json")
        """
        underlying = LocalFilesystem(
            workspace=workspace,
            virtual_mode=virtual_mode,
            max_file_size_mb=max_file_size_mb,
        )
        return cls(underlying, enable_langchain_tools=enable_langchain_tools)

    @classmethod
    def from_workspace(
        cls,
        workspace: str | Path,
        *,
        virtual_mode: bool = True,
        max_file_size_mb: int = 10,
        enable_langchain_tools: bool = True,
    ) -> LangChainAdapter:
        """Create a LangChainAdapter with a WorkspaceFilesystem backend.

        This factory method creates a LangChainAdapter that uses WorkspaceFilesystem
        as the underlying storage, providing better integration with the Soothe
        workspace management system including gitignore-aware globbing and
        workspace context resolution.

        Args:
            workspace: Root workspace directory.
            virtual_mode: Whether to sandbox paths to workspace.
            max_file_size_mb: Maximum file size in MB.
            enable_langchain_tools: Whether to enable LangChain tool creation.

        Returns:
            LangChainAdapter instance with WorkspaceFilesystem backend.

        Example:
            >>> adapter = LangChainAdapter.from_workspace("/workspace")
            >>> result = adapter.read("config.json")
            >>> # Glob results respect .gitignore
            >>> glob_result = adapter.glob("**/*.py")
        """
        from .workspace import WorkspaceFilesystem

        underlying = WorkspaceFilesystem(
            workspace=workspace,
            virtual_mode=virtual_mode,
            max_file_size_mb=max_file_size_mb,
        )
        return cls(underlying, enable_langchain_tools=enable_langchain_tools)

    # ========================================================================
    # Path Operations (delegated to underlying)
    # ========================================================================

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
        return self._underlying.resolve_path(path)

    def exists(self, path: str) -> bool:
        """Check if a path exists.

        Args:
            path: Path to check.

        Returns:
            True if path exists, False otherwise.
        """
        return self._underlying.exists(path)

    def is_file(self, path: str) -> bool:
        """Check if path is a file.

        Args:
            path: Path to check.

        Returns:
            True if path exists and is a file.
        """
        return self._underlying.is_file(path)

    def is_dir(self, path: str) -> bool:
        """Check if path is a directory.

        Args:
            path: Path to check.

        Returns:
            True if path exists and is a directory.
        """
        return self._underlying.is_dir(path)

    # ========================================================================
    # Read Operations (delegated to underlying)
    # ========================================================================

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
        return self._underlying.read(path, offset=offset, limit=limit, encoding=encoding)

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
        return await self._underlying.aread(path, offset=offset, limit=limit, encoding=encoding)

    # ========================================================================
    # Write Operations (delegated to underlying)
    # ========================================================================

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
        return self._underlying.write(path, content, encoding=encoding, backup=backup)

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
        return await self._underlying.awrite(path, content, encoding=encoding, backup=backup)

    # ========================================================================
    # Edit Operations (delegated to underlying)
    # ========================================================================

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
        return self._underlying.edit(path, old_string, new_string, backup=backup)

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
        return await self._underlying.aedit(path, old_string, new_string, backup=backup)

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
        return self._underlying.edit_lines(path, start_line, end_line, new_content, backup=backup)

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
        return await self._underlying.aedit_lines(
            path, start_line, end_line, new_content, backup=backup
        )

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
        return self._underlying.insert_lines(path, line, content, backup=backup)

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
        return await self._underlying.ainsert_lines(path, line, content, backup=backup)

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
        return self._underlying.delete_lines(path, start_line, end_line, backup=backup)

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
        return await self._underlying.adelete_lines(path, start_line, end_line, backup=backup)

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
        return self._underlying.apply_diff(path, diff, backup=backup)

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
        return await self._underlying.aapply_diff(path, diff, backup=backup)

    async def aedit_batched(
        self,
        path: str,
        operations: list[BatchedEditOperation],
        *,
        backup: bool = True,
    ) -> BatchedEditResult:
        """Async apply multiple edit operations to a file in one read/modify/write cycle.

        See ``UnifiedFilesystem.aedit_batched`` for operation semantics.
        """
        return await self._underlying.aedit_batched(path, operations, backup=backup)

    # ========================================================================
    # Directory Operations (delegated to underlying)
    # ========================================================================

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
        return self._underlying.ls(path, include_info=include_info)

    async def als(
        self,
        path: str = ".",
        *,
        include_info: bool = False,
    ) -> list[str] | list[FileInfo]:
        """Async list directory contents.

        See ls() for details.
        """
        return await self._underlying.als(path, include_info=include_info)

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
        return self._underlying.mkdir(path, recursive=recursive, exist_ok=exist_ok)

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
        return await self._underlying.amkdir(path, recursive=recursive, exist_ok=exist_ok)

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
        return self._underlying.rmdir(path, recursive=recursive, backup=backup)

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
        return await self._underlying.armdir(path, recursive=recursive, backup=backup)

    # ========================================================================
    # File Operations (delegated to underlying)
    # ========================================================================

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
        return self._underlying.delete(path, backup=backup)

    async def adelete(
        self,
        path: str,
        *,
        backup: bool = True,
    ) -> DeleteResult:
        """Async delete file.

        See delete() for details.
        """
        return await self._underlying.adelete(path, backup=backup)

    def info(self, path: str) -> FileInfo:
        """Get file/directory information.

        Args:
            path: Path to get info for.

        Returns:
            FileInfo with metadata.

        Raises:
            PathNotFoundError: If path does not exist.
        """
        return self._underlying.info(path)

    async def ainfo(self, path: str) -> FileInfo:
        """Async get file/directory information.

        See info() for details.
        """
        return await self._underlying.ainfo(path)

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
        return self._underlying.copy(src, dst, overwrite=overwrite)

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
        return await self._underlying.acopy(src, dst, overwrite=overwrite)

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
        return self._underlying.move(src, dst, overwrite=overwrite)

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
        return await self._underlying.amove(src, dst, overwrite=overwrite)

    # ========================================================================
    # Search Operations (delegated to underlying)
    # ========================================================================

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
        return self._underlying.glob(pattern, path=path, include_ignored=include_ignored)

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
        return await self._underlying.aglob(pattern, path=path, include_ignored=include_ignored)

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
        return self._underlying.grep(pattern, path=path, glob=glob, output_mode=output_mode)

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
        return await self._underlying.agrep(pattern, path=path, glob=glob, output_mode=output_mode)

    # ========================================================================
    # LangChain Tool Factory Methods
    # ========================================================================

    def get_read_file_tool(self) -> Any:
        """Get LangChain ReadFile tool configured for this filesystem.

        Returns:
            LangChain ReadFileTool instance.

        Raises:
            ImportError: If langchain_community is not installed.
            RuntimeError: If LangChain tools are disabled.
        """
        if not self._enable_langchain_tools:
            raise RuntimeError("LangChain tools are disabled")

        try:
            from langchain_community.tools.file_management import ReadFileTool

            return ReadFileTool(fs=self)
        except ImportError as e:
            raise ImportError(
                "langchain_community is required for LangChain tools. "
                "Install with: pip install langchain_community"
            ) from e

    def get_write_file_tool(self) -> Any:
        """Get LangChain WriteFile tool configured for this filesystem.

        Returns:
            LangChain WriteFileTool instance.

        Raises:
            ImportError: If langchain_community is not installed.
            RuntimeError: If LangChain tools are disabled.
        """
        if not self._enable_langchain_tools:
            raise RuntimeError("LangChain tools are disabled")

        try:
            from langchain_community.tools.file_management import WriteFileTool

            return WriteFileTool(fs=self)
        except ImportError as e:
            raise ImportError(
                "langchain_community is required for LangChain tools. "
                "Install with: pip install langchain_community"
            ) from e

    def get_list_directory_tool(self) -> Any:
        """Get LangChain ListDirectory tool configured for this filesystem.

        Returns:
            LangChain ListDirectoryTool instance.

        Raises:
            ImportError: If langchain_community is not installed.
            RuntimeError: If LangChain tools are disabled.
        """
        if not self._enable_langchain_tools:
            raise RuntimeError("LangChain tools are disabled")

        try:
            from langchain_community.tools.file_management import ListDirectoryTool

            return ListDirectoryTool(fs=self)
        except ImportError as e:
            raise ImportError(
                "langchain_community is required for LangChain tools. "
                "Install with: pip install langchain_community"
            ) from e

    def get_file_tools(self) -> list[Any]:
        """Get all available LangChain file management tools.

        Returns:
            List of LangChain tool instances.

        Raises:
            ImportError: If langchain_community is not installed.
        """
        if not self._enable_langchain_tools:
            return []

        try:
            from langchain_community.tools.file_management import (
                CopyFileTool,
                DeleteFileTool,
                FileSearchTool,
                ListDirectoryTool,
                MoveFileTool,
                ReadFileTool,
                WriteFileTool,
            )

            return [
                ReadFileTool(fs=self),
                WriteFileTool(fs=self),
                ListDirectoryTool(fs=self),
                CopyFileTool(fs=self),
                MoveFileTool(fs=self),
                DeleteFileTool(fs=self),
                FileSearchTool(fs=self),
            ]
        except ImportError:
            return []

    # ========================================================================
    # Context Manager Support
    # ========================================================================

    def __enter__(self) -> LangChainAdapter:
        """Enter context manager."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit context manager."""
        # No cleanup needed, but could be extended
        pass

    def __repr__(self) -> str:
        """Get string representation."""
        return (
            f"LangChainAdapter("
            f"underlying={type(self._underlying).__name__}, "
            f"workspace={self.workspace!r}, "
            f"virtual_mode={self.virtual_mode}"
            f")"
        )
