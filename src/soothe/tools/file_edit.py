"""File operations with backup and safety features.

Ported from noesium's file_edit_toolkit.py for coding agent support.
"""

from __future__ import annotations

import logging
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from langchain_core.tools import BaseTool
from pydantic import Field

logger = logging.getLogger(__name__)


class CreateFileTool(BaseTool):
    """Create or update files with backup support."""

    name: str = "create_file"
    description: str = (
        "Create a new file or update existing file. "
        "Provide `file_path` (relative or absolute path) and `content` (file content). "
        "Optional `overwrite` (default False) to overwrite existing files. "
        "Automatic backups are created for existing files. "
        "Returns success message or error."
    )

    work_dir: str = Field(default="")
    backup_enabled: bool = Field(default=True)
    backup_dir: str = Field(default="")
    max_file_size: int = Field(default=10 * 1024 * 1024)  # 10MB

    def _resolve_path(self, file_path: str) -> Path:
        """Resolve file path relative to work directory.

        Args:
            file_path: File path (relative or absolute).

        Returns:
            Resolved absolute path.

        Raises:
            ValueError: If path is outside work directory.
        """
        path = Path(file_path)

        # If absolute path, validate it's within work_dir
        if path.is_absolute():
            if self.work_dir:
                work = Path(self.work_dir).resolve()
                try:
                    path.resolve().relative_to(work)
                except ValueError as err:
                    raise ValueError(f"Path {file_path} is outside work directory") from err
            return path

        # Relative path - resolve against work_dir or cwd
        if self.work_dir:
            base = Path(self.work_dir).resolve()
        else:
            base = Path.cwd()

        return (base / path).resolve()

    def _sanitize_filename(self, filename: str) -> str:
        """Replace unsafe characters in filename.

        Args:
            filename: Original filename.

        Returns:
            Sanitized filename.
        """
        # Keep only alphanumeric, dash, underscore, dot
        safe = re.sub(r"[^\w\-_.]", "_", filename)
        # Remove leading/trailing underscores and dots
        return safe.strip("_.")

    def _create_backup(self, file_path: Path) -> Optional[Path]:
        """Create timestamped backup of existing file.

        Args:
            file_path: Path to file to backup.

        Returns:
            Path to backup file or None if backup disabled/file doesn't exist.
        """
        if not self.backup_enabled or not file_path.exists():
            return None

        # Determine backup directory
        if self.backup_dir:
            backup_base = Path(self.backup_dir)
        else:
            backup_base = file_path.parent / ".backups"

        backup_base.mkdir(parents=True, exist_ok=True)

        # Create timestamped backup
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{file_path.stem}_{timestamp}{file_path.suffix}"
        backup_path = backup_base / backup_name

        shutil.copy2(file_path, backup_path)
        logger.info("Created backup: %s", backup_path)

        return backup_path

    def _run(self, file_path: str, content: str, overwrite: bool = False) -> str:
        """Create or update file.

        Args:
            file_path: File path to create.
            content: File content.
            overwrite: Whether to overwrite existing file.

        Returns:
            Success message or error.
        """
        try:
            # Resolve path
            resolved = self._resolve_path(file_path)

            # Check if file exists
            if resolved.exists() and not overwrite:
                return f"Error: File already exists: {resolved}. Use overwrite=True to replace."

            # Check content size
            content_size = len(content.encode("utf-8"))
            if content_size > self.max_file_size:
                return f"Error: Content size ({content_size} bytes) exceeds limit ({self.max_file_size} bytes)"

            # Create backup if file exists
            backup_path = self._create_backup(resolved) if resolved.exists() else None

            # Ensure parent directory exists
            resolved.parent.mkdir(parents=True, exist_ok=True)

            # Write file
            resolved.write_text(content, encoding="utf-8")

            result = f"Created: {resolved}"
            if backup_path:
                result += f" (backup: {backup_path.name})"

            return result

        except ValueError as e:
            return f"Error: {e}"
        except Exception as e:  # noqa: BLE001
            logger.error("Failed to create file: %s", e, exc_info=True)
            return f"Error creating file: {e}"

    async def _arun(self, file_path: str, content: str, overwrite: bool = False) -> str:
        return self._run(file_path, content, overwrite)


