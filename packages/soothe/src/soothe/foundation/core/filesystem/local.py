"""Local filesystem implementation of UnifiedFilesystem."""

from __future__ import annotations

import asyncio
import fnmatch
import hashlib
import logging
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import aiofiles
import pathspec

from .exceptions import (
    DirectoryNotEmptyError,
    FilesystemError,
    InvalidPathError,
    NotADirectoryError,
    NotAFileError,
    PathNotFoundError,
    PathTraversalError,
    PermissionDeniedError,
)
from .grep_search import grep_with_ag, is_ag_available
from .protocol import (
    BatchedEditOperation,
    BatchedEditResult,
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

logger = logging.getLogger(__name__)

# Incremental grep batching constants (IG-510, IG-520)
_GREP_BATCH_SIZE: int = 100  # files per batch
_GREP_MAX_BATCHES: int = 10  # stop after this many batches
# Per-batch and total budgets kept below the 30s tool timeout so the fallback
# returns partial results before the tool-timeout middleware kills the call.
_GREP_BATCH_TIMEOUT_S: float = 2.0  # timeout per batch
_GREP_MAX_FILE_SIZE_BYTES: int = 1_000_000  # 1 MB per file limit
_GREP_TOTAL_TIMEOUT_S: float = 25.0  # overall grep timeout (< 30s tool limit)
_GREP_MAX_TOTAL_BYTES: int = 10 * 1024 * 1024  # 10 MB total read limit
# When ag is unavailable, refuse to Python-walk trees larger than this. A 30s
# hang becomes a sub-second structured "scope too large" error the agent can act
# on. Real workspaces (gitignored) are well under this; ~1754 files at the time
# of writing. See IG-520.
_GREP_FALLBACK_FILE_LIMIT: int = 50_000
# Defense-in-depth floor: always skip these even when a repo forgets to
# .gitignore them. The .gitignore-aware walker (pathspec) is the primary filter;
# this set is the backstop when pathspec is unavailable or no .gitignore exists.
_GREP_IGNORE_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".svn",
        ".hg",  # VCS
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",  # Python caches
        "node_modules",
        "bower_components",  # JS deps
        ".venv",
        "venv",
        "env",
        ".env",  # Python virtualenvs
        "dist",
        "build",
        ".tox",
        "*.egg-info",  # Build artifacts
        ".idea",
        ".vscode",
        ".pytest_cache",  # IDE/tool dirs
        "target",
        "out",
        "bin",
        "obj",  # Build outputs (Java, .NET, etc.)
    }
)


