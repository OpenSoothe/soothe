"""Workspace-aware filesystem backend for thread-specific workspace (RFC-103).

This module provides a backend wrapper that resolves the correct workspace
from the ToolRuntime.config at operation time, enabling per-thread workspace isolation.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

from deepagents.backends.filesystem import FilesystemBackend
from deepagents.backends.protocol import GlobResult

if TYPE_CHECKING:
    pass

# Global cache for workspace backends (shared across all instances)
_backend_cache: dict[str, NormalizedPathBackend] = {}


class NormalizedPathBackend(FilesystemBackend):
    """FilesystemBackend wrapper that normalizes paths to workspace-relative.

    When virtual_mode=False (allow_paths_outside_workspace=True), the underlying
    FilesystemBackend would interpret '/' as the actual root filesystem.
    This wrapper ensures such paths are treated as workspace-relative.

    ``_resolve_path`` is overridden so ``read``, ``write``, ``edit``, and other
    path-based operations use the same normalization as ``ls`` / ``glob`` (IG-300).

    Glob optimization: limits results to 50 and excludes large/irrelevant
    directories using .gitignore patterns + essential hardcoded excludes.
    """

    DEFAULT_GLOB_MAX_RESULTS = 50

    ESSENTIAL_GLOB_EXCLUDES = [
        ".venv",
        "venv",
        "env",
        "__pycache__",
        "node_modules",
        ".git",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        "site-packages",
    ]

    def _normalize_path(self, path: str) -> str:
        """Normalize path to be workspace-relative (RFC-103).

        Expands leading ``~`` so home-relative paths cannot bypass workspace
        routing (IG-300).

        When ``virtual_mode=True`` and the path is a host-absolute path inside
        the workspace, map it to the virtual absolute form (``/rel``) expected
        by ``FilesystemBackend._resolve_path`` (IG-300).

        Args:
            path: Input path (may be '/', absolute, or relative).

        Returns:
            Normalized path that's safe for the backend.
        """
        if not path or path.strip() in {"", ".", "/"}:
            return "."

        workspace = Path(self.cwd)
        expanded = Path(path.strip()).expanduser()

        if expanded.is_absolute():
            abs_str = str(expanded)
            try:
                rel = expanded.resolve().relative_to(workspace.resolve())
            except ValueError:
                # Path is outside workspace - treat as workspace-relative
                relative = abs_str.lstrip("/")
                return relative or "."
            if self.virtual_mode:
                return "/" + rel.as_posix()
            return abs_str

        return path.strip()

    def _load_gitignore_patterns(self) -> set[str]:
        """Load .gitignore patterns from workspace root (cached per instance)."""
        if hasattr(self, "_gitignore_cache") and self._gitignore_cache is not None:
            return self._gitignore_cache

        workspace = Path(self.cwd)
        gitignore_path = workspace / ".gitignore"
        self._gitignore_cache = set()

        if gitignore_path.exists():
            try:
                for line in gitignore_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        self._gitignore_cache.add(line)
            except OSError:
                pass

        return self._gitignore_cache

    def _should_exclude_path(self, path: str, name: str, excludes: set[str]) -> bool:
        """Check if a path/name should be excluded based on patterns."""
        for pattern in excludes:
            if pattern in name or pattern in path:
                return True
            if pattern.startswith("*") and name.endswith(pattern[1:]):
                return True
            if pattern.endswith("*") and name.startswith(pattern[:-1]):
                return True
        return False

    def _apply_glob_limits(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Apply gitignore + essential excludes and max_results limit to glob results."""
        all_excludes = set(self.ESSENTIAL_GLOB_EXCLUDES) | self._load_gitignore_patterns()

        filtered = [
            r
            for r in results
            if not self._should_exclude_path(r.get("path", ""), r.get("name", ""), all_excludes)
        ]

        if len(filtered) > self.DEFAULT_GLOB_MAX_RESULTS:
            truncated = filtered[: self.DEFAULT_GLOB_MAX_RESULTS]
            truncated.append(
                {
                    "name": f"... truncated {len(filtered) - self.DEFAULT_GLOB_MAX_RESULTS} more results",
                    "path": "",
                    "truncated": True,
                }
            )
            return truncated
        return filtered

    def _resolve_path(self, key: str) -> Path:
        """Apply RFC-103 normalization before deepagents virtual/host resolution (IG-300)."""
        return super()._resolve_path(self._normalize_path(key))

    def ls_info(self, path: str) -> list[dict[str, Any]]:
        """List directory with file info, normalizing path first."""
        return super().ls_info(self._normalize_path(path))

    async def als_info(self, path: str) -> list[dict[str, Any]]:
        """Async list directory with file info, normalizing path first."""
        return await super().als_info(self._normalize_path(path))

    def glob(self, pattern: str, path: str = "/") -> GlobResult:
        """Glob with path normalization, gitignore excludes, and max_results limit."""
        normalized = self._normalize_path(path)
        result = super().glob(pattern, normalized)
        if result.error or not result.matches:
            return result
        return GlobResult(matches=self._apply_glob_limits(result.matches))

    async def aglob(self, pattern: str, path: str = "/") -> GlobResult:
        """Async glob with path normalization, gitignore excludes, and max_results limit."""
        normalized = self._normalize_path(path)
        result = await super().aglob(pattern, normalized)
        if result.error or not result.matches:
            return result
        return GlobResult(matches=self._apply_glob_limits(result.matches))


