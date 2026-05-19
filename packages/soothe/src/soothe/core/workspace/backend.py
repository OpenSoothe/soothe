"""Workspace-aware filesystem backend for thread-specific workspace (RFC-103).

This module provides a backend wrapper that resolves the correct workspace
from the ToolRuntime.config at operation time, enabling per-thread workspace isolation.
"""

from __future__ import annotations

import contextlib
import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import wcmatch.glob as wcglob
from deepagents.backends.filesystem import FilesystemBackend
from deepagents.backends.protocol import GlobResult
from pathspec import PathSpec

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Global cache for workspace backends (shared across all instances)
_backend_cache: dict[str, NormalizedPathBackend] = {}

_WCMATCH_FLAGS = wcglob.BRACE | wcglob.GLOBSTAR
_GIT_LS_FILES_TIMEOUT_S = 5.0


class NormalizedPathBackend(FilesystemBackend):
    """FilesystemBackend wrapper that normalizes paths to workspace-relative.

    When virtual_mode=False (allow_paths_outside_workspace=True), the underlying
    FilesystemBackend would interpret '/' as the actual root filesystem.
    This wrapper ensures such paths are treated as workspace-relative.

    ``_resolve_path`` is overridden so ``read``, ``write``, ``edit``, and other
    path-based operations use the same normalization as ``ls`` / ``glob`` (IG-300).

    Glob optimization: respects ``.gitignore`` (and nested ignore files on walk),
    prunes ignored directories during traversal, uses ``git ls-files`` when
    available, and caps results to ``DEFAULT_GLOB_MAX_RESULTS``.
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

    def _load_gitignore_lines(self) -> list[str]:
        """Load raw pattern lines from workspace root ``.gitignore`` (cached)."""
        if hasattr(self, "_gitignore_lines_cache"):
            return self._gitignore_lines_cache

        workspace = Path(self.cwd)
        gitignore_path = workspace / ".gitignore"
        lines: list[str] = []
        if gitignore_path.exists():
            try:
                for line in gitignore_path.read_text(encoding="utf-8").splitlines():
                    stripped = line.strip()
                    if stripped and not stripped.startswith("#"):
                        lines.append(stripped)
            except OSError:
                pass

        self._gitignore_lines_cache = lines
        return lines

    def _ignore_spec(self) -> PathSpec:
        """Build a gitwildmatch spec from essential excludes + root ``.gitignore``."""
        if hasattr(self, "_ignore_spec_cache"):
            return self._ignore_spec_cache

        patterns = [f"{name}/" if "/" not in name else name for name in self.ESSENTIAL_GLOB_EXCLUDES]
        patterns.extend(self._load_gitignore_lines())
        self._ignore_spec_cache = PathSpec.from_lines("gitignore", patterns)
        return self._ignore_spec_cache

    def _is_ignored(self, rel_posix: str) -> bool:
        """Return True when a workspace-relative path is ignored."""
        return self._ignore_spec().match_file(rel_posix)

    def _apply_glob_limits(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Cap glob results to ``DEFAULT_GLOB_MAX_RESULTS``."""
        if len(results) > self.DEFAULT_GLOB_MAX_RESULTS:
            truncated = results[: self.DEFAULT_GLOB_MAX_RESULTS]
            truncated.append(
                {
                    "name": f"... truncated {len(results) - self.DEFAULT_GLOB_MAX_RESULTS} more results",
                    "path": "",
                    "truncated": True,
                }
            )
            return truncated
        return results

    def _file_info(self, matched_path: Path) -> dict[str, Any]:
        """Build a deepagents ``FileInfo`` dict for a matched file."""
        if self.virtual_mode:
            try:
                path_key: str = self._to_virtual_path(matched_path)
            except ValueError:
                return {}
            except (OSError, RuntimeError):
                logger.warning("Could not resolve glob result path: %s", matched_path, exc_info=True)
                return {}
        else:
            path_key = str(matched_path)

        try:
            st = matched_path.stat()
            return {
                "path": path_key,
                "is_dir": False,
                "size": int(st.st_size),
                "modified_at": datetime.fromtimestamp(st.st_mtime).isoformat(),  # noqa: DTZ006
            }
        except OSError:
            return {"path": path_key, "is_dir": False}

    def _list_files_via_git(self, workspace: Path) -> list[str] | None:
        """List non-ignored files using git index (fast, full gitignore semantics)."""
        if not (workspace / ".git").exists():
            return None
        try:
            proc = subprocess.run(
                [
                    "git",
                    "-C",
                    str(workspace),
                    "ls-files",
                    "-co",
                    "--exclude-standard",
                    "-z",
                ],
                capture_output=True,
                check=False,
                timeout=_GIT_LS_FILES_TIMEOUT_S,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.debug("git ls-files unavailable for glob: %s", exc)
            return None
        if proc.returncode != 0:
            logger.debug("git ls-files failed (code %s) for glob", proc.returncode)
            return None
        return [p.decode("utf-8", errors="replace") for p in proc.stdout.split(b"\0") if p]

    def _list_files_via_walk(self, workspace: Path, search_path: Path) -> list[str]:
        """Walk the tree, pruning ignored directories using pathspec."""
        rel_paths: list[str] = []
        search_resolved = search_path.resolve()
        workspace_resolved = workspace.resolve()

        for root, dirs, files in os.walk(search_path, topdown=True, followlinks=False):
            root_path = Path(root)
            try:
                rel_root = root_path.resolve().relative_to(workspace_resolved)
                rel_root_posix = "." if rel_root == Path(".") else rel_root.as_posix()
            except ValueError:
                continue

            dirs[:] = sorted(
                d
                for d in dirs
                if not self._is_ignored(
                    f"{rel_root_posix}/{d}".removeprefix("./") if rel_root_posix != "." else d
                )
            )

            for name in files:
                rel_posix = (
                    name
                    if rel_root_posix == "."
                    else f"{rel_root_posix}/{name}".removeprefix("./")
                )
                if self._is_ignored(rel_posix):
                    continue
                full = root_path / name
                if not full.is_file():
                    continue
                if not full.resolve().is_relative_to(search_resolved):
                    continue
                rel_paths.append(rel_posix)

        return rel_paths

    def _glob_gitignore_aware(self, pattern: str, path: str) -> GlobResult:
        """Match ``pattern`` under ``path`` while respecting gitignore rules."""
        if pattern.startswith("/"):
            pattern = pattern.lstrip("/")

        if self.virtual_mode and ".." in Path(pattern).parts:
            return GlobResult(error="Path traversal not allowed in glob pattern", matches=[])

        workspace = Path(self.cwd).resolve()
        try:
            search_path = workspace if path in {"/", ".", ""} else self._resolve_path(path)
            if not search_path.exists() or not search_path.is_dir():
                return GlobResult(matches=[])
        except (OSError, RuntimeError) as exc:
            return GlobResult(error=f"Error globbing path '{path}': {exc}", matches=[])

        try:
            search_rel = search_path.resolve().relative_to(workspace)
            search_prefix = "." if search_rel == Path(".") else search_rel.as_posix()
        except ValueError:
            return GlobResult(error=f"Error globbing path '{path}': outside workspace", matches=[])

        candidates = self._list_files_via_git(workspace)
        if candidates is None:
            candidates = self._list_files_via_walk(workspace, search_path)

        results: list[dict[str, Any]] = []
        for rel_posix in candidates:
            if search_prefix != ".":
                if rel_posix != search_prefix and not rel_posix.startswith(f"{search_prefix}/"):
                    continue
                match_rel = (
                    rel_posix[len(search_prefix) + 1 :]
                    if rel_posix.startswith(f"{search_prefix}/")
                    else rel_posix
                )
            else:
                match_rel = rel_posix

            if not wcglob.globmatch(match_rel, pattern, flags=_WCMATCH_FLAGS) and not wcglob.globmatch(
                Path(rel_posix).name, pattern, flags=_WCMATCH_FLAGS
            ):
                continue

            full_path = (workspace / rel_posix).resolve()
            if not full_path.is_file():
                continue
            info = self._file_info(full_path)
            if info:
                results.append(info)

        results.sort(key=lambda item: item.get("path", ""))
        return GlobResult(matches=self._apply_glob_limits(results))

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
        """Glob with gitignore-aware traversal and result limits."""
        normalized = self._normalize_path(path)
        return self._glob_gitignore_aware(pattern, normalized)

    async def aglob(self, pattern: str, path: str = "/") -> GlobResult:
        """Async glob with gitignore-aware traversal and result limits."""
        normalized = self._normalize_path(path)
        return self._glob_gitignore_aware(pattern, normalized)


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
