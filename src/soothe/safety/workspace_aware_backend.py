"""Workspace-aware filesystem backend for thread-specific workspace (RFC-103).

This module provides a backend wrapper that resolves the correct workspace
from the ToolRuntime.config at operation time, enabling per-thread workspace isolation.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from deepagents.backends.filesystem import FilesystemBackend

if TYPE_CHECKING:
    from deepagents.backends.protocol import BackendProtocol

logger = logging.getLogger(__name__)

# Global cache for workspace backends (shared across all instances)
_backend_cache: dict[str, FilesystemBackend] = {}


def get_workspace_backend(
    workspace: Path | str,
    virtual_mode: bool = False,  # noqa: FBT001, FBT002
    max_file_size_mb: int = 10,
) -> FilesystemBackend:
    """Get or create a FilesystemBackend for the given workspace.

    Args:
        workspace: Workspace directory path.
        virtual_mode: Whether to sandbox paths to workspace.
        max_file_size_mb: Maximum file size in MB.

    Returns:
        FilesystemBackend instance for the workspace.
    """
    workspace_str = str(workspace)
    if workspace_str not in _backend_cache:
        _backend_cache[workspace_str] = FilesystemBackend(
            root_dir=workspace,
            virtual_mode=virtual_mode,
            max_file_size_mb=max_file_size_mb,
        )
    return _backend_cache[workspace_str]


class WorkspaceAwareBackend:
    """Filesystem backend that resolves workspace from ToolRuntime.config.

    This backend is designed to be used as a callable factory for deepagents
    FilesystemMiddleware. When called with a ToolRuntime, it reads the workspace
    from runtime.config["configurable"]["workspace"] and returns the appropriate
    FilesystemBackend.

    For non-tool operations (framework internal use), it falls back to a default
    workspace or uses the ContextVar if set.
    """

    def __init__(
        self,
        default_root_dir: Path,
        virtual_mode: bool = False,  # noqa: FBT001, FBT002
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
        self._default_backend = get_workspace_backend(
            default_root_dir,
            virtual_mode,
            max_file_size_mb,
        )

    def __call__(self, runtime: Any) -> FilesystemBackend:
        """Called by FilesystemMiddleware to get backend for tool execution.

        This is the factory interface used by deepagents. It reads workspace
        from the runtime config (passed through LangGraph's configurable).

        Args:
            runtime: ToolRuntime with config containing workspace.

        Returns:
            FilesystemBackend for the tool's workspace.
        """
        # Try to get workspace from runtime.config (ToolRuntime case)
        if hasattr(runtime, "config") and runtime.config:
            configurable = runtime.config.get("configurable", {})
            workspace = configurable.get("workspace")
            if workspace:
                logger.debug("Backend factory (ToolRuntime): workspace=%s", workspace)
                return get_workspace_backend(
                    Path(workspace),
                    self._virtual_mode,
                    self._max_file_size_mb,
                )

        # For Runtime (middleware), use get_config() from langgraph.config
        # Runtime does NOT have a config attribute - see langgraph.runtime docs
        try:
            from langgraph.config import get_config

            config = get_config()
            if config:
                configurable = config.get("configurable", {})
                workspace = configurable.get("workspace")
                if workspace:
                    logger.debug("Backend factory (Runtime): workspace=%s", workspace)
                    return get_workspace_backend(
                        Path(workspace),
                        self._virtual_mode,
                        self._max_file_size_mb,
                    )
        except Exception:
            logger.debug("get_config() failed, falling back to ContextVar")

        # Fallback to ContextVar (for non-tool operations)
        from soothe.safety.filesystem import FrameworkFilesystem

        current_workspace = FrameworkFilesystem.get_current_workspace()
        if current_workspace:
            logger.debug("Backend factory (ContextVar): workspace=%s", current_workspace)
            return get_workspace_backend(
                current_workspace,
                self._virtual_mode,
                self._max_file_size_mb,
            )

        # Use default
        logger.debug("Backend factory: using default workspace=%s", self._default_root_dir)
        return self._default_backend

    def _get_backend(self) -> FilesystemBackend:
        """Get backend for direct method calls (non-tool operations).

        Returns:
            FilesystemBackend for current context.
        """
        from soothe.safety.filesystem import FrameworkFilesystem

        current_workspace = FrameworkFilesystem.get_current_workspace()
        if current_workspace:
            return get_workspace_backend(
                current_workspace,
                self._virtual_mode,
                self._max_file_size_mb,
            )
        return self._default_backend

    # Delegate all FilesystemBackend methods to the resolved backend

    def read(self, path: str, offset: int = 0, limit: int = 2000) -> str:
        """Read file contents."""
        return self._get_backend().read(path, offset, limit)

    async def aread(self, path: str, offset: int = 0, limit: int = 2000) -> str:
        """Async read file contents."""
        return await self._get_backend().aread(path, offset, limit)

    def write(self, path: str, content: str | bytes) -> str:
        """Write content to file."""
        return self._get_backend().write(path, content)

    async def awrite(self, path: str, content: str | bytes) -> str:
        """Async write content to file."""
        return await self._get_backend().awrite(path, content)

    def edit(
        self,
        path: str,
        edits: list[dict[str, Any]],
        path_edits: list[dict[str, Any]] | None = None,
    ) -> str:
        """Apply edits to file."""
        return self._get_backend().edit(path, edits, path_edits)

    async def aedit(
        self,
        path: str,
        edits: list[dict[str, Any]],
        path_edits: list[dict[str, Any]] | None = None,
    ) -> str:
        """Async apply edits to file."""
        return await self._get_backend().aedit(path, edits, path_edits)

    def ls(self, path: str) -> list[str]:
        """List directory contents."""
        return self._get_backend().ls(path)

    async def als(self, path: str) -> list[str]:
        """Async list directory contents."""
        return await self._get_backend().als(path)

    def ls_info(self, path: str) -> list[dict[str, Any]]:
        """List directory with file info."""
        return self._get_backend().ls_info(path)

    async def als_info(self, path: str) -> list[dict[str, Any]]:
        """Async list directory with file info."""
        return await self._get_backend().als_info(path)

    def glob(self, pattern: str) -> list[str]:
        """Glob pattern matching."""
        return self._get_backend().glob(pattern)

    async def aglob(self, pattern: str) -> list[str]:
        """Async glob pattern matching."""
        return await self._get_backend().aglob(pattern)

    def glob_info(self, pattern: str, path: str = "/") -> list[dict[str, Any]]:
        """Glob pattern matching with file info."""
        backend = self._get_backend()
        logger.debug("glob_info: pattern=%s, path=%s, backend.cwd=%s", pattern, path, backend.cwd)
        return backend.glob_info(pattern, path)

    async def aglob_info(self, pattern: str, path: str = "/") -> list[dict[str, Any]]:
        """Async glob pattern matching with file info."""
        backend = self._get_backend()
        logger.debug("aglob_info: pattern=%s, path=%s, backend.cwd=%s", pattern, path, backend.cwd)
        result = await backend.aglob_info(pattern, path)
        logger.debug("aglob_info result: %d files found", len(result))
        return result

    def grep(
        self,
        path: str,
        pattern: str,
        output_mode: str = "files_with_matches",
        include: str | None = None,
    ) -> str:
        """Grep for pattern in files."""
        return self._get_backend().grep(path, pattern, output_mode, include)

    async def agrep(
        self,
        path: str,
        pattern: str,
        output_mode: str = "files_with_matches",
        include: str | None = None,
    ) -> str:
        """Async grep for pattern in files."""
        return await self._get_backend().agrep(path, pattern, output_mode, include)

    def grep_raw(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> list[dict[str, Any]] | str:
        """Raw grep results."""
        return self._get_backend().grep_raw(pattern, path, glob)

    async def agrep_raw(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> list[dict[str, Any]] | str:
        """Async raw grep results."""
        return await self._get_backend().agrep_raw(pattern, path, glob)

    def delete(self, path: str) -> str:
        """Delete file or directory."""
        return self._get_backend().delete(path)

    async def adelete(self, path: str) -> str:
        """Async delete file or directory."""
        return await self._get_backend().adelete(path)

    def download_files(self, paths: list[str]) -> list[Any]:
        """Download files as bytes."""
        return self._get_backend().download_files(paths)

    async def adownload_files(self, paths: list[str]) -> list[Any]:
        """Async download files as bytes."""
        return await self._get_backend().adownload_files(paths)

    def upload_files(self, files: list[Any]) -> list[str]:
        """Upload files."""
        return self._get_backend().upload_files(files)

    async def aupload_files(self, files: list[Any]) -> list[str]:
        """Async upload files."""
        return await self._get_backend().aupload_files(files)

    def exists(self, path: str) -> bool:
        """Check if path exists."""
        return self._get_backend().exists(path)

    async def aexists(self, path: str) -> bool:
        """Async check if path exists."""
        return await self._get_backend().aexists(path)

    def mkdir(self, path: str, recursive: bool = False) -> str:  # noqa: FBT001, FBT002
        """Create directory."""
        return self._get_backend().mkdir(path, recursive)

    async def amkdir(self, path: str, recursive: bool = False) -> str:  # noqa: FBT001, FBT002
        """Async create directory."""
        return await self._get_backend().amkdir(path, recursive)

    def _resolve_path(self, path: str) -> Path:
        """Resolve path relative to current workspace."""
        return self._get_backend()._resolve_path(path)


def create_workspace_aware_backend(
    default_root_dir: Path,
    virtual_mode: bool = False,  # noqa: FBT001, FBT002
    max_file_size_mb: int = 10,
) -> BackendProtocol:
    """Create a workspace-aware filesystem backend.

    Args:
        default_root_dir: Default workspace when no ContextVar is set.
        virtual_mode: Whether to sandbox paths to workspace.
        max_file_size_mb: Maximum file size in MB.

    Returns:
        A backend that resolves workspace from ContextVar.
    """
    return WorkspaceAwareBackend(
        default_root_dir=default_root_dir,
        virtual_mode=virtual_mode,
        max_file_size_mb=max_file_size_mb,
    )
