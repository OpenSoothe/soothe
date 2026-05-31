"""Refactored workspace backend using UnifiedFilesystem.

This module provides workspace-aware filesystem operations using the native
Soothe UnifiedFilesystem interface instead of external dependencies.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar, Token
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from soothe.config import SootheConfig
    from soothe.protocols.policy import PolicyContext, PolicyProtocol

logger = logging.getLogger(__name__)

# Thread-safe workspace context for async execution (RFC-103)
_current_workspace: ContextVar[Path | None] = ContextVar("soothe_workspace", default=None)


class FrameworkFilesystem:
    """Singleton filesystem backend for all framework operations.
    
    Provides consistent path resolution and security across:
    - Tool operations (via middleware)
    - Framework operations (reports, checkpoints, manifests)
    - CLI operations (final reports, health checks)
    
    Uses native UnifiedFilesystem.
    """
    
    _instance: Any | None = None
    _root_dir: Path | None = None
    _policy: PolicyProtocol | None = None
    
    @classmethod
    def initialize(
        cls,
        config: SootheConfig,
        policy: PolicyProtocol | None = None,
    ) -> Any:
        """Initialize the singleton filesystem backend.
        
        Args:
            config: Soothe configuration.
            policy: Optional security policy for access control.
            
        Returns:
            Initialized WorkspaceFilesystem instance.
        """
        from soothe.core.filesystem import WorkspaceFilesystem
        from soothe.core.workspace.resolution import resolve_daemon_workspace
        
        # Use daemon workspace (TEMP unless SOOTHE_WORKSPACE set) as default
        resolved_workspace = resolve_daemon_workspace()
        
        virtual_mode = not config.security.allow_paths_outside_workspace
        
        max_file_size_mb = 10
        if hasattr(config, "filesystem_middleware") and hasattr(
            config.filesystem_middleware, "max_file_size_mb"
        ):
            max_file_size_mb = config.filesystem_middleware.max_file_size_mb
        
        cls._instance = WorkspaceFilesystem(
            workspace=resolved_workspace,
            virtual_mode=virtual_mode,
            max_file_size_mb=max_file_size_mb,
        )
        cls._root_dir = resolved_workspace
        cls._policy = policy
        
        logger.info(
            "FrameworkFilesystem initialized: root=%s virtual_mode=%s",
            resolved_workspace,
            virtual_mode,
        )
        
        return cls._instance
    
    @classmethod
    def get(cls) -> Any:
        """Get the singleton filesystem backend.
        
        Returns:
            WorkspaceFilesystem instance.
            
        Raises:
            RuntimeError: If backend not initialized.
        """
        if cls._instance is None:
            raise RuntimeError(
                "FrameworkFilesystem not initialized. Call FrameworkFilesystem.initialize() first."
            )
        return cls._instance
    
    @classmethod
    def is_initialized(cls) -> bool:
        """Check if the backend has been initialized."""
        return cls._instance is not None
    
    @classmethod
    def get_root_dir(cls) -> Path:
        """Get the root workspace directory.
        
        Returns:
            Path to the root workspace.
            
        Raises:
            RuntimeError: If backend not initialized.
        """
        if cls._root_dir is None:
            raise RuntimeError("FrameworkFilesystem not initialized")
        return cls._root_dir
    
    @classmethod
    def get_current_workspace(cls) -> Path | None:
        """Get the current workspace from context variable.
        
        Returns:
            Current workspace path or None if not set.
        """
        return _current_workspace.get()
    
    @classmethod
    def set_current_workspace(cls, workspace: Path | str) -> Token:
        """Set the current workspace for the current context.
        
        Args:
            workspace: Workspace directory path.
            
        Returns:
            Token for restoring previous value.
        """
        return _current_workspace.set(Path(workspace))
    
    @classmethod
    def reset_workspace(cls, token: Token) -> None:
        """Reset workspace to previous value using token.
        
        Args:
            token: Token from set_current_workspace.
        """
        _current_workspace.reset(token)


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
        
        # Create underlying UnifiedFilesystem
        from soothe.core.filesystem import LocalFilesystem
        
        self._fs = LocalFilesystem(
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
            abs_str = str(expanded)
            try:
                rel = expanded.resolve().relative_to(self._root_dir.resolve())
            except ValueError:
                # Path is outside workspace - treat as workspace-relative
                relative = abs_str.lstrip("/")
                return relative or "."
            if self._virtual_mode:
                return "/" + rel.as_posix()
            return abs_str
        
        return path.strip()
    
    def read(self, path: str, offset: int = 0, limit: int | None = None) -> str:
        """Read file contents."""
        normalized = self._normalize_path(path)
        result = self._fs.read(normalized, offset=offset, limit=limit)
        if result.error:
            raise FileNotFoundError(f"Error reading {path}: {result.error}")
        return result.content
    
    async def aread(self, path: str, offset: int = 0, limit: int | None = None) -> str:
        """Async read file contents."""
        normalized = self._normalize_path(path)
        result = await self._fs.aread(normalized, offset=offset, limit=limit)
        if result.error:
            raise FileNotFoundError(f"Error reading {path}: {result.error}")
        return result.content
    
    def write(self, path: str, content: str | bytes) -> str:
        """Write content to file."""
        normalized = self._normalize_path(path)
        result = self._fs.write(normalized, content)
        if result.error:
            raise IOError(f"Error writing {path}: {result.error}")
        return result.path
    
    async def awrite(self, path: str, content: str | bytes) -> str:
        """Async write content to file."""
        normalized = self._normalize_path(path)
        result = await self._fs.awrite(normalized, content)
        if result.error:
            raise IOError(f"Error writing {path}: {result.error}")
        return result.path
    
    def edit(
        self,
        path: str,
        old_string: str | None = None,
        new_string: str | None = None,
        edits: list[dict[str, Any]] | None = None,
    ) -> str:
        """Apply edits to file."""
        normalized = self._normalize_path(path)
        
        if edits:
            # Handle edits list format
            for edit in edits:
                old = edit.get("old_string", "")
                new = edit.get("new_string", "")
                result = self._fs.edit(normalized, old, new)
                if result.error:
                    raise IOError(f"Error editing {path}: {result.error}")
        elif old_string is not None and new_string is not None:
            result = self._fs.edit(normalized, old_string, new_string)
            if result.error:
                raise IOError(f"Error editing {path}: {result.error}")
        
        return normalized
    
    async def aedit(
        self,
        path: str,
        old_string: str | None = None,
        new_string: str | None = None,
        edits: list[dict[str, Any]] | None = None,
    ) -> str:
        """Async apply edits to file."""
        normalized = self._normalize_path(path)
        
        if edits:
            for edit in edits:
                old = edit.get("old_string", "")
                new = edit.get("new_string", "")
                result = await self._fs.aedit(normalized, old, new)
                if result.error:
                    raise IOError(f"Error editing {path}: {result.error}")
        elif old_string is not None and new_string is not None:
            result = await self._fs.aedit(normalized, old_string, new_string)
            if result.error:
                raise IOError(f"Error editing {path}: {result.error}")
        
        return normalized
    
    def ls(self, path: str = ".") -> list[str]:
        """List directory contents."""
        normalized = self._normalize_path(path)
        result = self._fs.ls(normalized)
        if isinstance(result, list) and result and isinstance(result[0], str):
            return result
        # Handle FileInfo list
        return [item.path for item in result]
    
    async def als(self, path: str = ".") -> list[str]:
        """Async list directory contents."""
        normalized = self._normalize_path(path)
        result = await self._fs.als(normalized)
        if isinstance(result, list) and result and isinstance(result[0], str):
            return result
        return [item.path for item in result]
    
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
        """Glob pattern matching."""
        from soothe.core.filesystem.protocol import GlobResult
        
        normalized = self._normalize_path(path)
        result = self._fs.glob(pattern, path=normalized)
        
        # Convert to GlobResult format
        return GlobResult(
            matches=result.matches,
            truncated=result.truncated,
            total_count=result.total_count,
            error=result.error,
        )
    
    async def aglob(self, pattern: str, path: str = "/") -> Any:
        """Async glob pattern matching."""
        from soothe.core.filesystem.protocol import GlobResult
        
        normalized = self._normalize_path(path)
        result = await self._fs.aglob(pattern, path=normalized)
        
        return GlobResult(
            matches=result.matches,
            truncated=result.truncated,
            total_count=result.total_count,
            error=result.error,
        )
    
    def grep(
        self,
        pattern: str,
        path: str = ".",
        output_mode: str = "files_with_matches",
        include: str | None = None,
    ) -> str:
        """Search for pattern in files."""
        normalized = self._normalize_path(path)
        result = self._fs.grep(pattern, path=normalized, glob=include, output_mode=output_mode)
        
        if isinstance(result, str):
            return result
        if isinstance(result, list):
            return "\n".join(result)
        return ""
    
    async def agrep(
        self,
        pattern: str,
        path: str = ".",
        output_mode: str = "files_with_matches",
        include: str | None = None,
    ) -> str:
        """Async search for pattern in files."""
        normalized = self._normalize_path(path)
        result = await self._fs.agrep(pattern, path=normalized, glob=include, output_mode=output_mode)
        
        if isinstance(result, str):
            return result
        if isinstance(result, list):
            return "\n".join(result)
        return ""
    
    def delete(self, path: str) -> str:
        """Delete file or directory."""
        normalized = self._normalize_path(path)
        result = self._fs.delete(normalized)
        if result.error:
            raise IOError(f"Error deleting {path}: {result.error}")
        return normalized
    
    async def adelete(self, path: str) -> str:
        """Async delete file or directory."""
        normalized = self._normalize_path(path)
        result = await self._fs.adelete(normalized)
        if result.error:
            raise IOError(f"Error deleting {path}: {result.error}")
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
        # Try to get workspace from runtime.config
        if hasattr(runtime, "config") and runtime.config:
            configurable = runtime.config.get("configurable", {})
            workspace = configurable.get("workspace")
            if workspace:
                return NormalizedPathBackend(
                    root_dir=Path(workspace),
                    virtual_mode=self._virtual_mode,
                    max_file_size_mb=self._max_file_size_mb,
                )
        
        # Fallback to ContextVar
        current_workspace = FrameworkFilesystem.get_current_workspace()
        if current_workspace:
            return NormalizedPathBackend(
                root_dir=current_workspace,
                virtual_mode=self._virtual_mode,
                max_file_size_mb=self._max_file_size_mb,
            )
        
        # Use default
        return self._default_backend
    
    def _get_backend(self) -> NormalizedPathBackend:
        """Get backend for direct method calls (non-tool operations).
        
        Returns:
            NormalizedPathBackend for current context.
        """
        current_workspace = FrameworkFilesystem.get_current_workspace()
        if current_workspace:
            return NormalizedPathBackend(
                root_dir=current_workspace,
                virtual_mode=self._virtual_mode,
                max_file_size_mb=self._max_file_size_mb,
            )
        return self._default_backend
    
    # Delegate all methods to the resolved backend
    
    def read(self, path: str, offset: int = 0, limit: int | None = None) -> str:
        """Read file contents."""
        return self._get_backend().read(path, offset, limit)
    
    async def aread(self, path: str, offset: int = 0, limit: int | None = None) -> str:
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
        edits: list[dict[str, Any]] | None = None,
        old_string: str | None = None,
        new_string: str | None = None,
    ) -> str:
        """Apply edits to file."""
        if edits:
            return self._get_backend().edit(path, edits=edits)
        return self._get_backend().edit(path, old_string=old_string, new_string=new_string)
    
    async def aedit(
        self,
        path: str,
        edits: list[dict[str, Any]] | None = None,
        old_string: str | None = None,
        new_string: str | None = None,
    ) -> str:
        """Async apply edits to file."""
        if edits:
            return await self._get_backend().aedit(path, edits=edits)
        return await self._get_backend().aedit(path, old_string=old_string, new_string=new_string)
    
    def ls(self, path: str = ".") -> list[str]:
        """List directory contents."""
        return self._get_backend().ls(path)
    
    async def als(self, path: str = ".") -> list[str]:
        """Async list directory contents."""
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
        include: str | None = None,
    ) -> str:
        """Search for pattern in files."""
        return self._get_backend().grep(pattern, path, output_mode, include)
    
    async def agrep(
        self,
        pattern: str,
        path: str = ".",
        output_mode: str = "files_with_matches",
        include: str | None = None,
    ) -> str:
        """Async search for pattern in files."""
        return await self._get_backend().agrep(pattern, path, output_mode, include)
    
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
