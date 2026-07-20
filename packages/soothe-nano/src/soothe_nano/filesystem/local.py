"""Local filesystem implementation of UnifiedFilesystem."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import aiofiles

from ._lock_registry import FileEditLockRegistry
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
from .grep_search import GREP_UNAVAILABLE_ERROR, is_grep_available, run_grep
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

logger = logging.getLogger(__name__)


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
        # Per-resolved-path edit locks for serialising concurrent read-modify-write
        # operations on the same file. Async methods use asyncio.Lock; sync methods
        # use threading.RLock (reentrant for nested acquisition).
        self._edit_locks = FileEditLockRegistry()

    def _resolve_path(self, path: str, *, allow_host_absolute: bool = False) -> Path:
        """Resolve path within workspace.

        Args:
            path: Input path.
            allow_host_absolute: When ``True``, host-root absolutes outside the
                workspace (for example ``/Users/...``) resolve to the real path
                instead of being remapped into the sandbox. Used by read-only
                operations (``grep``, ``read``).

        Returns:
            Resolved Path object.

        Raises:
            PathTraversalError: If path escapes workspace.
        """
        from soothe_nano.workspace.workspace_paths import (
            should_use_virtual_path_resolution,
        )

        self._validate_path(path)

        # Handle empty or root paths
        if not path or path.strip() in {"", ".", "/"}:
            return self.workspace

        # Expand user and resolve
        expanded = Path(path).expanduser()

        if expanded.is_absolute():
            resolved = expanded.resolve()
            if self._is_within_workspace(resolved):
                return resolved
            if self.virtual_mode:
                if should_use_virtual_path_resolution(path.strip(), self.workspace):
                    rel_path = path.lstrip("/")
                    virtual = (self.workspace / rel_path).resolve()
                    if not self._is_within_workspace(virtual):
                        raise PathTraversalError(
                            path=path,
                            attempted_path=str(virtual),
                            workspace=str(self.workspace),
                        )
                    return virtual
                if allow_host_absolute:
                    return resolved
                raise PathTraversalError(
                    path=path,
                    attempted_path=str(resolved),
                    workspace=str(self.workspace),
                )
            return resolved

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

    def _compute_version_stamp(self, resolved: Path) -> str | None:
        """Compute a version stamp for optimistic concurrency control.

        Combines file mtime (nanosecond precision) and size into a compact
        string.  Two stamps are equal only if the file was not modified
        between the two stat calls.  Returns ``None`` when the file does
        not exist (new-file creation), allowing callers to skip the
        stamp-verification step for brand-new files.

        Args:
            resolved: Absolute path to the file on disk.

        Returns:
            A ``"mtime_ns:size"`` string, or ``None`` if the file is absent.
        """
        try:
            stat = resolved.stat()
            return f"{stat.st_mtime_ns}:{stat.st_size}"
        except FileNotFoundError:
            return None

    def _write_atomic(
        self,
        resolved: Path,
        content: str | bytes,
        *,
        encoding: str = "utf-8",
    ) -> None:
        """Write content atomically via temp-file + ``os.replace``.

        The content is first written to a uniquely-named temporary file in
        the **same directory** as the target (guaranteeing the same
        filesystem so that ``os.replace`` is atomic).  Only after the temp
        file is fully written and flushed is it renamed into place.

        Crash safety: the target file is either the old version or the new
        version—never a partially-written file.

        Stale temp files are cleaned up on any exception to avoid
        accumulating orphaned ``.tmp`` files.

        Args:
            resolved: Absolute target path.
            content: Content to write (``str`` or ``bytes``).
            encoding: Text encoding (ignored for ``bytes`` content).

        Raises:
            OSError: If the temp file cannot be created or renamed.
        """
        tmp_name = f".{resolved.name}.{uuid.uuid4().hex}.tmp"
        tmp_path = resolved.parent / tmp_name

        try:
            if isinstance(content, str):
                tmp_path.write_text(content, encoding=encoding)
            else:
                tmp_path.write_bytes(content)
            os.replace(tmp_path, resolved)
        except Exception:
            # Best-effort cleanup of stale temp file on any error
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def _check_file_size(self, resolved: Path, path: str) -> None:
        """Guard against reading or writing oversized files.

        Raises ``FilesystemError`` if the file exists and exceeds
        ``max_file_size_bytes``.

        Args:
            resolved: Absolute path to check.
            path: Original user-facing path string (for error messages).

        Raises:
            FilesystemError: If the file exceeds the size limit.
        """
        if resolved.exists() and resolved.is_file():
            file_size = resolved.stat().st_size
            if file_size > self.max_file_size_bytes:
                raise FilesystemError(
                    f"File too large: {file_size} bytes (max: {self.max_file_size_bytes})",
                    path=path,
                )

    # =======================================================================
    # Path Operations
    # =======================================================================

    def resolve_path(self, path: str, *, allow_host_absolute: bool = False) -> Path:
        """Resolve path relative to workspace."""
        return self._resolve_path(path, allow_host_absolute=allow_host_absolute)

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
        resolved = self._resolve_path(path, allow_host_absolute=True)

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
        resolved = self._resolve_path(path, allow_host_absolute=True)

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
        """Async write content to file using atomic temp-file + rename.

        Writes content to a temporary file in the same directory as the
        target, then atomically renames it into place via
        ``os.replace()``. A version stamp (mtime+size) is captured before
        the write and verified just before the rename to detect concurrent
        external writers. If the stamp changed, the write is retried once.

        Args:
            path: Path to write to.
            content: Content to write (str or bytes).
            encoding: Text encoding for str content.
            backup: If True, create a backup before writing.

        Returns:
            WriteResult with write details.
        """
        resolved = self._resolve_path(path)

        # Ensure parent directory exists
        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
        except PermissionError as e:
            raise PermissionDeniedError(f"Permission denied: {path}", path=path) from e
        except OSError as e:
            raise FilesystemError(f"Cannot create directory for {path}: {e}", path=path) from e

        # Guard against oversized files
        self._check_file_size(resolved, path)

        async with self._edit_locks.acquire(resolved):
            for attempt in range(2):
                # Snapshot version stamp before backup / write
                stamp_before = self._compute_version_stamp(resolved)
                created = stamp_before is None  # file did not exist

                # Create backup if needed (sync — rare operation)
                backup_path = None
                if backup and resolved.exists():
                    backup_path = self._create_backup(resolved)

                # Verify no external writer modified the file
                stamp_after = self._compute_version_stamp(resolved)
                if stamp_before != stamp_after:
                    if attempt == 0:
                        logger.debug(
                            "Concurrent modification detected for %s, retrying write",
                            path,
                        )
                        continue
                    # On second attempt, proceed anyway (best-effort)

                # Atomic write via temp file + os.replace
                try:
                    self._write_atomic(resolved, content, encoding=encoding)
                    if isinstance(content, str):
                        bytes_written = len(content.encode(encoding))
                    else:
                        bytes_written = len(content)
                except PermissionError as e:
                    raise PermissionDeniedError(f"Permission denied: {path}", path=path) from e
                except OSError as e:
                    raise FilesystemError(f"Write error: {e}", path=path) from e

                result_path = self._result_path(resolved)
                result_backup = self._result_path(backup_path) if backup_path else None

                return WriteResult(
                    path=result_path,
                    bytes_written=bytes_written,
                    created=created,
                    backup_path=result_backup,
                )

            # Unreachable — loop always returns or raises
            raise FilesystemError(f"Write failed after retry: {path}", path=path)

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
        """Replace old_string with new_string in file.

        Uses optimistic concurrency: a version stamp is captured before
        reading the file and verified before the atomic write. If an
        external writer modified the file in between, the operation is
        retried once.
        """
        resolved = self._resolve_path(path)

        if not resolved.exists():
            raise PathNotFoundError(f"File not found: {path}", path=path)

        # Guard against oversized files
        self._check_file_size(resolved, path)

        with self._edit_locks.acquire_sync(resolved):
            for attempt in range(2):
                # Snapshot version stamp before reading
                stamp_before = self._compute_version_stamp(resolved)

                # Read current content
                with open(resolved, encoding="utf-8") as f:
                    content = f.read()

                old_hash = self._compute_hash(content)

                # Check for matches
                if old_string not in content:
                    raise FilesystemError(
                        f"String not found in file: {old_string!r}. Re-read the file with "
                        "read_file and retry with exact surrounding context including whitespace.",
                        path=path,
                    )

                count = content.count(old_string)
                if count > 1:
                    raise FilesystemError(
                        f"Multiple matches ({count}) found for string: {old_string!r}. "
                        "Add more surrounding context to old_string or set replace_all=true.",
                        path=path,
                    )

                # Create backup
                backup_path = None
                if backup:
                    backup_path = self._create_backup(resolved)

                # Verify stamp unchanged before write
                stamp_after = self._compute_version_stamp(resolved)
                if stamp_before != stamp_after:
                    if attempt == 0:
                        logger.debug(
                            "Concurrent modification detected for %s, retrying edit",
                            path,
                        )
                        continue
                    # On second attempt, proceed anyway (best-effort)

                # Apply edit
                new_content = content.replace(old_string, new_string, 1)
                new_hash = self._compute_hash(new_content)

                # Count changed lines (approximate)
                old_lines = old_string.count("\n")
                new_lines = new_string.count("\n")
                lines_changed = abs(new_lines - old_lines) + 1

                # Atomic write back
                self._write_atomic(resolved, new_content)

                return EditResult(
                    path=self._result_path(resolved),
                    old_hash=old_hash,
                    new_hash=new_hash,
                    lines_changed=lines_changed,
                    backup_path=self._result_path(backup_path) if backup_path else None,
                )

            # Unreachable — loop always returns or raises
            raise FilesystemError(f"Edit failed after retry: {path}", path=path)

    async def aedit(
        self,
        path: str,
        old_string: str,
        new_string: str,
        *,
        backup: bool = True,
    ) -> EditResult:
        """Async replace old_string with new_string in file.

        Uses optimistic concurrency: a version stamp is captured before
        reading the file and verified before the atomic write. If an
        external writer modified the file in between, the operation is
        retried once. The final write is atomic (temp file + os.replace).
        """
        resolved = self._resolve_path(path)

        if not resolved.exists():
            raise PathNotFoundError(f"File not found: {path}", path=path)

        # Guard against oversized files
        self._check_file_size(resolved, path)

        async with self._edit_locks.acquire(resolved):
            for attempt in range(2):
                # Snapshot version stamp before reading
                stamp_before = self._compute_version_stamp(resolved)

                # Async read current content
                async with aiofiles.open(resolved, encoding="utf-8") as f:
                    content = await f.read()

                old_hash = self._compute_hash(content)

                # Check for matches
                if old_string not in content:
                    raise FilesystemError(
                        f"String not found in file: {old_string!r}. Re-read the file with "
                        "read_file and retry with exact surrounding context including whitespace.",
                        path=path,
                    )

                count = content.count(old_string)
                if count > 1:
                    raise FilesystemError(
                        f"Multiple matches ({count}) found for string: {old_string!r}. "
                        "Add more surrounding context to old_string or set replace_all=true.",
                        path=path,
                    )

                # Create backup (sync — rare operation)
                backup_path = None
                if backup:
                    backup_path = self._create_backup(resolved)

                # Verify stamp unchanged before write
                stamp_after = self._compute_version_stamp(resolved)
                if stamp_before != stamp_after:
                    if attempt == 0:
                        logger.debug(
                            "Concurrent modification detected for %s, retrying edit",
                            path,
                        )
                        continue
                    # On second attempt, proceed anyway (best-effort)

                # Apply edit
                new_content = content.replace(old_string, new_string, 1)
                new_hash = self._compute_hash(new_content)

                # Count changed lines (approximate)
                old_lines = old_string.count("\n")
                new_lines = new_string.count("\n")
                lines_changed = abs(new_lines - old_lines) + 1

                # Atomic write back (temp file + os.replace)
                self._write_atomic(resolved, new_content)

                return EditResult(
                    path=self._result_path(resolved),
                    old_hash=old_hash,
                    new_hash=new_hash,
                    lines_changed=lines_changed,
                    backup_path=self._result_path(backup_path) if backup_path else None,
                )

            # Unreachable — loop always returns or raises
            raise FilesystemError(f"Edit failed after retry: {path}", path=path)

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

        with self._edit_locks.acquire_sync(resolved):
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
                result_lines = (
                    lines[: start_line - 1] + formatted_new_lines + lines[start_line - 1 :]
                )
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
        """Async replace specific line range in file.

        Uses optimistic concurrency: a version stamp is captured before
        reading the file and verified before the atomic write. If an
        external writer modified the file in between, the operation is
        retried once. The final write is atomic (temp file + os.replace).
        """
        resolved = self._resolve_path(path)

        if not resolved.exists():
            raise PathNotFoundError(f"File not found: {path}", path=path)

        # Guard against oversized files
        self._check_file_size(resolved, path)

        async with self._edit_locks.acquire(resolved):
            for attempt in range(2):
                # Snapshot version stamp before reading
                stamp_before = self._compute_version_stamp(resolved)

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

                # Create backup (sync — rare operation)
                backup_path = None
                if backup:
                    backup_path = self._create_backup(resolved)

                # Verify stamp unchanged before write
                stamp_after = self._compute_version_stamp(resolved)
                if stamp_before != stamp_after:
                    if attempt == 0:
                        logger.debug(
                            "Concurrent modification detected for %s, retrying edit_lines",
                            path,
                        )
                        continue
                    # On second attempt, proceed anyway (best-effort)

                new_lines = new_content.split("\n")
                if new_lines and new_lines[-1] == "":
                    new_lines = new_lines[:-1]

                formatted_new_lines = [line + "\n" for line in new_lines]
                if insert_mode:
                    result_lines = (
                        lines[: start_line - 1] + formatted_new_lines + lines[start_line - 1 :]
                    )
                    lines_changed = len(formatted_new_lines)
                else:
                    result_lines = lines[: start_line - 1] + formatted_new_lines + lines[end_line:]
                    lines_changed = end_line - start_line + 1

                new_full_content = "".join(result_lines)
                new_hash = self._compute_hash(new_full_content)

                # Atomic write back (temp file + os.replace)
                self._write_atomic(resolved, new_full_content)

                return EditResult(
                    path=self._result_path(resolved),
                    old_hash=old_hash,
                    new_hash=new_hash,
                    lines_changed=lines_changed,
                    backup_path=self._result_path(backup_path) if backup_path else None,
                )

            # Unreachable — loop always returns or raises
            raise FilesystemError(f"Edit failed after retry: {path}", path=path)

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
        """Apply multiple edit operations to a file in one atomic read/modify/write.

        All operations are applied to in-memory content in a single pass,
        then the result is written atomically via temp file + ``os.replace``.
        Optimistic concurrency (version stamp) is used to detect external
        writers and retry once if the file changed between read and write.

        Operations are applied in order: deletions → insertions →
        replacements. Replacements are sorted by line number descending
        (bottom-to-top) to preserve line indices during modification.

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

        # Guard against oversized files
        self._check_file_size(resolved, path)

        # Separate operations by type (validated once, outside retry loop)
        deletions = [op for op in operations if op.operation_type == "delete"]
        insertions = [op for op in operations if op.operation_type == "insert"]
        replacements = [op for op in operations if op.operation_type == "replace"]

        # Check for overlaps in replacements (fail fast before any I/O)
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

        async with self._edit_locks.acquire(resolved):
            for attempt in range(2):
                # Snapshot version stamp before reading
                stamp_before = self._compute_version_stamp(resolved)

                # Async read file
                async with aiofiles.open(resolved, encoding="utf-8") as f:
                    content = await f.read()
                lines = content.splitlines(keepends=True)
                old_hash = self._compute_hash(content)

                # Create backup (sync — rare operation)
                backup_path = None
                if backup:
                    backup_path = self._create_backup(resolved)

                # Verify stamp unchanged before write
                stamp_after = self._compute_version_stamp(resolved)
                if stamp_before != stamp_after:
                    if attempt == 0:
                        logger.debug(
                            "Concurrent modification detected for %s, retrying batched edit",
                            path,
                        )
                        continue
                    # On second attempt, proceed anyway (best-effort)

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
                    lines = (
                        lines[: op.start_line - 1]
                        + formatted_new_lines
                        + lines[op.start_line - 1 :]
                    )
                    total_lines_changed += len(formatted_new_lines)
                    operations_applied += 1

                # Apply replacements (sorted descending to preserve indices)
                replacements_sorted = sorted(
                    replacements, key=lambda op: op.start_line, reverse=True
                )
                for op in replacements_sorted:
                    if op.start_line < 1 or op.end_line > len(lines) or op.start_line > op.end_line:
                        failed_ops.append(op.original_call_id or "")
                        continue
                    new_lines = op.content.split("\n")
                    if new_lines and new_lines[-1] == "":
                        new_lines = new_lines[:-1]
                    formatted_new_lines = [line + "\n" for line in new_lines]
                    lines = lines[: op.start_line - 1] + formatted_new_lines + lines[op.end_line :]
                    total_lines_changed += max(
                        op.end_line - op.start_line + 1, len(formatted_new_lines)
                    )
                    operations_applied += 1

                # Compute new hash
                new_content = "".join(lines)
                new_hash = self._compute_hash(new_content)

                # Atomic write back (temp file + os.replace)
                self._write_atomic(resolved, new_content)

                return BatchedEditResult(
                    path=self._result_path(resolved),
                    old_hash=old_hash,
                    new_hash=new_hash,
                    total_lines_changed=total_lines_changed,
                    operations_applied=operations_applied,
                    failed_operations=failed_ops if failed_ops else None,
                    backup_path=self._result_path(backup_path) if backup_path else None,
                )

            # Unreachable — loop always returns or raises
            raise FilesystemError(f"Batched edit failed after retry: {path}", path=path)

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
        """Apply unified diff patch to file with atomic write.

        Reads the current content, applies the patch in-memory, and writes
        the result atomically via temp file + ``os.replace``. A version
        stamp is captured before reading and verified before writing; if
        an external writer modified the file, the operation retries once.

        Falls back to the ``patch`` command-line tool for diffs that
        cannot be applied via the in-memory approach.
        """
        resolved = self._resolve_path(path)

        if not resolved.exists():
            raise PathNotFoundError(f"File not found: {path}", path=path)

        # Guard against oversized files
        self._check_file_size(resolved, path)

        with self._edit_locks.acquire_sync(resolved):
            for attempt in range(2):
                # Snapshot version stamp before reading
                stamp_before = self._compute_version_stamp(resolved)

                # Read current content
                with open(resolved, encoding="utf-8") as f:
                    content = f.read()

                # Create backup
                backup_path = None
                if backup:
                    backup_path = self._create_backup(resolved)

                # Verify stamp unchanged before applying patch
                stamp_after = self._compute_version_stamp(resolved)
                if stamp_before != stamp_after:
                    if attempt == 0:
                        logger.debug(
                            "Concurrent modification detected for %s, retrying diff apply",
                            path,
                        )
                        continue
                    # On second attempt, proceed anyway (best-effort)

                # Apply patch in-memory using the patch command on temp content
                import tempfile

                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".diff", delete=False, encoding="utf-8"
                ) as diff_file:
                    diff_file.write(diff)
                    diff_file_path = diff_file.name

                import tempfile as _tmpf

                # Create a temp copy of the original content to patch
                with _tmpf.NamedTemporaryFile(
                    mode="w", suffix=".txt", delete=False, encoding="utf-8"
                ) as content_file:
                    content_file.write(content)
                    content_file_path = content_file.name

                try:
                    subprocess.run(
                        ["patch", "-u", content_file_path, diff_file_path],
                        capture_output=True,
                        text=True,
                        check=True,
                    )
                    with open(content_file_path, encoding="utf-8") as f:
                        new_content = f.read()
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
                finally:
                    # Clean up temp files
                    for tmp in (diff_file_path, content_file_path):
                        try:
                            os.unlink(tmp)
                        except OSError:
                            pass

                # Atomic write back
                self._write_atomic(resolved, new_content)

                old_hash = self._compute_hash(content)
                new_hash = self._compute_hash(new_content)

                return EditResult(
                    path=self._result_path(resolved),
                    old_hash=old_hash,
                    new_hash=new_hash,
                    backup_path=self._result_path(backup_path) if backup_path else None,
                )

            # Unreachable — loop always returns or raises
            raise FilesystemError(f"Diff apply failed after retry: {path}", path=path)

    async def aapply_diff(
        self,
        path: str,
        diff: str,
        *,
        backup: bool = True,
    ) -> EditResult:
        """Async apply unified diff patch to file with atomic write.

        Delegates to the sync ``apply_diff`` which performs in-memory
        patching followed by an atomic temp-file + ``os.replace`` write.
        Optimistic concurrency (version stamp) is used to detect external
        writers and retry once.
        """
        resolved = self._resolve_path(path)
        async with self._edit_locks.acquire(resolved):
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
        """Search for pattern in files via ``ag`` or ``rg``.

        Args:
            pattern: Regex pattern to search for.
            path: Directory or file to search.
            glob: Optional glob pattern for file filtering.
            output_mode: ``files_with_matches``, ``count``, or ``content``.

        Returns:
            GrepResult, or simplified list[str] / str for files_with_matches / count modes.
        """
        resolved = self._resolve_path(path, allow_host_absolute=True)

        if not resolved.is_dir() and not resolved.is_file():
            return GrepResult(matches=[])

        if not is_grep_available():
            return GrepResult(matches=[], error=GREP_UNAVAILABLE_ERROR)

        result = run_grep(
            workspace=self.workspace,
            search_path=resolved,
            pattern=pattern,
            glob=glob,
            output_mode=output_mode,
        )
        if result is None:
            return GrepResult(matches=[], error="grep search failed")
        return result

    async def agrep(
        self,
        pattern: str,
        *,
        path: str = ".",
        glob: str | None = None,
        output_mode: str = "files_with_matches",
    ) -> GrepResult | list[str] | str:
        """Async search for pattern in files via ``ag`` or ``rg``."""
        return await asyncio.to_thread(
            self.grep,
            pattern,
            path=path,
            glob=glob,
            output_mode=output_mode,
        )