def get_workspace_backend(
    workspace: Path | str,
    virtual_mode: bool = False,  # noqa: FBT001, FBT002
    max_file_size_mb: int = 10,
) -> NormalizedPathBackend:
    """Get or create a NormalizedPathBackend for the given workspace.

    Args:
        workspace: Workspace directory path.
        virtual_mode: Whether to sandbox paths to workspace.
        max_file_size_mb: Maximum file size in MB.

    Returns:
        NormalizedPathBackend instance for the workspace.
    """
    workspace_str = str(workspace)
    if workspace_str not in _backend_cache:
        _backend_cache[workspace_str] = NormalizedPathBackend(
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

    def __call__(self, runtime: Any) -> NormalizedPathBackend:
        """Called by FilesystemMiddleware to get backend for tool execution.

        This is the factory interface used by deepagents. It reads workspace
        from the runtime config (passed through LangGraph's configurable).

        Args:
            runtime: ToolRuntime with config containing workspace.

        Returns:
            NormalizedPathBackend for the tool's workspace.
        """
        # Try to get workspace from runtime.config (ToolRuntime case)
        if hasattr(runtime, "config") and runtime.config:
            configurable = runtime.config.get("configurable", {})
            workspace = configurable.get("workspace")
            if workspace:
                return get_workspace_backend(
                    Path(workspace),
                    self._virtual_mode,
                    self._max_file_size_mb,
                )

        # For Runtime (middleware), use get_config() from langgraph.config
        # Runtime does NOT have a config attribute - see langgraph.runtime docs
        with contextlib.suppress(Exception):
            from langgraph.config import get_config

            config = get_config()
            if config:
                configurable = config.get("configurable", {})
                workspace = configurable.get("workspace")
                if workspace:
                    return get_workspace_backend(
                        Path(workspace),
                        self._virtual_mode,
                        self._max_file_size_mb,
                    )

        # Fallback to ContextVar (for non-tool operations)
        from .framework_filesystem import FrameworkFilesystem

        current_workspace = FrameworkFilesystem.get_current_workspace()
        if current_workspace:
            return get_workspace_backend(
                current_workspace,
                self._virtual_mode,
                self._max_file_size_mb,
            )

        # Use default
        return self._default_backend

    def _get_backend(self) -> NormalizedPathBackend:
        """Get backend for direct method calls (non-tool operations).

        Returns:
            NormalizedPathBackend for current context.
        """
        from .framework_filesystem import FrameworkFilesystem

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

    def _normalize_path(self, path: str) -> str:
        """Normalize path to be workspace-relative (RFC-103).

        When the backend uses virtual_mode=False (allow_paths_outside_workspace=True),
        absolute paths like '/' would resolve to the actual root filesystem.
        This method ensures such paths are treated as workspace-relative.

        Args:
            path: Input path (may be '/', absolute, or relative).

        Returns:
            Normalized path that's safe for the backend.
        """
        # Empty, '.', or root '/' -> use workspace root
        if not path or path in {".", "/"}:
            return "."

        # Absolute path outside workspace -> make relative
        if path.startswith("/"):
            backend = self._get_backend()
            workspace = Path(backend.cwd).resolve()
            abs_path = Path(path).expanduser().resolve()
            try:
                rel = abs_path.relative_to(workspace)
            except ValueError:
                # Path is outside workspace - treat as workspace-relative
                relative = path.lstrip("/")
                return relative or "."
            if getattr(backend, "virtual_mode", False):
                return "/" + rel.as_posix()
            return path

        # Already relative
        return path

    def ls(self, path: str) -> list[str]:
        """List directory contents."""
        return self._get_backend().ls(self._normalize_path(path))

    async def als(self, path: str) -> list[str]:
        """Async list directory contents."""
        return await self._get_backend().als(self._normalize_path(path))

    def ls_info(self, path: str) -> list[dict[str, Any]]:
        """List directory with file info."""
        return self._get_backend().ls_info(self._normalize_path(path))

    async def als_info(self, path: str) -> list[dict[str, Any]]:
        """Async list directory with file info."""
        return await self._get_backend().als_info(self._normalize_path(path))

    def glob(self, pattern: str, path: str = "/") -> GlobResult:
        """Glob pattern matching with workspace path normalization."""
        return self._get_backend().glob(pattern, self._normalize_path(path))

    async def aglob(self, pattern: str, path: str = "/") -> GlobResult:
        """Async glob pattern matching with workspace path normalization."""
        return await self._get_backend().aglob(pattern, self._normalize_path(path))

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