class ReadFileTool(BaseTool):
    """Read file contents."""

    name: str = "read_file"
    description: str = (
        "Read contents of a file. "
        "Provide `file_path` (relative or absolute path). "
        "Optional `start_line` and `end_line` to read specific line range. "
        "Returns file content or error message."
    )

    work_dir: str = Field(default="")
    max_file_size: int = Field(default=10 * 1024 * 1024)  # 10MB

    def _resolve_path(self, file_path: str) -> Path:
        """Resolve file path relative to work directory."""
        path = Path(file_path)

        if path.is_absolute():
            if self.work_dir:
                work = Path(self.work_dir).resolve()
                try:
                    path.resolve().relative_to(work)
                except ValueError as err:
                    raise ValueError(f"Path {file_path} is outside work directory") from err
            return path

        if self.work_dir:
            base = Path(self.work_dir).resolve()
        else:
            base = Path.cwd()

        return (base / path).resolve()

    def _run(
        self,
        file_path: str,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> str:
        """Read file contents.

        Args:
            file_path: File path to read.
            start_line: Optional start line (1-indexed).
            end_line: Optional end line (inclusive).

        Returns:
            File content or error message.
        """
        try:
            resolved = self._resolve_path(file_path)

            if not resolved.exists():
                return f"Error: File not found: {resolved}"

            if not resolved.is_file():
                return f"Error: Not a file: {resolved}"

            # Check file size
            file_size = resolved.stat().st_size
            if file_size > self.max_file_size:
                return f"Error: File size ({file_size} bytes) exceeds limit ({self.max_file_size} bytes)"

            # Read file
            lines = resolved.read_text(encoding="utf-8").splitlines(keepends=True)

            # Apply line range
            if start_line is not None or end_line is not None:
                start = (start_line or 1) - 1  # Convert to 0-indexed
                end = end_line or len(lines)
                lines = lines[start:end]

            return "".join(lines)

        except ValueError as e:
            return f"Error: {e}"
        except Exception as e:  # noqa: BLE001
            logger.error("Failed to read file: %s", e, exc_info=True)
            return f"Error reading file: {e}"

    async def _arun(
        self,
        file_path: str,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> str:
        return self._run(file_path, start_line, end_line)


class DeleteFileTool(BaseTool):
    """Delete files with backup."""

    name: str = "delete_file"
    description: str = (
        "Delete a file. "
        "Provide `file_path` (relative or absolute path). "
        "Optional `backup` (default True) to create backup before deletion. "
        "Returns success message or error."
    )

    work_dir: str = Field(default="")
    backup_enabled: bool = Field(default=True)
    backup_dir: str = Field(default="")

    def _resolve_path(self, file_path: str) -> Path:
        """Resolve file path relative to work directory."""
        path = Path(file_path)

        if path.is_absolute():
            if self.work_dir:
                work = Path(self.work_dir).resolve()
                try:
                    path.resolve().relative_to(work)
                except ValueError as err:
                    raise ValueError(f"Path {file_path} is outside work directory") from err
            return path

        if self.work_dir:
            base = Path(self.work_dir).resolve()
        else:
            base = Path.cwd()

        return (base / path).resolve()

    def _create_backup(self, file_path: Path) -> Optional[Path]:
        """Create backup before deletion."""
        if not self.backup_enabled or not file_path.exists():
            return None

        if self.backup_dir:
            backup_base = Path(self.backup_dir)
        else:
            backup_base = file_path.parent / ".backups"

        backup_base.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{file_path.stem}_{timestamp}{file_path.suffix}"
        backup_path = backup_base / backup_name

        shutil.copy2(file_path, backup_path)
        return backup_path

    def _run(self, file_path: str, backup: bool = True) -> str:
        """Delete file.

        Args:
            file_path: File path to delete.
            backup: Whether to create backup.

        Returns:
            Success message or error.
        """
        try:
            resolved = self._resolve_path(file_path)

            if not resolved.exists():
                return f"Error: File not found: {resolved}"

            if not resolved.is_file():
                return f"Error: Not a file: {resolved}"

            # Create backup if requested
            backup_path = self._create_backup(resolved) if backup else None

            # Delete file
            resolved.unlink()

            result = f"Deleted: {resolved}"
            if backup_path:
                result += f" (backup: {backup_path.name})"

            return result

        except ValueError as e:
            return f"Error: {e}"
        except Exception as e:  # noqa: BLE001
            logger.error("Failed to delete file: %s", e, exc_info=True)
            return f"Error deleting file: {e}"

    async def _arun(self, file_path: str, backup: bool = True) -> str:
        return self._run(file_path, backup)


class ListFilesTool(BaseTool):
    """List files in directory."""

    name: str = "list_files"
    description: str = (
        "List files in a directory. "
        "Provide `path` (optional, defaults to current directory). "
        "Optional `pattern` to filter files (e.g., '*.py'). "
        "Optional `recursive` (default False) to list recursively. "
        "Returns file listing or error message."
    )

    work_dir: str = Field(default="")

    def _run(
        self,
        path: str = ".",
        pattern: str = "*",
        recursive: bool = False,
    ) -> str:
        """List files in directory.

        Args:
            path: Directory path.
            pattern: File pattern to match.
            recursive: Whether to list recursively.

        Returns:
            File listing or error.
        """
        try:
            if self.work_dir:
                base = Path(self.work_dir).resolve()
            else:
                base = Path.cwd()

            target = (base / path).resolve() if path != "." else base

            if not target.exists():
                return f"Error: Directory not found: {target}"

            if not target.is_dir():
                return f"Error: Not a directory: {target}"

            # Collect files
            if recursive:
                files = list(target.rglob(pattern))
            else:
                files = list(target.glob(pattern))

            # Format output
            lines = []
            for f in sorted(files):
                if f.is_file():
                    rel_path = f.relative_to(target)
                    size = f.stat().st_size
                    lines.append(f"{rel_path} ({size} bytes)")

            if not lines:
                return f"No files found matching pattern '{pattern}'"

            return "\n".join(lines)

        except Exception as e:  # noqa: BLE001
            logger.error("Failed to list files: %s", e, exc_info=True)
            return f"Error listing files: {e}"

    async def _arun(
        self,
        path: str = ".",
        pattern: str = "*",
        recursive: bool = False,
    ) -> str:
        return self._run(path, pattern, recursive)


class SearchInFilesTool(BaseTool):
    """Search for pattern in files."""

    name: str = "search_in_files"
    description: str = (
        "Search for a pattern in files. "
        "Provide `pattern` (regex pattern to search). "
        "Optional `path` (directory to search, default current). "
        "Optional `file_pattern` to filter files (e.g., '*.py'). "
        "Returns search results with file paths and line numbers."
    )

    work_dir: str = Field(default="")

    def _run(
        self,
        pattern: str,
        path: str = ".",
        file_pattern: str = "*",
    ) -> str:
        """Search for pattern in files.

        Args:
            pattern: Regex pattern to search.
            path: Directory to search.
            file_pattern: File pattern to match.

        Returns:
            Search results or error.
        """
        try:
            if self.work_dir:
                base = Path(self.work_dir).resolve()
            else:
                base = Path.cwd()

            target = (base / path).resolve() if path != "." else base

            if not target.exists():
                return f"Error: Directory not found: {target}"

            # Compile pattern
            regex = re.compile(pattern, re.IGNORECASE)

            # Search files
            results = []
            for f in target.rglob(file_pattern):
                if not f.is_file():
                    continue

                try:
                    lines = f.read_text(encoding="utf-8", errors="ignore").splitlines()
                    for i, line in enumerate(lines, 1):
                        if regex.search(line):
                            rel_path = f.relative_to(target)
                            results.append(f"{rel_path}:{i}: {line.strip()}")
                except Exception:  # noqa: BLE001
                    continue

            if not results:
                return f"No matches found for pattern '{pattern}'"

            return "\n".join(results[:100])  # Limit to 100 results

        except re.error as e:
            return f"Error: Invalid regex pattern: {e}"
        except Exception as e:  # noqa: BLE001
            logger.error("Failed to search files: %s", e, exc_info=True)
            return f"Error searching files: {e}"

    async def _arun(
        self,
        pattern: str,
        path: str = ".",
        file_pattern: str = "*",
    ) -> str:
        return self._run(pattern, path, file_pattern)


class GetFileInfoTool(BaseTool):
    """Get file metadata."""

    name: str = "get_file_info"
    description: str = (
        "Get metadata about a file. "
        "Provide `file_path` (relative or absolute path). "
        "Returns file size, modification time, and other metadata."
    )

    work_dir: str = Field(default="")

    def _resolve_path(self, file_path: str) -> Path:
        """Resolve file path relative to work directory."""
        path = Path(file_path)

        if path.is_absolute():
            if self.work_dir:
                work = Path(self.work_dir).resolve()
                try:
                    path.resolve().relative_to(work)
                except ValueError as err:
                    raise ValueError(f"Path {file_path} is outside work directory") from err
            return path

        if self.work_dir:
            base = Path(self.work_dir).resolve()
        else:
            base = Path.cwd()

        return (base / path).resolve()

    def _run(self, file_path: str) -> str:
        """Get file info.

        Args:
            file_path: File path.

        Returns:
            File metadata or error.
        """
        try:
            resolved = self._resolve_path(file_path)

            if not resolved.exists():
                return f"Error: File not found: {resolved}"

            stat = resolved.stat()

            import time

            mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            atime = datetime.fromtimestamp(stat.st_atime).strftime("%Y-%m-%d %H:%M:%S")

            info = [
                f"Path: {resolved}",
                f"Size: {stat.st_size} bytes ({stat.st_size / 1024:.2f} KB)",
                f"Modified: {mtime}",
                f"Accessed: {atime}",
                f"Is File: {resolved.is_file()}",
                f"Is Directory: {resolved.is_dir()}",
            ]

            return "\n".join(info)

        except ValueError as e:
            return f"Error: {e}"
        except Exception as e:  # noqa: BLE001
            logger.error("Failed to get file info: %s", e, exc_info=True)
            return f"Error getting file info: {e}"

    async def _arun(self, file_path: str) -> str:
        return self._run(file_path)


def create_file_edit_tools() -> list[BaseTool]:
    """Create file operation tools.

    Returns:
        List of file tools: create_file, read_file, delete_file, list_files,
        search_in_files, get_file_info.
    """
    return [
        CreateFileTool(),
        ReadFileTool(),
        DeleteFileTool(),
        ListFilesTool(),
        SearchInFilesTool(),
        GetFileInfoTool(),
    ]
