"""Local filesystem implementation of UnifiedFilesystem."""

from __future__ import annotations

import fnmatch
import hashlib
import shutil
import subprocess
from pathlib import Path

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
from .protocol import (
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
                # Non-virtual mode: use absolute path but check bounds
                resolved = expanded.resolve()
                if not self._is_within_workspace(resolved):
                    raise PathTraversalError(
                        path=path,
                        attempted_path=str(resolved),
                        workspace=str(self.workspace),
                    )
        else:
            # Relative path: resolve against workspace
            resolved = (self.workspace / path).resolve()

        # Final check: must be within workspace
        if not self._is_within_workspace(resolved):
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
        """Async read file contents."""
        # For local filesystem, async is same as sync
        return self.read(path, offset=offset, limit=limit, encoding=encoding)

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
        resolved.parent.mkdir(parents=True, exist_ok=True)

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

        return WriteResult(
            path=str(resolved.relative_to(self.workspace)),
            bytes_written=bytes_written,
            created=created,
            backup_path=str(backup_path.relative_to(self.workspace)) if backup_path else None,
        )

    async def awrite(
        self,
        path: str,
        content: str | bytes,
        *,
        encoding: str = "utf-8",
        backup: bool = False,
    ) -> WriteResult:
        """Async write content to file."""
        return self.write(path, content, encoding=encoding, backup=backup)

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
            path=str(resolved.relative_to(self.workspace)),
            old_hash=old_hash,
            new_hash=new_hash,
            lines_changed=lines_changed,
            backup_path=str(backup_path.relative_to(self.workspace)) if backup_path else None,
        )

    async def aedit(
        self,
        path: str,
        old_string: str,
        new_string: str,
        *,
        backup: bool = True,
    ) -> EditResult:
        """Async replace old_string with new_string in file."""
        return self.edit(path, old_string, new_string, backup=backup)

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

        if start_line < 1 or end_line > len(lines) or start_line > end_line:
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

        # Replace lines
        new_lines = new_content.split("\n")
        if new_lines[-1] == "":
            new_lines = new_lines[:-1]

        result_lines = (
            lines[: start_line - 1] + [line + "\n" for line in new_lines] + lines[end_line:]
        )

        new_full_content = "".join(result_lines)
        new_hash = self._compute_hash(new_full_content)

        lines_changed = end_line - start_line + 1

        with open(resolved, "w", encoding="utf-8") as f:
            f.writelines(result_lines)

        return EditResult(
            path=str(resolved.relative_to(self.workspace)),
            old_hash=old_hash,
            new_hash=new_hash,
            lines_changed=lines_changed,
            backup_path=str(backup_path.relative_to(self.workspace)) if backup_path else None,
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
        """Async replace specific line range in file."""
        return self.edit_lines(path, start_line, end_line, new_content, backup=backup)

    def insert_lines(
        self,
        path: str,
        line: int,
        content: str,
        *,
        backup: bool = True,
    ) -> EditResult:
        """Insert content at specific line number."""
        # Insert is equivalent to replacing empty range
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
            path=str(resolved.relative_to(self.workspace)),
            backup_path=str(backup_path.relative_to(self.workspace)) if backup_path else None,
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
            path=str(path.relative_to(self.workspace)),
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
            path=str(resolved.relative_to(self.workspace)),
            was_directory=True,
            backup_path=str(backup_path.relative_to(self.workspace)) if backup_path else None,
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
            path=str(resolved.relative_to(self.workspace)),
            was_directory=False,
            backup_path=str(backup_path.relative_to(self.workspace)) if backup_path else None,
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
    ) -> GrepResult | list[str] | str:
        """Search for pattern in files."""
        import re

        resolved = self._resolve_path(path)

        if not resolved.is_dir():
            return GrepResult(matches=[])

        matches: list[GrepMatch] = []
        files_searched = 0

        for root, dirs, files in __import__("os").walk(resolved):
            for name in files:
                if glob and not fnmatch.fnmatch(name, glob):
                    continue

                file_path = Path(root) / name
                rel_path = str(file_path.relative_to(self.workspace))

                try:
                    with open(file_path, encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                except (OSError, UnicodeDecodeError):
                    continue

                files_searched += 1

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

        result = GrepResult(
            matches=matches,
            files_searched=files_searched,
            total_matches=len(matches),
        )

        if output_mode == "files_with_matches":
            return list({m.path for m in matches})
        elif output_mode == "count":
            return str(len(matches))
        else:
            return result

    async def agrep(
        self,
        pattern: str,
        *,
        path: str = ".",
        glob: str | None = None,
        output_mode: str = "files_with_matches",
    ) -> GrepResult | list[str] | str:
        """Async search for pattern in files."""
        return self.grep(pattern, path=path, glob=glob, output_mode=output_mode)
