"""Workspace-aware filesystem implementation.

This module provides a UnifiedFilesystem implementation that integrates with
the Soothe workspace backend system, enabling per-thread workspace isolation
and framework-wide filesystem operations.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path

import wcmatch.glob as wcglob
from pathspec import PathSpec

from soothe_nano.workspace.workspace_runtime import resolve_process_workspace_root

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

_WCMATCH_FLAGS = wcglob.BRACE | wcglob.GLOBSTAR
_GIT_LS_FILES_TIMEOUT_S = 5.0


class WorkspaceFilesystem(UnifiedFilesystem):
    """Workspace-aware filesystem implementing UnifiedFilesystem interface.

    This implementation integrates with Soothe's workspace backend system,
    providing per-thread workspace isolation and framework-wide filesystem
    operations. It replaces the legacy backend with a native
    UnifiedFilesystem implementation.

    Features:
    - Per-thread workspace isolation via context variables
    - Gitignore-aware glob operations
    - Path normalization and security validation
    - Async operation support
    - Framework integration with WorkspaceAwareBackend

    Attributes:
        workspace: The root workspace directory.
        virtual_mode: Whether paths are sandboxed to the workspace.
        max_file_size_mb: Maximum file size in megabytes.
        _local_fs: Underlying LocalFilesystem for actual operations.
        _gitignore_spec: Cached gitignore patterns.

    Example:
        >>> from soothe_nano.filesystem import WorkspaceFilesystem
        >>> fs = WorkspaceFilesystem("/workspace", virtual_mode=True)
        >>> result = fs.read("config.json")
        >>> print(result.content)
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

    def __init__(
        self,
        workspace: str | Path,
        *,
        virtual_mode: bool = True,
        max_file_size_mb: int = 10,
    ) -> None:
        """Initialize the workspace filesystem.

        Args:
            workspace: Root workspace directory.
            virtual_mode: Whether to sandbox paths to workspace.
            max_file_size_mb: Maximum file size in MB.
        """
        super().__init__(
            workspace=workspace,
            virtual_mode=virtual_mode,
            max_file_size_mb=max_file_size_mb,
        )
        self._local_fs = LocalFilesystem(
            workspace=workspace,
            virtual_mode=virtual_mode,
            max_file_size_mb=max_file_size_mb,
        )
        self._gitignore_spec: PathSpec | None = None
        self._gitignore_lines_cache: list[str] | None = None

    # ========================================================================
    # Gitignore Support
    # ========================================================================

    def _load_gitignore_lines(self) -> list[str]:
        """Load raw pattern lines from workspace root ``.gitignore`` (cached)."""
        if self._gitignore_lines_cache is not None:
            return self._gitignore_lines_cache

        gitignore_path = self.workspace / ".gitignore"
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
        if self._gitignore_spec is not None:
            return self._gitignore_spec

        patterns = [
            f"{name}/" if "/" not in name else name for name in self.ESSENTIAL_GLOB_EXCLUDES
        ]
        patterns.extend(self._load_gitignore_lines())
        self._gitignore_spec = PathSpec.from_lines("gitignore", patterns)
        return self._gitignore_spec

    def _is_ignored(self, rel_posix: str) -> bool:
        """Return True when a workspace-relative path is ignored."""
        return self._ignore_spec().match_file(rel_posix)

    def _apply_glob_limits(self, results: list[str]) -> tuple[list[str], bool]:
        """Cap glob results to ``DEFAULT_GLOB_MAX_RESULTS``.

        Returns:
            Tuple of (limited_results, was_truncated).
        """
        if len(results) > self.DEFAULT_GLOB_MAX_RESULTS:
            return results[: self.DEFAULT_GLOB_MAX_RESULTS], True
        return results, False

    def _list_files_via_git(self) -> list[str] | None:
        """List non-ignored files using git index (fast, full gitignore semantics)."""
        if not (self.workspace / ".git").exists():
            return None
        try:
            proc = subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.workspace),
                    "ls-files",
                    "-co",
                    "--exclude-standard",
                    "-z",
                ],
                capture_output=True,
                check=False,
                timeout=_GIT_LS_FILES_TIMEOUT_S,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if proc.returncode != 0:
            return None
        return [p.decode("utf-8", errors="replace") for p in proc.stdout.split(b"\0") if p]

    def _list_files_via_walk(self, search_path: Path) -> list[str]:
        """Walk the tree, pruning ignored directories using pathspec."""
        rel_paths: list[str] = []
        search_resolved = search_path.resolve()
        workspace_resolved = self.workspace.resolve()

        for root, dirs, files in os.walk(search_path, topdown=True, followlinks=False):
            root_path = Path(root)
            try:
                rel_root = root_path.resolve().relative_to(workspace_resolved)
                rel_root_posix = "." if rel_root == Path(".") else rel_root.as_posix()
            except ValueError:
                continue

            # Filter out ignored directories
            dirs[:] = sorted(
                d
                for d in dirs
                if not self._is_ignored(
                    f"{rel_root_posix}/{d}".removeprefix("./") if rel_root_posix != "." else d
                )
            )

            for name in files:
                rel_posix = (
                    name if rel_root_posix == "." else f"{rel_root_posix}/{name}".removeprefix("./")
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

    # ========================================================================
    # Path Operations
    # ========================================================================

    def resolve_path(self, path: str, *, allow_host_absolute: bool = False) -> Path:
        """Resolve a path relative to workspace.

        Args:
            path: Input path (may be absolute, relative, or virtual).
            allow_host_absolute: When ``True``, host-root absolutes outside the
                workspace resolve to the real on-disk path (read-only ops).

        Returns:
            Resolved Path object.

        Raises:
            InvalidPathError: If path contains invalid characters.
            PathTraversalError: If path attempts to escape workspace.
        """
        return self._local_fs.resolve_path(path, allow_host_absolute=allow_host_absolute)

    def exists(self, path: str) -> bool:
        """Check if a path exists."""
        return self._local_fs.exists(path)

    def is_file(self, path: str) -> bool:
        """Check if path is a file."""
        return self._local_fs.is_file(path)

    def is_dir(self, path: str) -> bool:
        """Check if path is a directory."""
        return self._local_fs.is_dir(path)

    # ========================================================================
    # Read Operations
    # ========================================================================

    def read(
        self,
        path: str,
        *,
        offset: int = 0,
        limit: int | None = None,
        encoding: str = "utf-8",
    ) -> ReadResult:
        """Read file contents."""
        return self._local_fs.read(path, offset=offset, limit=limit, encoding=encoding)

    async def aread(
        self,
        path: str,
        *,
        offset: int = 0,
        limit: int | None = None,
        encoding: str = "utf-8",
    ) -> ReadResult:
        """Async read file contents."""
        return await self._local_fs.aread(path, offset=offset, limit=limit, encoding=encoding)

    # ========================================================================
    # Write Operations
    # ========================================================================

    def write(
        self,
        path: str,
        content: str | bytes,
        *,
        encoding: str = "utf-8",
        backup: bool = False,
    ) -> WriteResult:
        """Write content to file."""
        return self._local_fs.write(path, content, encoding=encoding, backup=backup)

    async def awrite(
        self,
        path: str,
        content: str | bytes,
        *,
        encoding: str = "utf-8",
        backup: bool = False,
    ) -> WriteResult:
        """Async write content to file."""
        return await self._local_fs.awrite(path, content, encoding=encoding, backup=backup)

    # ========================================================================
    # Edit Operations
    # ========================================================================

    def edit(
        self,
        path: str,
        old_string: str,
        new_string: str,
        *,
        backup: bool = True,
    ) -> EditResult:
        """Replace old_string with new_string in file."""
        return self._local_fs.edit(path, old_string, new_string, backup=backup)

    async def aedit(
        self,
        path: str,
        old_string: str,
        new_string: str,
        *,
        backup: bool = True,
    ) -> EditResult:
        """Async replace old_string with new_string in file."""
        return await self._local_fs.aedit(path, old_string, new_string, backup=backup)

    def edit_lines(
        self,
        path: str,
        start_line: int,
        end_line: int,
        new_content: str,
        *,
        backup: bool = True,
    ) -> EditResult:
        """Replace specific line range in file."""
        return self._local_fs.edit_lines(path, start_line, end_line, new_content, backup=backup)

    async def aedit_lines(
        self,
        path: str,
        start_line: int,
        end_line: int,
        new_content: str,
        *,
        backup: bool = True,
    ) -> EditResult:
        """Async replace specific line range in file."""
        return await self._local_fs.aedit_lines(
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
        """Insert content at specific line number."""
        return self._local_fs.insert_lines(path, line, content, backup=backup)

    async def ainsert_lines(
        self,
        path: str,
        line: int,
        content: str,
        *,
        backup: bool = True,
    ) -> EditResult:
        """Async insert content at specific line number."""
        return await self._local_fs.ainsert_lines(path, line, content, backup=backup)

    def delete_lines(
        self,
        path: str,
        start_line: int,
        end_line: int,
        *,
        backup: bool = True,
    ) -> EditResult:
        """Delete specific line range from file."""
        return self._local_fs.delete_lines(path, start_line, end_line, backup=backup)

    async def adelete_lines(
        self,
        path: str,
        start_line: int,
        end_line: int,
        *,
        backup: bool = True,
    ) -> EditResult:
        """Async delete specific line range from file."""
        return await self._local_fs.adelete_lines(path, start_line, end_line, backup=backup)

    def apply_diff(
        self,
        path: str,
        diff: str,
        *,
        backup: bool = True,
    ) -> EditResult:
        """Apply unified diff patch to file."""
        return self._local_fs.apply_diff(path, diff, backup=backup)

    async def aapply_diff(
        self,
        path: str,
        diff: str,
        *,
        backup: bool = True,
    ) -> EditResult:
        """Async apply unified diff patch to file."""
        return await self._local_fs.aapply_diff(path, diff, backup=backup)

    async def aedit_batched(
        self,
        path: str,
        operations: list[BatchedEditOperation],
        *,
        backup: bool = True,
    ) -> BatchedEditResult:
        """Async apply multiple edit operations to a file in one read/modify/write cycle.

        IG-517: Batched edit for coalescing middleware.
        """
        return await self._local_fs.aedit_batched(path, operations, backup=backup)

    # ========================================================================
    # Directory Operations
    # ========================================================================

    def ls(
        self,
        path: str = ".",
        *,
        include_info: bool = False,
    ) -> list[str] | list[FileInfo]:
        """List directory contents."""
        return self._local_fs.ls(path, include_info=include_info)

    async def als(
        self,
        path: str = ".",
        *,
        include_info: bool = False,
    ) -> list[str] | list[FileInfo]:
        """Async list directory contents."""
        return await self._local_fs.als(path, include_info=include_info)

    def mkdir(
        self,
        path: str,
        *,
        recursive: bool = False,
        exist_ok: bool = False,
    ) -> FileInfo:
        """Create directory."""
        return self._local_fs.mkdir(path, recursive=recursive, exist_ok=exist_ok)

    async def amkdir(
        self,
        path: str,
        *,
        recursive: bool = False,
        exist_ok: bool = False,
    ) -> FileInfo:
        """Async create directory."""
        return await self._local_fs.amkdir(path, recursive=recursive, exist_ok=exist_ok)

    def rmdir(
        self,
        path: str,
        *,
        recursive: bool = False,
        backup: bool = False,
    ) -> DeleteResult:
        """Remove directory."""
        return self._local_fs.rmdir(path, recursive=recursive, backup=backup)

    async def armdir(
        self,
        path: str,
        *,
        recursive: bool = False,
        backup: bool = False,
    ) -> DeleteResult:
        """Async remove directory."""
        return await self._local_fs.armdir(path, recursive=recursive, backup=backup)

    # ========================================================================
    # File Operations
    # ========================================================================

    def delete(
        self,
        path: str,
        *,
        backup: bool = True,
    ) -> DeleteResult:
        """Delete file."""
        return self._local_fs.delete(path, backup=backup)

    async def adelete(
        self,
        path: str,
        *,
        backup: bool = True,
    ) -> DeleteResult:
        """Async delete file."""
        return await self._local_fs.adelete(path, backup=backup)

    def info(self, path: str) -> FileInfo:
        """Get file/directory information."""
        return self._local_fs.info(path)

    async def ainfo(self, path: str) -> FileInfo:
        """Async get file/directory information."""
        return await self._local_fs.ainfo(path)

    def copy(
        self,
        src: str,
        dst: str,
        *,
        overwrite: bool = False,
    ) -> FileInfo:
        """Copy file or directory."""
        return self._local_fs.copy(src, dst, overwrite=overwrite)

    async def acopy(
        self,
        src: str,
        dst: str,
        *,
        overwrite: bool = False,
    ) -> FileInfo:
        """Async copy file or directory."""
        return await self._local_fs.acopy(src, dst, overwrite=overwrite)

    def move(
        self,
        src: str,
        dst: str,
        *,
        overwrite: bool = False,
    ) -> FileInfo:
        """Move/rename file or directory."""
        return self._local_fs.move(src, dst, overwrite=overwrite)

    async def amove(
        self,
        src: str,
        dst: str,
        *,
        overwrite: bool = False,
    ) -> FileInfo:
        """Async move/rename file or directory."""
        return await self._local_fs.amove(src, dst, overwrite=overwrite)

    # ========================================================================
    # Search Operations (with gitignore support)
    # ========================================================================

    def glob(
        self,
        pattern: str,
        *,
        path: str = ".",
        include_ignored: bool = False,
    ) -> GlobResult:
        """Glob pattern matching with gitignore support.

        Args:
            pattern: Glob pattern (e.g., "**/*.py").
            path: Directory to search in.
            include_ignored: Whether to include gitignored files.

        Returns:
            GlobResult with matches.
        """
        if pattern.startswith("/"):
            pattern = pattern.lstrip("/")

        if self.virtual_mode and ".." in Path(pattern).parts:
            return GlobResult(
                matches=[],
                error="Path traversal not allowed in glob pattern",
            )

        search_path = self.workspace if path in {"/", ".", ""} else self.resolve_path(path)
        if not search_path.exists() or not search_path.is_dir():
            return GlobResult(matches=[])

        try:
            search_rel = search_path.resolve().relative_to(self.workspace.resolve())
            search_prefix = "." if search_rel == Path(".") else search_rel.as_posix()
        except ValueError:
            return GlobResult(
                matches=[],
                error=f"Error globbing path '{path}': outside workspace",
            )

        # Get candidates (respecting gitignore)
        if include_ignored:
            # List all files without gitignore filtering
            candidates: list[str] = []
            for root, _dirs, files in os.walk(search_path, topdown=True, followlinks=False):
                root_path = Path(root)
                try:
                    rel_root = root_path.resolve().relative_to(self.workspace.resolve())
                    rel_root_posix = "." if rel_root == Path(".") else rel_root.as_posix()
                except ValueError:
                    continue
                for name in files:
                    rel_posix = (
                        name
                        if rel_root_posix == "."
                        else f"{rel_root_posix}/{name}".removeprefix("./")
                    )
                    candidates.append(rel_posix)
        else:
            candidates = self._list_files_via_git()
            if candidates is None:
                candidates = self._list_files_via_walk(search_path)

        results: list[str] = []
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

            if not wcglob.globmatch(
                match_rel, pattern, flags=_WCMATCH_FLAGS
            ) and not wcglob.globmatch(Path(rel_posix).name, pattern, flags=_WCMATCH_FLAGS):
                continue

            full_path = (self.workspace / rel_posix).resolve()
            if not full_path.is_file():
                continue

            # Always return host-absolute paths so the LLM gets paths that work
            # consistently across filesystem tools (which accept host-absolute
            # paths under the workspace via _normalize_path) AND shell tools
            # (which see '/' as the host root, not the workspace).
            results.append(str(full_path))

        results.sort()
        limited_results, truncated = self._apply_glob_limits(results)

        hint: str | None = None
        if not limited_results:
            hint = (
                f"No files matched pattern {pattern!r} under {search_path} "
                f"(workspace root: {self.workspace}). "
                "Try a scoped path, grep, or ls on a known directory."
            )

        return GlobResult(
            matches=limited_results,
            truncated=truncated,
            total_count=len(results) if truncated else None,
            error=hint,
        )

    async def aglob(
        self,
        pattern: str,
        *,
        path: str = ".",
        include_ignored: bool = False,
    ) -> GlobResult:
        """Async glob pattern matching with gitignore support."""
        return await asyncio.to_thread(
            self.glob, pattern, path=path, include_ignored=include_ignored
        )

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
        return self._local_fs.grep(pattern, path=path, glob=glob, output_mode=output_mode)

    async def agrep(
        self,
        pattern: str,
        *,
        path: str = ".",
        glob: str | None = None,
        output_mode: str = "files_with_matches",
    ) -> GrepResult | list[str] | str:
        """Async search for pattern in files."""
        return await self._local_fs.agrep(pattern, path=path, glob=glob, output_mode=output_mode)

    # ========================================================================
    # Framework Integration
    # ========================================================================

    @classmethod
    def from_framework(
        cls,
        *,
        virtual_mode: bool = True,
        max_file_size_mb: int = 10,
    ) -> WorkspaceFilesystem:
        """Create a WorkspaceFilesystem using the process-default workspace.

        This factory method resolves the process workspace and creates a
        WorkspaceFilesystem instance configured for framework operations.

        Args:
            virtual_mode: Whether to sandbox paths to workspace.
            max_file_size_mb: Maximum file size in MB.

        Returns:
            WorkspaceFilesystem instance configured for the process workspace.
        """
        workspace = resolve_process_workspace_root()
        return cls(
            workspace=workspace,
            virtual_mode=virtual_mode,
            max_file_size_mb=max_file_size_mb,
        )

    def get_local_filesystem(self) -> LocalFilesystem:
        """Get the underlying LocalFilesystem instance.

        Returns:
            The LocalFilesystem instance used for actual operations.
        """
        return self._local_fs
