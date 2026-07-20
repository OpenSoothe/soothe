"""Normalized path backend for workspace filesystem operations.

This module provides workspace-aware filesystem operations using the native
Soothe UnifiedFilesystem interface with soothe_deepagents compatibility.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from soothe_deepagents.backends.protocol import (
    EditResult,
    FileData,
    LsResult,
    ReadResult,
    WriteResult,
)

logger = logging.getLogger(__name__)

_DEFAULT_READ_LINE_LIMIT = 2000


def _coerce_fs_grep_to_da_matches(result: Any) -> list[dict[str, Any]]:
    """Convert filesystem grep results to soothe_deepagents ``GrepMatch`` dicts."""
    from soothe_nano.filesystem.protocol import GrepResult as FsGrepResult

    matches: list[dict[str, Any]] = []
    if isinstance(result, FsGrepResult):
        for match in result.matches:
            matches.append(
                {
                    "path": match.path,
                    "line": match.line_number,
                    "text": match.line_content,
                }
            )
    elif isinstance(result, list):
        for item in result:
            if isinstance(item, dict):
                matches.append(item)
            elif isinstance(item, str):
                matches.append({"path": item, "line": 0, "text": ""})
    elif isinstance(result, str) and result:
        for line in result.split("\n"):
            if line:
                matches.append({"path": line, "line": 0, "text": ""})
    return matches


def _read_result_for_path(
    fs: Any,
    normalized: str,
    *,
    offset: int,
    limit: int,
    display_path: str,
) -> ReadResult:
    """Build soothe_deepagents ``ReadResult`` using line-based offset/limit semantics."""
    from soothe_nano.filesystem.exceptions import (
        FilesystemError,
        NotAFileError,
        PathNotFoundError,
    )

    try:
        raw = fs.read(normalized)
    except PathNotFoundError:
        return ReadResult(error=f"File '{display_path}' not found")
    except NotAFileError:
        return ReadResult(error=f"File '{display_path}' not found")
    except FilesystemError as exc:
        return ReadResult(error=str(exc))

    if raw.is_binary:
        return ReadResult(
            file_data=FileData(content=raw.content, encoding="base64"),
        )

    content = raw.content
    if not content:
        return ReadResult(file_data=FileData(content="", encoding="utf-8"))

    lines = content.splitlines(keepends=True)
    start_idx = max(offset, 0)
    end_idx = min(start_idx + limit, len(lines))
    if start_idx >= len(lines):
        return ReadResult(
            error=(
                f"Line offset {offset} exceeds file length ({len(lines)} lines). "
                f"Offset is 0-indexed: use offset={max(len(lines) - 1, 0)} to read the last line."
            ),
        )

    return ReadResult(
        file_data=FileData(content="".join(lines[start_idx:end_idx]), encoding="utf-8"),
    )


class NormalizedPathBackend:
    """Wrapper that normalizes paths to workspace-relative.

    When virtual_mode=False (allow_paths_outside_workspace=True), absolute paths
    like '/' would resolve to the actual root filesystem. This wrapper ensures
    such paths are treated as workspace-relative.

    Uses native UnifiedFilesystem.
    """

    def __init__(
        self,
        root_dir: Path,
        virtual_mode: bool = False,
        max_file_size_mb: int = 10,
    ) -> None:
        """Initialize the normalized path backend.

        Args:
            root_dir: Root workspace directory.
            virtual_mode: Whether to sandbox paths to workspace.
            max_file_size_mb: Maximum file size in MB.
        """
        self._root_dir = Path(root_dir)
        self._virtual_mode = virtual_mode
        self._max_file_size_mb = max_file_size_mb

        # Use WorkspaceFilesystem (not bare LocalFilesystem) so glob gets
        # gitignore filtering, result caps, and host-absolute path output.
        from soothe_nano.filesystem.workspace import WorkspaceFilesystem

        self._fs = WorkspaceFilesystem(
            workspace=root_dir,
            virtual_mode=virtual_mode,
            max_file_size_mb=max_file_size_mb,
        )

    @property
    def cwd(self) -> str:
        """Get current working directory (workspace root)."""
        return str(self._root_dir)

    @property
    def virtual_mode(self) -> bool:
        """Get virtual mode setting."""
        return self._virtual_mode

    def _normalize_path(self, path: str) -> str:
        """Normalize path to be workspace-relative (RFC-103).

        Args:
            path: Input path (may be '/', absolute, or relative).

        Returns:
            Normalized path that's safe for the backend.
        """
        if not path or path.strip() in {"", ".", "/"}:
            return "."

        expanded = Path(path.strip()).expanduser()

        if expanded.is_absolute():
            abs_str = str(expanded.resolve())
            try:
                rel = expanded.resolve().relative_to(self._root_dir.resolve())
            except ValueError:
                # Path is outside workspace
                if self._virtual_mode:
                    from soothe_nano.workspace.tool_path_resolution import (
                        should_use_virtual_path_resolution,
                    )

                    if should_use_virtual_path_resolution(path.strip(), self._root_dir):
                        relative = abs_str.lstrip("/")
                        return relative or "."
                    return abs_str
                return abs_str
            if self._virtual_mode:
                return rel.as_posix()
            return abs_str

        return path.strip()

    def resolve_os_path(self, path: str) -> Path:
        """Resolve a logical path to an absolute on-disk path under the workspace."""
        normalized = self._normalize_path(path)
        return self._fs.resolve_path(normalized, allow_host_absolute=True)

    def read(
        self,
        path: str,
        offset: int = 0,
        limit: int | None = None,
    ) -> ReadResult:
        """Read file contents for a line range (soothe_deepagents BackendProtocol)."""
        normalized = self._normalize_path(path)
        line_limit = limit if limit is not None else _DEFAULT_READ_LINE_LIMIT
        return _read_result_for_path(
            self._fs,
            normalized,
            offset=offset,
            limit=line_limit,
            display_path=path,
        )

    async def aread(
        self,
        path: str,
        offset: int = 0,
        limit: int | None = None,
    ) -> ReadResult:
        """Async read file contents for a line range (soothe_deepagents BackendProtocol)."""
        normalized = self._normalize_path(path)
        line_limit = limit if limit is not None else _DEFAULT_READ_LINE_LIMIT
        return _read_result_for_path(
            self._fs,
            normalized,
            offset=offset,
            limit=line_limit,
            display_path=path,
        )

    def write(self, path: str, content: str | bytes) -> WriteResult:
        """Write content to file (soothe_deepagents BackendProtocol)."""
        from soothe_nano.filesystem.exceptions import FilesystemError

        normalized = self._normalize_path(path)
        try:
            result = self._fs.write(normalized, content)
        except FilesystemError as exc:
            return WriteResult(error=str(exc))
        return WriteResult(path=result.path)

    async def awrite(self, path: str, content: str | bytes) -> WriteResult:
        """Async write content to file (soothe_deepagents BackendProtocol)."""
        from soothe_nano.filesystem.exceptions import FilesystemError

        normalized = self._normalize_path(path)
        try:
            result = await self._fs.awrite(normalized, content)
        except FilesystemError as exc:
            return WriteResult(error=str(exc))
        return WriteResult(path=result.path)

    def edit(
        self,
        path: str,
        old_string: str | None = None,
        new_string: str | None = None,
        edits: list[dict[str, Any]] | None = None,
        *,
        replace_all: bool = False,
    ) -> EditResult:
        """Apply edits to file.

        Returns EditResult for soothe_deepagents.middleware.filesystem compatibility.
        """
        normalized = self._normalize_path(path)

        try:
            if edits:
                # Handle edits list format
                total_occurrences = 0
                for edit_item in edits:
                    old = edit_item.get("old_string", "")
                    new = edit_item.get("new_string", "")
                    result = self._fs.edit(normalized, old, new)
                    # Soothe filesystem returns EditResult without error field,
                    # soothe_deepagents returns EditResult with error field
                    if hasattr(result, "error") and result.error:
                        return EditResult(error=result.error)
                    total_occurrences += 1
                return EditResult(path=normalized, occurrences=total_occurrences)
            elif old_string is not None and new_string is not None:
                result = self._fs.edit(normalized, old_string, new_string)
                # Check if result has error attribute (soothe_deepagents style)
                if hasattr(result, "error") and result.error:
                    return EditResult(error=result.error)
                # Soothe EditResult has path and lines_changed
                return EditResult(path=normalized, occurrences=1)
            else:
                return EditResult(error="No edits provided")
        except Exception as e:
            logger.warning("edit error for %s: %s", path, e)
            return EditResult(error=str(e))

    async def aedit(
        self,
        path: str,
        old_string: str | None = None,
        new_string: str | None = None,
        edits: list[dict[str, Any]] | None = None,
        *,
        replace_all: bool = False,
    ) -> EditResult:
        """Async apply edits to file.

        Returns EditResult for soothe_deepagents.middleware.filesystem compatibility.
        """
        normalized = self._normalize_path(path)

        try:
            if edits:
                total_occurrences = 0
                for edit_item in edits:
                    old = edit_item.get("old_string", "")
                    new = edit_item.get("new_string", "")
                    result = await self._fs.aedit(normalized, old, new)
                    if hasattr(result, "error") and result.error:
                        return EditResult(error=result.error)
                    total_occurrences += 1
                return EditResult(path=normalized, occurrences=total_occurrences)
            elif old_string is not None and new_string is not None:
                result = await self._fs.aedit(normalized, old_string, new_string)
                if hasattr(result, "error") and result.error:
                    return EditResult(error=result.error)
                return EditResult(path=normalized, occurrences=1)
            else:
                return EditResult(error="No edits provided")
        except Exception as e:
            logger.warning("aedit error for %s: %s", path, e)
            return EditResult(error=str(e))

    async def aedit_batched(
        self,
        path: str,
        operations: list[Any],
        *,
        backup: bool = True,
    ) -> Any:
        """Async apply multiple edit operations to a file in one read/modify/write cycle (IG-517).

        Args:
            path: Path to the file to edit.
            operations: List of BatchedEditOperation objects.
            backup: Whether to create a backup before editing.

        Returns:
            BatchedEditResult with details of all operations applied.
        """
        from soothe_nano.filesystem.protocol import BatchedEditResult

        normalized = self._normalize_path(path)

        try:
            result = await self._fs.aedit_batched(normalized, operations, backup=backup)
            return result
        except Exception as e:
            logger.warning("aedit_batched error for %s: %s", path, e)
            return BatchedEditResult(path=normalized, error=str(e))

    def ls(self, path: str = ".") -> LsResult:
        """List directory contents.

        Returns LsResult for soothe_deepagents.middleware.filesystem compatibility.
        """
        normalized = self._normalize_path(path)
        try:
            # Use include_info=True to get is_dir information
            result = self._fs.ls(normalized, include_info=True)
            if isinstance(result, list) and result:
                # Handle FileInfo list - convert to dicts
                entries = [
                    {
                        "path": item.path if hasattr(item, "path") else str(item),
                        "is_dir": item.is_dir if hasattr(item, "is_dir") else False,
                        "size": item.size if hasattr(item, "size") else 0,
                        "modified_at": (
                            item.modified_at.isoformat()
                            if hasattr(item, "modified_at") and item.modified_at
                            else None
                        ),
                    }
                    for item in result
                ]
            else:
                entries = []
            return LsResult(entries=entries)
        except Exception as e:
            logger.warning("ls error for %s: %s", path, e)
            return LsResult(error=str(e), entries=[])

    async def als(self, path: str = ".") -> LsResult:
        """Async list directory contents.

        Returns LsResult for soothe_deepagents.middleware.filesystem compatibility.
        """
        normalized = self._normalize_path(path)
        try:
            # Use include_info=True to get is_dir information
            result = await self._fs.als(normalized, include_info=True)
            if isinstance(result, list) and result:
                entries = [
                    {
                        "path": item.path if hasattr(item, "path") else str(item),
                        "is_dir": item.is_dir if hasattr(item, "is_dir") else False,
                        "size": item.size if hasattr(item, "size") else 0,
                        "modified_at": (
                            item.modified_at.isoformat()
                            if hasattr(item, "modified_at") and item.modified_at
                            else None
                        ),
                    }
                    for item in result
                ]
            else:
                entries = []
            return LsResult(entries=entries)
        except Exception as e:
            logger.warning("als error for %s: %s", path, e)
            return LsResult(error=str(e), entries=[])

    def ls_info(self, path: str = ".") -> list[dict[str, Any]]:
        """List directory with file info."""
        normalized = self._normalize_path(path)
        result = self._fs.ls(normalized, include_info=True)

        if not result:
            return []

        if isinstance(result[0], str):
            # Convert string list to FileInfo dicts
            return [{"path": p, "is_dir": False} for p in result]

        # Convert FileInfo objects to dicts
        return [
            {
                "path": item.path,
                "is_dir": item.is_dir,
                "size": item.size,
                "modified_at": item.modified_at.isoformat() if item.modified_at else None,
            }
            for item in result
        ]

    async def als_info(self, path: str = ".") -> list[dict[str, Any]]:
        """Async list directory with file info."""
        normalized = self._normalize_path(path)
        result = await self._fs.als(normalized, include_info=True)

        if not result:
            return []

        if isinstance(result[0], str):
            return [{"path": p, "is_dir": False} for p in result]

        return [
            {
                "path": item.path,
                "is_dir": item.is_dir,
                "size": item.size,
                "modified_at": item.modified_at.isoformat() if item.modified_at else None,
            }
            for item in result
        ]

    def glob(self, pattern: str, path: str = "/") -> Any:
        """Glob pattern matching.

        Returns soothe_deepagents-compatible GlobResult with FileInfo dicts.
        """
        from soothe_deepagents.backends.protocol import GlobResult as DaGlobResult

        normalized = self._normalize_path(path)
        result = self._fs.glob(pattern, path=normalized)

        # Convert string matches to FileInfo dicts for soothe_deepagents compatibility
        # soothe_deepagents expects matches: list[FileInfo] where FileInfo is a TypedDict with "path" key
        file_infos = [{"path": p, "is_dir": False} for p in (result.matches or [])]

        return DaGlobResult(
            error=result.error,
            matches=file_infos,
        )

    async def aglob(self, pattern: str, path: str = "/") -> Any:
        """Async glob pattern matching.

        Returns soothe_deepagents-compatible GlobResult with FileInfo dicts.
        """
        from soothe_deepagents.backends.protocol import GlobResult as DaGlobResult

        normalized = self._normalize_path(path)
        result = await self._fs.aglob(pattern, path=normalized)

        # Convert string matches to FileInfo dicts for soothe_deepagents compatibility
        file_infos = [{"path": p, "is_dir": False} for p in (result.matches or [])]

        return DaGlobResult(
            error=result.error,
            matches=file_infos,
        )

    def grep(
        self,
        pattern: str,
        path: str = ".",
        output_mode: str = "files_with_matches",
        glob: str | None = None,
    ) -> Any:
        """Search for pattern in files.

        Returns soothe_deepagents-compatible GrepResult.

        Args:
            pattern: Search pattern.
            path: Directory to search.
            output_mode: Output format.
            glob: Glob pattern to filter files (soothe_deepagents parameter name).
        """
        from soothe_deepagents.backends.protocol import GrepResult as DaGrepResult

        from soothe_nano.filesystem.protocol import GrepResult as FsGrepResult

        normalized = self._normalize_path(path)
        try:
            result = self._fs.grep(pattern, path=normalized, glob=glob, output_mode=output_mode)

            matches = _coerce_fs_grep_to_da_matches(result)
            error: str | None = None
            if isinstance(result, FsGrepResult):
                error = result.error

            return DaGrepResult(error=error, matches=matches)
        except Exception as e:
            logger.warning("grep error for %s: %s", path, e)
            return DaGrepResult(error=str(e), matches=None)

    async def agrep(
        self,
        pattern: str,
        path: str = ".",
        output_mode: str = "files_with_matches",
        glob: str | None = None,
    ) -> Any:
        """Async search for pattern in files.

        Returns soothe_deepagents-compatible GrepResult.

        Args:
            pattern: Search pattern.
            path: Directory to search.
            output_mode: Output format.
            glob: Glob pattern to filter files (soothe_deepagents parameter name).
        """
        from soothe_deepagents.backends.protocol import GrepResult as DaGrepResult

        from soothe_nano.filesystem.protocol import GrepResult as FsGrepResult

        normalized = self._normalize_path(path)
        try:
            result = await self._fs.agrep(
                pattern, path=normalized, glob=glob, output_mode=output_mode
            )

            matches = _coerce_fs_grep_to_da_matches(result)
            error: str | None = None
            if isinstance(result, FsGrepResult):
                error = result.error

            return DaGrepResult(error=error, matches=matches)
        except Exception as e:
            logger.warning("agrep error for %s: %s", path, e)
            return DaGrepResult(error=str(e), matches=None)

    def delete(self, path: str) -> str:
        """Delete file or directory."""
        normalized = self._normalize_path(path)
        # Exceptions are raised directly by the filesystem
        self._fs.delete(normalized)
        return normalized

    async def adelete(self, path: str) -> str:
        """Async delete file or directory."""
        normalized = self._normalize_path(path)
        # Exceptions are raised directly by the filesystem
        await self._fs.adelete(normalized)
        return normalized

    def exists(self, path: str) -> bool:
        """Check if path exists."""
        normalized = self._normalize_path(path)
        return self._fs.exists(normalized)

    def is_file(self, path: str) -> bool:
        """Check if path is a file."""
        normalized = self._normalize_path(path)
        return self._fs.is_file(normalized)

    def is_dir(self, path: str) -> bool:
        """Check if path is a directory."""
        normalized = self._normalize_path(path)
        return self._fs.is_dir(normalized)


class WorkspaceAwareBackend:
    """Filesystem backend that resolves workspace from context.

    This backend is designed to be used as a callable factory for middleware.
    When called with a runtime, it reads the workspace from runtime config
    and returns the appropriate filesystem backend.

    Uses native UnifiedFilesystem.
    """

    def __init__(
        self,
        default_root_dir: Path,
        virtual_mode: bool = False,
        max_file_size_mb: int = 10,
    ) -> None:
        """Initialize the workspace-aware backend.

        Args:
            default_root_dir: Default workspace when no workspace in config.
            virtual_mode: Whether to sandbox paths to workspace.
            max_file_size_mb: Maximum file size in MB.
        """
        self._default_root_dir = default_root_dir
        self._virtual_mode = virtual_mode
        self._max_file_size_mb = max_file_size_mb

        # Create the default backend
        self._default_backend = NormalizedPathBackend(
            root_dir=default_root_dir,
            virtual_mode=virtual_mode,
            max_file_size_mb=max_file_size_mb,
        )

    def __call__(self, runtime: Any) -> NormalizedPathBackend:
        """Called by middleware to get backend for tool execution.

        Args:
            runtime: ToolRuntime with config containing workspace.

        Returns:
            NormalizedPathBackend for the tool's workspace.
        """
        from soothe_nano.workspace.runtime_resolution import (
            resolve_workspace_for_tool_execution,
        )

        workspace = resolve_workspace_for_tool_execution(
            runtime=runtime,
            fallback=self._default_backend._root_dir,
            use_langgraph_config=True,
        )
        if workspace is not None:
            return get_workspace_backend(
                workspace=workspace,
                virtual_mode=self._virtual_mode,
                max_file_size_mb=self._max_file_size_mb,
            )

        return self._default_backend

    def _get_backend(self) -> NormalizedPathBackend:
        """Get backend for direct method calls (non-tool operations).

        Returns:
            NormalizedPathBackend for current context.
        """
        from soothe_nano.workspace.framework_filesystem import FrameworkFilesystem

        current_workspace = FrameworkFilesystem.get_current_workspace()
        if current_workspace:
            return get_workspace_backend(
                workspace=current_workspace,
                virtual_mode=self._virtual_mode,
                max_file_size_mb=self._max_file_size_mb,
            )
        return self._default_backend

    # Delegate all methods to the resolved backend

    def read(
        self,
        path: str,
        offset: int = 0,
        limit: int | None = None,
    ) -> ReadResult:
        """Read file contents for a line range (soothe_deepagents BackendProtocol)."""
        return self._get_backend().read(path, offset, limit)

    async def aread(
        self,
        path: str,
        offset: int = 0,
        limit: int | None = None,
    ) -> ReadResult:
        """Async read file contents for a line range (soothe_deepagents BackendProtocol)."""
        return await self._get_backend().aread(path, offset, limit)

    def write(self, path: str, content: str | bytes) -> WriteResult:
        """Write content to file (soothe_deepagents BackendProtocol)."""
        return self._get_backend().write(path, content)

    async def awrite(self, path: str, content: str | bytes) -> WriteResult:
        """Async write content to file (soothe_deepagents BackendProtocol)."""
        return await self._get_backend().awrite(path, content)

    def edit(
        self,
        path: str,
        edits: list[dict[str, Any]] | None = None,
        old_string: str | None = None,
        new_string: str | None = None,
        *,
        replace_all: bool = False,
    ) -> EditResult:
        """Apply edits to file.

        Returns EditResult for soothe_deepagents.middleware.filesystem compatibility.
        """
        if edits:
            return self._get_backend().edit(path, edits=edits, replace_all=replace_all)
        return self._get_backend().edit(
            path, old_string=old_string, new_string=new_string, replace_all=replace_all
        )

    async def aedit(
        self,
        path: str,
        edits: list[dict[str, Any]] | None = None,
        old_string: str | None = None,
        new_string: str | None = None,
        *,
        replace_all: bool = False,
    ) -> EditResult:
        """Async apply edits to file.

        Returns EditResult for soothe_deepagents.middleware.filesystem compatibility.
        """
        if edits:
            return await self._get_backend().aedit(path, edits=edits, replace_all=replace_all)
        return await self._get_backend().aedit(
            path, old_string=old_string, new_string=new_string, replace_all=replace_all
        )

    def ls(self, path: str = ".") -> LsResult:
        """List directory contents.

        Returns LsResult for soothe_deepagents.middleware.filesystem compatibility.
        """
        return self._get_backend().ls(path)

    async def als(self, path: str = ".") -> LsResult:
        """Async list directory contents.

        Returns LsResult for soothe_deepagents.middleware.filesystem compatibility.
        """
        return await self._get_backend().als(path)

    def ls_info(self, path: str = ".") -> list[dict[str, Any]]:
        """List directory with file info."""
        return self._get_backend().ls_info(path)

    async def als_info(self, path: str = ".") -> list[dict[str, Any]]:
        """Async list directory with file info."""
        return await self._get_backend().als_info(path)

    def glob(self, pattern: str, path: str = "/") -> Any:
        """Glob pattern matching."""
        return self._get_backend().glob(pattern, path)

    async def aglob(self, pattern: str, path: str = "/") -> Any:
        """Async glob pattern matching."""
        return await self._get_backend().aglob(pattern, path)

    def grep(
        self,
        pattern: str,
        path: str = ".",
        output_mode: str = "files_with_matches",
        glob: str | None = None,
    ) -> Any:
        """Search for pattern in files."""
        return self._get_backend().grep(pattern, path, output_mode, glob)

    async def agrep(
        self,
        pattern: str,
        path: str = ".",
        output_mode: str = "files_with_matches",
        glob: str | None = None,
    ) -> Any:
        """Async search for pattern in files."""
        return await self._get_backend().agrep(pattern, path, output_mode, glob)

    def delete(self, path: str) -> str:
        """Delete file or directory."""
        return self._get_backend().delete(path)

    async def adelete(self, path: str) -> str:
        """Async delete file or directory."""
        return await self._get_backend().adelete(path)


# Global cache for workspace backends (shared across all instances)
_backend_cache: dict[str, NormalizedPathBackend] = {}


def get_workspace_backend(
    workspace: Path,
    virtual_mode: bool = False,
    max_file_size_mb: int = 10,
) -> NormalizedPathBackend:
    """Get or create a cached NormalizedPathBackend for a workspace.

    This function caches backends by workspace path to avoid creating multiple
    instances for the same workspace. Each unique workspace gets its own backend
    with the specified virtual_mode and max_file_size_mb settings.

    Args:
        workspace: The workspace directory path.
        virtual_mode: Whether to sandbox paths to workspace.
        max_file_size_mb: Maximum file size in MB.

    Returns:
        Cached NormalizedPathBackend instance.
    """
    cache_key = f"{workspace}:{virtual_mode}:{max_file_size_mb}"

    if cache_key not in _backend_cache:
        _backend_cache[cache_key] = NormalizedPathBackend(
            root_dir=workspace,
            virtual_mode=virtual_mode,
            max_file_size_mb=max_file_size_mb,
        )

    return _backend_cache[cache_key]


def clear_workspace_backend_cache() -> None:
    """Clear the workspace backend cache.

    Useful for testing or when workspaces are removed.
    """
    _backend_cache.clear()