class LocalFilesystem(UnifiedFilesystem):
    """Local filesystem implementation.

    This implementation uses Python's pathlib and standard library
    for filesystem operations. It provides full UnifiedFilesystem
    functionality with local file storage.
    """

    def __init__(
        self,
        workspace: str | Path,
        *,
        virtual_mode: bool = True,
        max_file_size_mb: int = 10,
        backup_dir: str | Path = ".backups",
    ) -> None:
        """Initialize local filesystem.

        Args:
            workspace: Root workspace directory.
            virtual_mode: Whether to sandbox paths to workspace.
            max_file_size_mb: Maximum file size in MB.
            backup_dir: Directory for backup files.
        """
        super().__init__(
            workspace=workspace,
            virtual_mode=virtual_mode,
            max_file_size_mb=max_file_size_mb,
        )
        self._backup_dir = Path(backup_dir)
        # Cache for compiled .gitignore specs keyed by (workspace_root, search_root) tuple.
        # None means no .gitignore found; pathspec.PathSpec means compiled patterns.
        self._gitignore_cache: dict[tuple[Path, Path], pathspec.PathSpec | None] = {}

    def _resolve_path(self, path: str) -> Path:
        """Resolve path within workspace.

        Args:
            path: Input path.

        Returns:
            Resolved Path object.

        Raises:
            PathTraversalError: If path escapes workspace.
        """
        self._validate_path(path)

        # Handle empty or root paths
        if not path or path.strip() in {"", ".", "/"}:
            return self.workspace

        # Expand user and resolve
        expanded = Path(path).expanduser()

        if expanded.is_absolute():
            if self.virtual_mode:
                # In virtual mode, absolute paths are relative to workspace
                # Strip leading slash and join with workspace
                rel_path = path.lstrip("/")
                resolved = self.workspace / rel_path
            else:
                # Non-virtual mode: allow absolute paths outside workspace
                resolved = expanded.resolve()
        else:
            # Relative path: resolve against workspace
            resolved = (self.workspace / path).resolve()

        # Bounds check only in virtual mode (sandboxed)
        if self.virtual_mode and not self._is_within_workspace(resolved):
            raise PathTraversalError(
                path=path,
                attempted_path=str(resolved),
                workspace=str(self.workspace),
            )

        return resolved

    def _create_backup(self, path: Path) -> Path | None:
        """Create backup of file before modification.

        Args:
            path: Path to backup.

        Returns:
            Path to backup file, or None if backup not needed.
        """
        if not path.exists():
            return None

        backup_dir = self.workspace / self._backup_dir
        backup_dir.mkdir(parents=True, exist_ok=True)

        timestamp = __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{path.name}.{timestamp}.bak"
        backup_path = backup_dir / backup_name

        shutil.copy2(path, backup_path)
        return backup_path

    def _result_path(self, resolved: Path) -> str:
        """Compute result path string for WriteResult/EditResult.

        Returns workspace-relative path if within workspace,
        otherwise absolute path (for virtual_mode=False case).

        Args:
            resolved: Resolved absolute path.

        Returns:
            Path string for result object.
        """
        if self._is_within_workspace(resolved):
            return str(resolved.relative_to(self.workspace))
        return str(resolved)

    def _compute_hash(self, content: str | bytes) -> str:
        """Compute MD5 hash of content."""
        if isinstance(content, str):
            content = content.encode("utf-8")
        return hashlib.md5(content).hexdigest()[:8]

    # =======================================================================
    # Path Operations
    # =======================================================================

    def resolve_path(self, path: str) -> Path:
        """Resolve path relative to workspace."""
        return self._resolve_path(path)

    def exists(self, path: str) -> bool:
        """Check if path exists."""
        try:
            resolved = self._resolve_path(path)
            return resolved.exists()
        except (PathTraversalError, InvalidPathError):
            return False

    def is_file(self, path: str) -> bool:
        """Check if path is a file."""
        try:
            resolved = self._resolve_path(path)
            return resolved.is_file()
        except (PathTraversalError, InvalidPathError):
            return False

    def is_dir(self, path: str) -> bool:
        """Check if path is a directory."""
        try:
            resolved = self._resolve_path(path)
            return resolved.is_dir()
        except (PathTraversalError, InvalidPathError):
            return False

    # =======================================================================
    # Read Operations
    # =======================================================================

    def read(
        self,
        path: str,
        *,
        offset: int = 0,
        limit: int | None = None,
        encoding: str = "utf-8",
    ) -> ReadResult:
        """Read file contents."""
        resolved = self._resolve_path(path)

        if not resolved.exists():
            raise PathNotFoundError(f"File not found: {path}", path=path)
        if not resolved.is_file():
            raise NotAFileError(f"Not a file: {path}", path=path)

        # Check file size
        file_size = resolved.stat().st_size
        if file_size > self.max_file_size_bytes:
            raise FilesystemError(
                f"File too large: {file_size} bytes (max: {self.max_file_size_bytes})",
                path=path,
            )

        # Read content
        try:
            with open(resolved, "rb") as f:
                if offset:
                    f.seek(offset)
                content_bytes = f.read(limit) if limit else f.read()
        except PermissionError as e:
            raise PermissionDeniedError(f"Permission denied: {path}", path=path) from e
        except OSError as e:
            raise FilesystemError(f"Read error: {e}", path=path) from e

        # Try to decode as text
        is_binary = False
        try:
            content = content_bytes.decode(encoding)
        except UnicodeDecodeError:
            # Binary file - encode as base64
            import base64

            content = base64.b64encode(content_bytes).decode("ascii")
            is_binary = True

        return ReadResult(
            content=content,
            is_binary=is_binary,
            encoding=encoding if not is_binary else "base64",
            truncated=limit is not None and len(content_bytes) == limit,
            total_size=file_size,
        )

    async def aread(
        self,
        path: str,
        *,
        offset: int = 0,
        limit: int | None = None,
        encoding: str = "utf-8",
    ) -> ReadResult:
        """Async read file contents using aiofiles (IG-517)."""
        resolved = self._resolve_path(path)

        if not resolved.exists():
            raise PathNotFoundError(f"File not found: {path}", path=path)
        if not resolved.is_file():
            raise NotAFileError(f"Not a file: {path}", path=path)

        # Check file size
        file_size = resolved.stat().st_size
        if file_size > self.max_file_size_bytes:
            raise FilesystemError(
                f"File too large: {file_size} bytes (max: {self.max_file_size_bytes})",
                path=path,
            )

        # Async read content
        try:
            async with aiofiles.open(resolved, "rb") as f:
                if offset:
                    await f.seek(offset)
                content_bytes = await f.read(limit) if limit else await f.read()
        except PermissionError as e:
            raise PermissionDeniedError(f"Permission denied: {path}", path=path) from e
        except OSError as e:
            raise FilesystemError(f"Read error: {e}", path=path) from e

        # Try to decode as text
        is_binary = False
        try:
            content = content_bytes.decode(encoding)
        except UnicodeDecodeError:
            # Binary file - encode as base64
            import base64

            content = base64.b64encode(content_bytes).decode("ascii")
            is_binary = True

        return ReadResult(
            content=content,
            is_binary=is_binary,
            encoding=encoding if not is_binary else "base64",
            truncated=limit is not None and len(content_bytes) == limit,
            total_size=file_size,
        )

    # =======================================================================
    # Write Operations
    # =======================================================================

    def write(
        self,
        path: str,
        content: str | bytes,
        *,
        encoding: str = "utf-8",
        backup: bool = False,
    ) -> WriteResult:
        """Write content to file."""
        resolved = self._resolve_path(path)

        # Create backup if needed
        backup_path = None
        if backup and resolved.exists():
            backup_path = self._create_backup(resolved)

        # Ensure parent directory exists
        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
        except PermissionError as e:
            raise PermissionDeniedError(f"Permission denied: {path}", path=path) from e
        except OSError as e:
            raise FilesystemError(f"Cannot create directory for {path}: {e}", path=path) from e

        # Write content
        created = not resolved.exists()
        try:
            if isinstance(content, str):
                with open(resolved, "w", encoding=encoding) as f:
                    f.write(content)
                bytes_written = len(content.encode(encoding))
            else:
                with open(resolved, "wb") as f:
                    f.write(content)
                bytes_written = len(content)
        except PermissionError as e:
            raise PermissionDeniedError(f"Permission denied: {path}", path=path) from e
        except OSError as e:
            raise FilesystemError(f"Write error: {e}", path=path) from e

        # Compute result path: use relative path if within workspace, else absolute
        result_path = self._result_path(resolved)
        result_backup = self._result_path(backup_path) if backup_path else None

        return WriteResult(
            path=result_path,
            bytes_written=bytes_written,
            created=created,
            backup_path=result_backup,
        )

    async def awrite(
        self,
        path: str,
        content: str | bytes,
        *,
        encoding: str = "utf-8",
        backup: bool = False,
    ) -> WriteResult:
        """Async write content to file using aiofiles (IG-517)."""
        resolved = self._resolve_path(path)

        # Create backup if needed (sync - rare operation)
        backup_path = None
        if backup and resolved.exists():
            backup_path = self._create_backup(resolved)

        # Ensure parent directory exists
        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
        except PermissionError as e:
            raise PermissionDeniedError(f"Permission denied: {path}", path=path) from e
        except OSError as e:
            raise FilesystemError(f"Cannot create directory for {path}: {e}", path=path) from e

        # Write content async
        created = not resolved.exists()
        try:
            if isinstance(content, str):
                async with aiofiles.open(resolved, "w", encoding=encoding) as f:
                    await f.write(content)
                bytes_written = len(content.encode(encoding))
            else:
                async with aiofiles.open(resolved, "wb") as f:
                    await f.write(content)
                bytes_written = len(content)
        except PermissionError as e:
            raise PermissionDeniedError(f"Permission denied: {path}", path=path) from e
        except OSError as e:
            raise FilesystemError(f"Write error: {e}", path=path) from e

        # Compute result path: use relative path if within workspace, else absolute
        result_path = self._result_path(resolved)
        result_backup = self._result_path(backup_path) if backup_path else None

        return WriteResult(
            path=result_path,
            bytes_written=bytes_written,
            created=created,
            backup_path=result_backup,
        )

    # =======================================================================
    # Edit Operations
    # =======================================================================

    def edit(
        self,
        path: str,
        old_string: str,
        new_string: str,
        *,
        backup: bool = True,
    ) -> EditResult:
        """Replace old_string with new_string in file."""
        resolved = self._resolve_path(path)

        if not resolved.exists():
            raise PathNotFoundError(f"File not found: {path}", path=path)

        # Read current content
        with open(resolved, encoding="utf-8") as f:
            content = f.read()

        old_hash = self._compute_hash(content)

        # Check for matches
        if old_string not in content:
            raise FilesystemError(f"String not found in file: {old_string!r}", path=path)

        count = content.count(old_string)
        if count > 1:
            raise FilesystemError(
                f"Multiple matches ({count}) found for string: {old_string!r}",
                path=path,
            )

        # Create backup
        backup_path = None
        if backup:
            backup_path = self._create_backup(resolved)

        # Apply edit
        new_content = content.replace(old_string, new_string, 1)
        new_hash = self._compute_hash(new_content)

        # Count changed lines (approximate)
        old_lines = old_string.count("\n")
        new_lines = new_string.count("\n")
        lines_changed = abs(new_lines - old_lines) + 1

        # Write back
        with open(resolved, "w", encoding="utf-8") as f:
            f.write(new_content)

        return EditResult(
            path=self._result_path(resolved),
            old_hash=old_hash,
            new_hash=new_hash,
            lines_changed=lines_changed,
            backup_path=self._result_path(backup_path) if backup_path else None,
        )

    async def aedit(
        self,
        path: str,
        old_string: str,
        new_string: str,
        *,
        backup: bool = True,
    ) -> EditResult:
        """Async replace old_string with new_string in file using aiofiles (IG-517)."""
        resolved = self._resolve_path(path)

        if not resolved.exists():
            raise PathNotFoundError(f"File not found: {path}", path=path)

        # Async read current content
        async with aiofiles.open(resolved, encoding="utf-8") as f:
            content = await f.read()

        old_hash = self._compute_hash(content)

        # Check for matches
        if old_string not in content:
            raise FilesystemError(f"String not found in file: {old_string!r}", path=path)

        count = content.count(old_string)
        if count > 1:
            raise FilesystemError(
                f"Multiple matches ({count}) found for string: {old_string!r}",
                path=path,
            )

        # Create backup (sync - rare operation)
        backup_path = None
        if backup:
            backup_path = self._create_backup(resolved)

        # Apply edit
        new_content = content.replace(old_string, new_string, 1)
        new_hash = self._compute_hash(new_content)

        # Count changed lines (approximate)
        old_lines = old_string.count("\n")
        new_lines = new_string.count("\n")
        lines_changed = abs(new_lines - old_lines) + 1

        # Async write back
        async with aiofiles.open(resolved, "w", encoding="utf-8") as f:
            await f.write(new_content)

        return EditResult(
            path=self._result_path(resolved),
            old_hash=old_hash,
            new_hash=new_hash,
            lines_changed=lines_changed,
            backup_path=self._result_path(backup_path) if backup_path else None,
        )

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
        resolved = self._resolve_path(path)

        if not resolved.exists():
            raise PathNotFoundError(f"File not found: {path}", path=path)

        with open(resolved, encoding="utf-8") as f:
            lines = f.readlines()

        insert_mode = end_line == start_line - 1
        if insert_mode:
            if start_line < 1 or start_line > len(lines) + 1:
                raise FilesystemError(
                    f"Invalid line number: {start_line} (file has {len(lines)} lines)",
                    path=path,
                )
        elif start_line < 1 or end_line > len(lines) or start_line > end_line:
            raise FilesystemError(
                f"Invalid line range: {start_line}-{end_line} (file has {len(lines)} lines)",
                path=path,
            )

        old_content = "".join(lines)
        old_hash = self._compute_hash(old_content)

        # Create backup
        backup_path = None
        if backup:
            backup_path = self._create_backup(resolved)

        new_lines = new_content.split("\n")
        if new_lines and new_lines[-1] == "":
            new_lines = new_lines[:-1]

        formatted_new_lines = [line + "\n" for line in new_lines]
        if insert_mode:
            result_lines = lines[: start_line - 1] + formatted_new_lines + lines[start_line - 1 :]
            lines_changed = len(formatted_new_lines)
        else:
            result_lines = lines[: start_line - 1] + formatted_new_lines + lines[end_line:]
            lines_changed = end_line - start_line + 1

        new_full_content = "".join(result_lines)
        new_hash = self._compute_hash(new_full_content)

        with open(resolved, "w", encoding="utf-8") as f:
            f.writelines(result_lines)

        return EditResult(
            path=self._result_path(resolved),
            old_hash=old_hash,
            new_hash=new_hash,
            lines_changed=lines_changed,
            backup_path=self._result_path(backup_path) if backup_path else None,
        )

    async def aedit_lines(
        self,
        path: str,
        start_line: int,
        end_line: int,
        new_content: str,
        *,
        backup: bool = True,
    ) -> EditResult:
        """Async replace specific line range in file using aiofiles (IG-517)."""
        resolved = self._resolve_path(path)

        if not resolved.exists():
            raise PathNotFoundError(f"File not found: {path}", path=path)

        # Async read lines
        async with aiofiles.open(resolved, encoding="utf-8") as f:
            content = await f.read()
        lines = content.splitlines(keepends=True)

        insert_mode = end_line == start_line - 1
        if insert_mode:
            if start_line < 1 or start_line > len(lines) + 1:
                raise FilesystemError(
                    f"Invalid line number: {start_line} (file has {len(lines)} lines)",
                    path=path,
                )
        elif start_line < 1 or end_line > len(lines) or start_line > end_line:
            raise FilesystemError(
                f"Invalid line range: {start_line}-{end_line} (file has {len(lines)} lines)",
                path=path,
            )

        old_hash = self._compute_hash(content)

        # Create backup (sync - rare operation)
        backup_path = None
        if backup:
            backup_path = self._create_backup(resolved)

        new_lines = new_content.split("\n")
        if new_lines and new_lines[-1] == "":
            new_lines = new_lines[:-1]

        formatted_new_lines = [line + "\n" for line in new_lines]
        if insert_mode:
            result_lines = lines[: start_line - 1] + formatted_new_lines + lines[start_line - 1 :]
            lines_changed = len(formatted_new_lines)
        else:
            result_lines = lines[: start_line - 1] + formatted_new_lines + lines[end_line:]
            lines_changed = end_line - start_line + 1

        new_full_content = "".join(result_lines)
        new_hash = self._compute_hash(new_full_content)

        # Async write back
        async with aiofiles.open(resolved, "w", encoding="utf-8") as f:
            await f.writelines(result_lines)

        return EditResult(
            path=self._result_path(resolved),
            old_hash=old_hash,
            new_hash=new_hash,
            lines_changed=lines_changed,
            backup_path=self._result_path(backup_path) if backup_path else None,
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
        return self.edit_lines(path, line, line - 1, content, backup=backup)

    async def ainsert_lines(
        self,
        path: str,
        line: int,
        content: str,
        *,
        backup: bool = True,
    ) -> EditResult:
        """Async insert content at specific line number."""
        return self.insert_lines(path, line, content, backup=backup)

    def delete_lines(
        self,
        path: str,
        start_line: int,
        end_line: int,
        *,
        backup: bool = True,
    ) -> EditResult:
        """Delete specific line range from file."""
        # Delete is equivalent to replacing with empty content
        return self.edit_lines(path, start_line, end_line, "", backup=backup)

    async def adelete_lines(
        self,
        path: str,
        start_line: int,
        end_line: int,
        *,
        backup: bool = True,
    ) -> EditResult:
        """Async delete specific line range from file."""
        return self.delete_lines(path, start_line, end_line, backup=backup)

    async def aedit_batched(
        self,
        path: str,
        operations: list[BatchedEditOperation],
        *,
        backup: bool = True,
    ) -> BatchedEditResult:
        """Apply multiple edit operations to a file in one read/modify/write cycle (IG-517).

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
        resolved = self._resolve_path(path)

        if not resolved.exists():
            raise PathNotFoundError(f"File not found: {path}", path=path)

        # Separate operations by type
        deletions = [op for op in operations if op.operation_type == "delete"]
        insertions = [op for op in operations if op.operation_type == "insert"]
        replacements = [op for op in operations if op.operation_type == "replace"]

        # Check for overlaps in replacements
        for i, op_a in enumerate(replacements):
            for op_b in replacements[i + 1 :]:
                if self._ranges_overlap(op_a, op_b):
                    return BatchedEditResult(
                        path=self._result_path(resolved),
                        error=f"Overlapping edits: lines {op_a.start_line}-{op_a.end_line} and {op_b.start_line}-{op_b.end_line}",
                        failed_operations=[
                            op_a.original_call_id or "",
                            op_b.original_call_id or "",
                        ],
                    )

        # Async read file
        async with aiofiles.open(resolved, encoding="utf-8") as f:
            content = await f.read()
        lines = content.splitlines(keepends=True)
        old_hash = self._compute_hash(content)

        # Create backup (sync - rare operation)
        backup_path = None
        if backup:
            backup_path = self._create_backup(resolved)

        # Track changes
        total_lines_changed = 0
        operations_applied = 0
        failed_ops: list[str] = []

        # Apply deletions first (sorted descending to preserve indices)
        deletions_sorted = sorted(deletions, key=lambda op: op.start_line, reverse=True)
        for op in deletions_sorted:
            if op.start_line < 1 or op.end_line > len(lines) or op.start_line > op.end_line:
                failed_ops.append(op.original_call_id or "")
                continue
            lines = lines[: op.start_line - 1] + lines[op.end_line :]
            total_lines_changed += op.end_line - op.start_line + 1
            operations_applied += 1

        # Apply insertions (sorted by line number ascending)
        insertions_sorted = sorted(insertions, key=lambda op: op.start_line)
        for op in insertions_sorted:
            if op.start_line < 1 or op.start_line > len(lines) + 1:
                failed_ops.append(op.original_call_id or "")
                continue
            new_lines = op.content.split("\n")
            if new_lines and new_lines[-1] == "":
                new_lines = new_lines[:-1]
            formatted_new_lines = [line + "\n" for line in new_lines]
            lines = lines[: op.start_line - 1] + formatted_new_lines + lines[op.start_line - 1 :]
            total_lines_changed += len(formatted_new_lines)
            operations_applied += 1

        # Apply replacements (sorted descending to preserve indices)
        replacements_sorted = sorted(replacements, key=lambda op: op.start_line, reverse=True)
        for op in replacements_sorted:
            if op.start_line < 1 or op.end_line > len(lines) or op.start_line > op.end_line:
                failed_ops.append(op.original_call_id or "")
                continue
            new_lines = op.content.split("\n")
            if new_lines and new_lines[-1] == "":
                new_lines = new_lines[:-1]
            formatted_new_lines = [line + "\n" for line in new_lines]
            lines = lines[: op.start_line - 1] + formatted_new_lines + lines[op.end_line :]
            total_lines_changed += max(op.end_line - op.start_line + 1, len(formatted_new_lines))
            operations_applied += 1

        # Compute new hash
        new_content = "".join(lines)
        new_hash = self._compute_hash(new_content)

        # Async write back
        async with aiofiles.open(resolved, "w", encoding="utf-8") as f:
            await f.write(new_content)

        return BatchedEditResult(
            path=self._result_path(resolved),
            old_hash=old_hash,
            new_hash=new_hash,
            total_lines_changed=total_lines_changed,
            operations_applied=operations_applied,
            failed_operations=failed_ops if failed_ops else None,
            backup_path=self._result_path(backup_path) if backup_path else None,
        )

    def _ranges_overlap(self, a: BatchedEditOperation, b: BatchedEditOperation) -> bool:
        """Check if two edit operations have overlapping line ranges."""
        return a.start_line <= b.end_line and b.start_line <= a.end_line

    def apply_diff(
        self,
        path: str,
        diff: str,
        *,
        backup: bool = True,
    ) -> EditResult:
        """Apply unified diff patch to file."""
        resolved = self._resolve_path(path)

        if not resolved.exists():
            raise PathNotFoundError(f"File not found: {path}", path=path)

        # Create backup
        backup_path = None
        if backup:
            backup_path = self._create_backup(resolved)

        # Use patch command
        try:
            subprocess.run(
                ["patch", "-u", str(resolved)],
                input=diff,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            raise FilesystemError(
                f"Failed to apply diff: {e.stderr}",
                path=path,
            ) from e
        except FileNotFoundError:
            raise FilesystemError(
                "patch command not found. Please install patch.",
                path=path,
            )

        return EditResult(
            path=self._result_path(resolved),
            backup_path=self._result_path(backup_path) if backup_path else None,
        )

    async def aapply_diff(
        self,
        path: str,
        diff: str,
        *,
        backup: bool = True,
    ) -> EditResult:
        """Async apply unified diff patch to file."""
        return self.apply_diff(path, diff, backup=backup)

    # =======================================================================
    # Directory Operations
    # =======================================================================

    def ls(
        self,
        path: str = ".",
        *,
        include_info: bool = False,
    ) -> list[str] | list[FileInfo]:
        """List directory contents."""
        resolved = self._resolve_path(path)

        if not resolved.exists():
            raise PathNotFoundError(f"Directory not found: {path}", path=path)
        if not resolved.is_dir():
            raise NotADirectoryError(f"Not a directory: {path}", path=path)

        entries = []
        for entry in resolved.iterdir():
            if include_info:
                entries.append(self._get_file_info(entry))
            else:
                entries.append(entry.name)

        return entries

    async def als(
        self,
        path: str = ".",
        *,
        include_info: bool = False,
    ) -> list[str] | list[FileInfo]:
        """Async list directory contents."""
        return self.ls(path, include_info=include_info)

    def _get_file_info(self, path: Path) -> FileInfo:
        """Get FileInfo for a path."""
        stat = path.stat()
        from datetime import datetime

        modified_at = datetime.fromtimestamp(stat.st_mtime)
        created_at = datetime.fromtimestamp(stat.st_ctime)

        # Get permissions as octal
        permissions = oct(stat.st_mode)[-3:]

        return FileInfo(
            path=self._result_path(path),
            is_dir=path.is_dir(),
            size=stat.st_size,
            modified_at=modified_at,
            created_at=created_at,
            permissions=permissions,
        )

    def mkdir(
        self,
        path: str,
        *,
        recursive: bool = False,
        exist_ok: bool = False,
    ) -> FileInfo:
        """Create directory."""
        resolved = self._resolve_path(path)

        try:
            resolved.mkdir(parents=recursive, exist_ok=exist_ok)
        except FileExistsError:
            if not exist_ok:
                raise FilesystemError(f"Directory already exists: {path}", path=path)
        except PermissionError as e:
            raise PermissionDeniedError(f"Permission denied: {path}", path=path) from e

        return self._get_file_info(resolved)

    async def amkdir(
        self,
        path: str,
        *,
        recursive: bool = False,
        exist_ok: bool = False,
    ) -> FileInfo:
        """Async create directory."""
        return self.mkdir(path, recursive=recursive, exist_ok=exist_ok)

    def rmdir(
        self,
        path: str,
        *,
        recursive: bool = False,
        backup: bool = False,
    ) -> DeleteResult:
        """Remove directory."""
        resolved = self._resolve_path(path)

        if not resolved.exists():
            raise PathNotFoundError(f"Directory not found: {path}", path=path)
        if not resolved.is_dir():
            raise NotADirectoryError(f"Not a directory: {path}", path=path)

        # Check if empty
        if not recursive and any(resolved.iterdir()):
            raise DirectoryNotEmptyError(f"Directory not empty: {path}", path=path)

        # Create backup if needed
        backup_path = None
        if backup:
            backup_path = self._create_backup(resolved)

        try:
            if recursive:
                shutil.rmtree(resolved)
            else:
                resolved.rmdir()
        except PermissionError as e:
            raise PermissionDeniedError(f"Permission denied: {path}", path=path) from e

        return DeleteResult(
            path=self._result_path(resolved),
            was_directory=True,
            backup_path=self._result_path(backup_path) if backup_path else None,
        )

    async def armdir(
        self,
        path: str,
        *,
        recursive: bool = False,
        backup: bool = False,
    ) -> DeleteResult:
        """Async remove directory."""
        return self.rmdir(path, recursive=recursive, backup=backup)

    # =======================================================================
    # File Operations
    # =======================================================================

    def delete(
        self,
        path: str,
        *,
        backup: bool = True,
    ) -> DeleteResult:
        """Delete file."""
        resolved = self._resolve_path(path)

        if not resolved.exists():
            raise PathNotFoundError(f"File not found: {path}", path=path)
        if not resolved.is_file():
            raise NotAFileError(f"Not a file: {path}", path=path)

        # Create backup
        backup_path = None
        if backup:
            backup_path = self._create_backup(resolved)

        try:
            resolved.unlink()
        except PermissionError as e:
            raise PermissionDeniedError(f"Permission denied: {path}", path=path) from e

        return DeleteResult(
            path=self._result_path(resolved),
            was_directory=False,
            backup_path=self._result_path(backup_path) if backup_path else None,
        )

    async def adelete(
        self,
        path: str,
        *,
        backup: bool = True,
    ) -> DeleteResult:
        """Async delete file."""
        return self.delete(path, backup=backup)

    def info(self, path: str) -> FileInfo:
        """Get file/directory information."""
        resolved = self._resolve_path(path)

        if not resolved.exists():
            raise PathNotFoundError(f"Path not found: {path}", path=path)

        return self._get_file_info(resolved)

    async def ainfo(self, path: str) -> FileInfo:
        """Async get file/directory information."""
        return self.info(path)

    def copy(
        self,
        src: str,
        dst: str,
        *,
        overwrite: bool = False,
    ) -> FileInfo:
        """Copy file or directory."""
        src_resolved = self._resolve_path(src)
        dst_resolved = self._resolve_path(dst)

        if not src_resolved.exists():
            raise PathNotFoundError(f"Source not found: {src}", path=src)

        if dst_resolved.exists() and not overwrite:
            raise FilesystemError(f"Destination exists: {dst}", path=dst)

        try:
            if src_resolved.is_dir():
                shutil.copytree(src_resolved, dst_resolved, dirs_exist_ok=overwrite)
            else:
                shutil.copy2(src_resolved, dst_resolved)
        except PermissionError as e:
            raise PermissionDeniedError("Permission denied", path=src) from e

        return self._get_file_info(dst_resolved)

    async def acopy(
        self,
        src: str,
        dst: str,
        *,
        overwrite: bool = False,
    ) -> FileInfo:
        """Async copy file or directory."""
        return self.copy(src, dst, overwrite=overwrite)

    def move(
        self,
        src: str,
        dst: str,
        *,
        overwrite: bool = False,
    ) -> FileInfo:
        """Move/rename file or directory."""
        src_resolved = self._resolve_path(src)
        dst_resolved = self._resolve_path(dst)

        if not src_resolved.exists():
            raise PathNotFoundError(f"Source not found: {src}", path=src)

        if dst_resolved.exists() and not overwrite:
            raise FilesystemError(f"Destination exists: {dst}", path=dst)

        try:
            shutil.move(str(src_resolved), str(dst_resolved))
        except PermissionError as e:
            raise PermissionDeniedError("Permission denied", path=src) from e

        return self._get_file_info(dst_resolved)

    async def amove(
        self,
        src: str,
        dst: str,
        *,
        overwrite: bool = False,
    ) -> FileInfo:
        """Async move/rename file or directory."""
        return self.move(src, dst, overwrite=overwrite)

    # =======================================================================
    # Search Operations
    # =======================================================================

    def glob(
        self,
        pattern: str,
        *,
        path: str = ".",
        include_ignored: bool = False,
    ) -> GlobResult:
        """Glob pattern matching."""
        resolved = self._resolve_path(path)

        if not resolved.is_dir():
            return GlobResult(matches=[], error=f"Not a directory: {path}")

        matches = []
        # Use pathlib's glob for proper ** handling
        try:
            for match in resolved.glob(pattern):
                rel_path = str(match.relative_to(resolved))
                matches.append(rel_path)
        except OSError:
            pass

        return GlobResult(matches=matches)

    async def aglob(
        self,
        pattern: str,
        *,
        path: str = ".",
        include_ignored: bool = False,
    ) -> GlobResult:
        """Async glob pattern matching."""
        return self.glob(pattern, path=path, include_ignored=include_ignored)

    def grep(
        self,
        pattern: str,
        *,
        path: str = ".",
        glob: str | None = None,
        output_mode: str = "files_with_matches",
        continuation_token: dict[str, Any] | None = None,
    ) -> GrepResult | list[str] | str:
        """Search for pattern in files with incremental batching.

        Uses bounded batch processing to prevent indefinite hangs on large
        directories. Returns partial results with continuation token when
        search is incomplete, allowing caller to request more.

        Args:
            pattern: Regex pattern to search for.
            path: Directory or file to search.
            glob: Optional glob pattern for file filtering.
            output_mode: "files_with_matches", "count", or "content".
            continuation_token: Token from previous partial result to continue.

        Returns:
            GrepResult (with is_partial=True if incomplete), or simplified
            list[str] / str for files_with_matches / count modes.
        """
        resolved = self._resolve_path(path)

        if not resolved.is_dir() and not resolved.is_file():
            return GrepResult(matches=[])

        # Single file: process directly (no batching needed)
        if resolved.is_file():
            return self._grep_single_file(pattern, resolved=resolved, output_mode=output_mode)

        # Directory: use incremental batching
        if is_ag_available():
            ag_result = grep_with_ag(
                workspace=self.workspace,
                search_path=resolved,
                pattern=pattern,
                glob=glob,
                output_mode=output_mode,
            )
            if ag_result is not None:
                # ag succeeded, return result (may need to wrap in GrepResult)
                return ag_result

        # ag unavailable: gate Python fallback by file count to avoid hangs.
        # The agent receives a structured "scope too large" error it can act on.
        gitignore_spec = self._load_gitignore(resolved)
        estimated_file_count = self._estimate_file_count(resolved, gitignore_spec)
        if estimated_file_count > _GREP_FALLBACK_FILE_LIMIT:
            logger.warning(
                "Python grep fallback gated: estimated %d files > limit %d. "
                "Install 'ag' (The Silver Searcher) for large directory search.",
                estimated_file_count,
                _GREP_FALLBACK_FILE_LIMIT,
            )
            return GrepResult(
                matches=[],
                files_searched=0,
                total_files=estimated_file_count,
                error=(
                    f"Search scope too large ({estimated_file_count} files). "
                    "Install 'ag' (The Silver Searcher) for efficient search, "
                    "or narrow the search path/glob pattern."
                ),
            )

        return self._grep_python_walk_incremental(
            pattern,
            resolved=resolved,
            glob=glob,
            output_mode=output_mode,
            continuation_token=continuation_token,
        )

    def _grep_single_file(
        self,
        pattern: str,
        *,
        resolved: Path,
        output_mode: str,
    ) -> GrepResult | list[str] | str:
        """Grep a single file (no batching needed)."""
        rel_path = self._result_path(resolved)
        matches: list[GrepMatch] = []

        try:
            # Check file size before reading
            stat = resolved.stat()
            if stat.st_size > _GREP_MAX_FILE_SIZE_BYTES:
                return GrepResult(
                    matches=[],
                    files_searched=0,
                    error=f"File too large: {stat.st_size} bytes (max: {_GREP_MAX_FILE_SIZE_BYTES})",
                )

            with open(resolved, encoding="utf-8", errors="ignore") as f:
                content = f.read()

            for line_num, line in enumerate(content.split("\n"), 1):
                for match in re.finditer(pattern, line):
                    matches.append(
                        GrepMatch(
                            path=rel_path,
                            line_number=line_num,
                            line_content=line,
                            match_start=match.start(),
                            match_end=match.end(),
                        )
                    )

            result = GrepResult(matches=matches, files_searched=1, total_matches=len(matches))

            if output_mode == "files_with_matches":
                return [rel_path] if matches else []
            if output_mode == "count":
                return str(len(matches))
            return result

        except OSError as e:
            return GrepResult(matches=[], files_searched=0, error=str(e))

    def _grep_python_walk_incremental(
        self,
        pattern: str,
        *,
        resolved: Path,
        glob: str | None,
        output_mode: str,
        continuation_token: dict[str, Any] | None = None,
    ) -> GrepResult | list[str] | str:
        """Incremental grep: process files in bounded batches with timeout.

        IG-510: Prevents indefinite hangs by:
        - Processing files in batches of _GREP_BATCH_SIZE
        - Stopping after _GREP_MAX_BATCHES batches
        - Timing out each batch at _GREP_BATCH_TIMEOUT_S
        - Skipping large files and ignored directories
        - Limiting total bytes read to _GREP_MAX_TOTAL_BYTES

        Returns partial results with continuation token when incomplete.
        """
        if not resolved.is_dir():
            return GrepResult(matches=[])

        # Compile pattern regex
        try:
            regex = re.compile(pattern)
        except re.error as e:
            return GrepResult(matches=[], error=f"Invalid regex: {e}")

        # Collect file list (with continuation support)
        all_files: list[Path] = []
        start_index = 0

        if continuation_token is not None:
            # Resume from previous partial search
            cached_files = continuation_token.get("cached_files")
            start_index = continuation_token.get("next_file_index", 0)
            if cached_files:
                all_files = [Path(f) for f in cached_files]
            else:
                # No cached files, need to re-collect (shouldn't happen normally)
                logger.warning("Continuation token missing cached_files, re-collecting")
                all_files = self._collect_grep_files(resolved, glob)

        if not all_files:
            # First run: collect files with ignore filter
            all_files = self._collect_grep_files(resolved, glob)
            start_index = 0

        total_files = len(all_files)
        if total_files == 0:
            return GrepResult(matches=[], files_searched=0, total_files=0)

        # Process batches
        matches: list[GrepMatch] = []
        files_searched = 0
        bytes_read = 0
        batches_completed = 0
        start_time = time.monotonic()
        stop_reason: str | None = None

        for batch_num in range(_GREP_MAX_BATCHES):
            batch_start_index = start_index + batch_num * _GREP_BATCH_SIZE
            batch_end_index = min(batch_start_index + _GREP_BATCH_SIZE, total_files)

            if batch_start_index >= total_files:
                # All files processed
                break

            batch_files = all_files[batch_start_index:batch_end_index]
            batch_start_time = time.monotonic()
            batch_files_searched = 0

            for file_path in batch_files:
                # Check batch timeout
                elapsed_batch = time.monotonic() - batch_start_time
                if elapsed_batch > _GREP_BATCH_TIMEOUT_S:
                    stop_reason = "batch_timeout"
                    logger.warning(
                        "Grep batch %d timed out after %.1fs (files searched: %d/%d)",
                        batch_num + 1,
                        elapsed_batch,
                        batch_files_searched,
                        len(batch_files),
                    )
                    break

                # Check total timeout
                elapsed_total = time.monotonic() - start_time
                if elapsed_total > _GREP_TOTAL_TIMEOUT_S:
                    stop_reason = "total_timeout"
                    logger.warning(
                        "Grep total timeout %.1fs reached after %d files",
                        elapsed_total,
                        files_searched,
                    )
                    break

                # Check total bytes limit
                if bytes_read >= _GREP_MAX_TOTAL_BYTES:
                    stop_reason = "bytes_limit"
                    logger.warning(
                        "Grep bytes limit %d reached after %d files",
                        _GREP_MAX_TOTAL_BYTES,
                        files_searched,
                    )
                    break

                try:
                    stat = file_path.stat()
                    file_size = stat.st_size

                    # Skip large files
                    if file_size > _GREP_MAX_FILE_SIZE_BYTES:
                        continue

                    # Check if adding this file exceeds bytes limit
                    if bytes_read + file_size > _GREP_MAX_TOTAL_BYTES:
                        stop_reason = "bytes_limit"
                        logger.warning(
                            "Grep bytes limit approaching, stopping before file %s (%d bytes)",
                            file_path.name,
                            file_size,
                        )
                        break

                    rel_path = self._result_path(file_path)

                    with open(file_path, encoding="utf-8", errors="ignore") as f:
                        content = f.read()

                    bytes_read += file_size
                    files_searched += 1
                    batch_files_searched += 1

                    # Search for pattern in content
                    for line_num, line in enumerate(content.split("\n"), 1):
                        for match in regex.finditer(line):
                            matches.append(
                                GrepMatch(
                                    path=rel_path,
                                    line_number=line_num,
                                    line_content=line,
                                    match_start=match.start(),
                                    match_end=match.end(),
                                )
                            )

                except OSError:
                    # Skip files we can't read
                    continue

            batches_completed += 1

            # Check if we stopped mid-batch
            if stop_reason:
                break

        # Determine if search is complete
        next_file_index = start_index + batches_completed * _GREP_BATCH_SIZE
        # Partial if: not all files processed AND (stopped early OR hit batch limit)
        is_partial = next_file_index < total_files

        # Build continuation token if partial
        continuation: dict[str, Any] | None = None
        if is_partial:
            continuation = {
                "next_file_index": next_file_index,
                "cached_files": [str(f) for f in all_files],  # Cache for resume
                "stop_reason": stop_reason or "batch_limit",  # Track why we stopped
            }

        result = GrepResult(
            matches=matches,
            files_searched=files_searched,
            total_matches=len(matches),
            is_partial=is_partial,
            continuation_token=continuation,
            total_files=total_files,
            error=None if not stop_reason or is_partial else f"Search stopped: {stop_reason}",
        )

        if output_mode == "files_with_matches":
            return list({m.path for m in matches})
        if output_mode == "count":
            return str(len(matches))
        return result

    def _collect_grep_files(self, resolved: Path, glob: str | None) -> list[Path]:
        """Collect all files for grep with .gitignore and ignore filter applied.

        Pre-collects files to support incremental batching and continuation.
        Uses pathspec to honor .gitignore patterns; falls back to _GREP_IGNORE_DIRS
        floor when no .gitignore exists or pathspec is unavailable.
        """
        all_files: list[Path] = []

        # Load gitignore spec for this search root
        gitignore_spec = self._load_gitignore(resolved)

        for root, dirs, files in os.walk(resolved):
            root_path = Path(root)
            rel_root = root_path.relative_to(resolved) if root_path != resolved else Path(".")

            # Filter directories using gitignore + floor filter
            filtered_dirs: list[str] = []
            for d in dirs:
                rel_dir = rel_root / d
                # Gitignore check (primary)
                if gitignore_spec and gitignore_spec.match_file(str(rel_dir)):
                    continue
                # Floor filter (defense-in-depth)
                if self._should_ignore_dir_for_grep(d):
                    continue
                filtered_dirs.append(d)
            dirs[:] = filtered_dirs

            for name in files:
                file_path = root_path / name
                rel_file = rel_root / name

                # Gitignore check (primary)
                if gitignore_spec and gitignore_spec.match_file(str(rel_file)):
                    continue

                # Apply glob filter if specified
                if glob and not fnmatch.fnmatch(name, glob):
                    continue
                all_files.append(file_path)

        return all_files

    def _load_gitignore(self, search_root: Path) -> pathspec.PathSpec | None:
        """Load and compile .gitignore patterns for the search tree.

        Scans the entire tree for .gitignore files (gated by file count already).
        For each .gitignore at path P, prepends patterns with the relative path
        from search_root to P, matching git's nested .gitignore semantics.

        Caches the compiled spec keyed by workspace root + search root to avoid
        re-parsing on repeated grep calls within the same session.

        Returns None if no .gitignore files found.
        """
        cache_key = (self.workspace.resolve(), search_root.resolve())
        if cache_key in self._gitignore_cache:
            return self._gitignore_cache[cache_key]

        patterns: list[str] = []

        # Walk tree to find all .gitignore files (including nested)
        for root, dirs, files in os.walk(search_root):
            root_path = Path(root)
            rel_root = root_path.relative_to(search_root) if root_path != search_root else Path(".")

            # Check for .gitignore at this level
            if ".gitignore" in files:
                gitignore_path = root_path / ".gitignore"
                try:
                    content = gitignore_path.read_text(encoding="utf-8", errors="ignore")
                    for line in content.splitlines():
                        stripped = line.strip()
                        if stripped and not stripped.startswith("#"):
                            # Prepend relative path for nested gitignore semantics
                            if rel_root == Path("."):
                                patterns.append(stripped)
                            else:
                                # Pattern applies relative to this directory
                                patterns.append(str(rel_root / stripped))
                except OSError:
                    pass  # Ignore unreadable gitignore files

            # Skip ignored dirs to speed up scan
            dirs[:] = [d for d in dirs if not self._should_ignore_dir_for_grep(d)]

        if not patterns:
            self._gitignore_cache[cache_key] = None
            return None

        spec = pathspec.PathSpec.from_lines("gitignore", patterns)
        self._gitignore_cache[cache_key] = spec
        return spec

    def _should_ignore_dir_for_grep(self, name: str) -> bool:
        """Check if directory should be skipped during grep walk."""
        # Exact match against known ignore dirs
        if name in _GREP_IGNORE_DIRS:
            return True
        # Pattern match for dynamic dirs (e.g., *.egg-info)
        for pattern in _GREP_IGNORE_DIRS:
            if "*" in pattern and fnmatch.fnmatch(name, pattern):
                return True
        return False

    def _estimate_file_count(self, resolved: Path, gitignore_spec: pathspec.PathSpec | None) -> int:
        """Estimate file count for gating decision without full tree walk.

        Uses shallow sampling: counts files in top-level dirs and extrapolates.
        Fast enough (<100ms) for gate check, accurate enough for limit decisions.
        """
        total_estimate = 0
        # Sample top-level entries only
        try:
            for entry in resolved.iterdir():
                if entry.is_file():
                    # Count file directly
                    if gitignore_spec and gitignore_spec.match_file(entry.name):
                        continue
                    total_estimate += 1
                elif entry.is_dir():
                    # Skip ignored dirs
                    if gitignore_spec and gitignore_spec.match_file(entry.name):
                        continue
                    if self._should_ignore_dir_for_grep(entry.name):
                        continue
                    # Sample: count files in this dir, use as multiplier estimate
                    # Assume average depth of 3-4 levels for typical project
                    try:
                        dir_file_count = sum(
                            1
                            for f in entry.iterdir()
                            if f.is_file()
                            and not (
                                gitignore_spec
                                and gitignore_spec.match_file(entry.name + "/" + f.name)
                            )
                        )
                        # Extrapolate: dir_file_count * estimated_depth (3-4)
                        # Clamp to avoid overcounting sparse dirs
                        total_estimate += dir_file_count * 4
                    except OSError:
                        # Permission denied or other error: use conservative estimate
                        total_estimate += 100
        except OSError:
            # Can't read directory: assume large
            return _GREP_FALLBACK_FILE_LIMIT + 1

        return total_estimate

    async def agrep(
        self,
        pattern: str,
        *,
        path: str = ".",
        glob: str | None = None,
        output_mode: str = "files_with_matches",
        continuation_token: dict[str, Any] | None = None,
    ) -> GrepResult | list[str] | str:
        """Async search for pattern in files with incremental batching."""
        return await asyncio.to_thread(
            self.grep,
            pattern,
            path=path,
            glob=glob,
            output_mode=output_mode,
            continuation_token=continuation_token,
        )
