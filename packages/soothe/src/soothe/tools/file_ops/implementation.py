"""File operation tools (RFC-0016 consolidation).

Consolidates single-purpose file tools into one module:
- read_file: Read file contents
- write_file: Write content to files
- delete_file: Delete files
- search_files: Search for patterns in files
- list_files: List files matching pattern
- file_info: Get file metadata

Follows the pattern from image.py and audio.py.
"""

from __future__ import annotations

import logging
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import Field

from soothe.tools._internal.file_edit import (
    _display_path,
    _normalize_workspace_relative_input,
)
from soothe.utils import expand_path

logger = logging.getLogger(__name__)


def _get_effective_work_dir(fallback_work_dir: str) -> str:
    """Get effective work directory, checking LangGraph config first (RFC-103).

    Priority:
    1. workspace from LangGraph configurable (passed through execution)
    2. ContextVar (for same-async-context operations)
    3. fallback_work_dir (daemon default)

    Args:
        fallback_work_dir: Fallback directory if no dynamic workspace set.

    Returns:
        Effective workspace directory path as string.
    """
    # Priority 1: Try to get workspace from LangGraph configurable
    # This works even when tool execution is in a different async context
    try:
        from langgraph.config import get_config

        config = get_config()
        configurable = config.get("configurable", {})
        workspace = configurable.get("workspace")
        if workspace:
            return str(workspace)
    except Exception:  # noqa: S110
        # Not in LangGraph context - this is expected for non-LangGraph tool calls
        pass

    # Priority 2: Try ContextVar (same async context)
    from soothe.core import FrameworkFilesystem

    dynamic_workspace = FrameworkFilesystem.get_current_workspace()
    if dynamic_workspace:
        logger.debug("Using dynamic workspace from ContextVar: %s", dynamic_workspace)
        return str(dynamic_workspace)

    # Priority 3: Use fallback
    logger.debug("No dynamic workspace, using fallback: %s", fallback_work_dir)
    return fallback_work_dir


class ReadFileTool(BaseTool):
    """Read file contents.

    Use this tool to view file contents, check configuration files,
    or inspect specific line ranges.
    """

    name: str = "read_file"
    description: str = (
        "Read contents of a file. "
        "Parameters: path (required) - absolute file path. "
        "Optional: start_line, end_line to read specific range. "
        "Returns: file contents with line numbers."
    )

    work_dir: str = Field(default="", description="Working directory")
    max_file_size: int = Field(default=10 * 1024 * 1024)  # 10MB
    allow_outside_workdir: bool = Field(default=False)

    def _resolve_path(self, file_path: str) -> Path:
        """Resolve file path relative to work directory.

        Resolution order (for absolute paths that don't exist):
        1. Try as relative path from workspace
        2. Try as relative path from workspace root (for /file paths)

        This handles LLM convention where /file.txt means "relative to workspace root".
        """
        # Use dynamic workspace from ContextVar if available (RFC-103)
        effective_work_dir = _get_effective_work_dir(self.work_dir)

        normalized_input = _normalize_workspace_relative_input(file_path, effective_work_dir)

        # Log if normalization changed the path
        if normalized_input != file_path:
            logger.info("Path normalization: '%s' → '%s'", file_path, normalized_input)

        path = Path(normalized_input)

        if path.is_absolute():
            # If absolute path exists, use it
            if path.exists():
                if effective_work_dir and not self.allow_outside_workdir:
                    work = expand_path(effective_work_dir)
                    try:
                        path.resolve().relative_to(work)
                    except ValueError as err:
                        msg = f"Path {normalized_input} is outside work directory"
                        raise ValueError(msg) from err
                return path

            # If absolute path doesn't exist, try as workspace-relative
            # This handles LLM convention where /file means "relative to workspace root"
            if effective_work_dir:
                base = expand_path(effective_work_dir)
                # Strip leading slash to make it relative
                relative_path = path.relative_to("/") if path.is_absolute() else path
                resolved = (base / relative_path).resolve()

                # If resolved path exists, use it
                if resolved.exists():
                    logger.debug(
                        "Absolute path %s doesn't exist, found at workspace-relative: %s",
                        file_path,
                        resolved,
                    )
                    return resolved

                # Path doesn't exist anywhere - return the workspace-relative version
                # (will fail later with a clearer error message)
                logger.debug(
                    "Absolute path %s doesn't exist, treating as workspace-relative: %s",
                    file_path,
                    resolved,
                )
                return resolved

            # No workspace, return the absolute path (will fail later)
            return path

        # Relative path - resolve relative to workspace
        base = expand_path(effective_work_dir) if effective_work_dir else Path.cwd()
        return (base / path).resolve()

    def _run(
        self, path: str, start_line: int | None = None, end_line: int | None = None, **kwargs: Any
    ) -> str:
        """Read file contents.

        Args:
            path: Absolute file path
            start_line: First line to read (1-indexed, inclusive)
            end_line: Last line to read (1-indexed, inclusive)
            **kwargs: Additional ignored parameters (for flexibility)

        Returns:
            File contents with line numbers
        """
        # Ignore unexpected kwargs like 'limit' that LLM might pass
        _ = kwargs

        try:
            resolved = self._resolve_path(path)

            if not resolved.exists():
                return f"Error: File not found: {resolved}"

            if not resolved.is_file():
                return f"Error: Not a file: {resolved}"

            file_size = resolved.stat().st_size
            if file_size > self.max_file_size:
                return f"Error: File size ({file_size} bytes) exceeds limit ({self.max_file_size} bytes)"

            lines = resolved.read_text(encoding="utf-8").splitlines(keepends=True)

            if start_line is not None or end_line is not None:
                # Convert to int if needed (LLM might pass strings)
                start = (int(start_line) if start_line is not None else 1) - 1
                end = int(end_line) if end_line is not None else len(lines)
                lines = lines[start:end]

            result = "".join(lines)
        except ValueError as e:
            return f"Error: {e}"
        except Exception as e:
            logger.exception("Failed to read file")
            return f"Error reading file: {e}"
        else:
            return result

    async def _arun(
        self, path: str, start_line: int | None = None, end_line: int | None = None, **kwargs: Any
    ) -> str:
        """Async execution (delegates to sync)."""
        return self._run(path, start_line, end_line, **kwargs)


class WriteFileTool(BaseTool):
    """Write content to a file.

    Use this tool to create new files or overwrite/append to existing files.
    Creates backups automatically when overwriting.
    """

    name: str = "write_file"
    description: str = (
        "Write content to a file. "
        "Parameters: path (required), content (required). "
        "Optional: mode - 'overwrite' (default) or 'append'. "
        "Returns: confirmation message."
    )

    work_dir: str = Field(default="", description="Working directory")
    backup_enabled: bool = Field(default=True)
    backup_dir: str = Field(default="")
    max_file_size: int = Field(default=10 * 1024 * 1024)  # 10MB
    allow_outside_workdir: bool = Field(default=False)

    def _resolve_path(self, file_path: str) -> Path:
        """Resolve file path relative to work directory.

        Args:
            file_path: File path (relative or absolute).

        Returns:
            Resolved absolute path.

        Raises:
            ValueError: If path is outside work directory and not allowed.
        """
        # Use dynamic workspace from ContextVar if available (RFC-103)
        effective_work_dir = _get_effective_work_dir(self.work_dir)

        normalized_input = _normalize_workspace_relative_input(file_path, effective_work_dir)

        # Log if normalization changed the path
        if normalized_input != file_path:
            logger.info("Path normalization: '%s' → '%s'", file_path, normalized_input)

        path = Path(normalized_input)

        if path.is_absolute():
            # If absolute path exists or parent exists, use it
            if path.exists() or path.parent.exists():
                if effective_work_dir and not self.allow_outside_workdir:
                    work = expand_path(effective_work_dir)
                    try:
                        path.resolve().relative_to(work)
                    except ValueError as err:
                        msg = f"Path {normalized_input} is outside work directory"
                        raise ValueError(msg) from err
                return path

            # If absolute path doesn't exist, treat as workspace-relative
            # This handles LLM convention where /file means "relative to workspace root"
            if effective_work_dir:
                base = expand_path(effective_work_dir)
                relative_path = path.relative_to("/") if path.is_absolute() else path
                resolved = (base / relative_path).resolve()
                logger.debug(
                    "Absolute path %s doesn't exist, treating as workspace-relative: %s",
                    file_path,
                    resolved,
                )
                return resolved

            # No workspace, return the absolute path
            return path

        base = expand_path(effective_work_dir) if effective_work_dir else Path.cwd()

        return (base / path).resolve()

    def _sanitize_filename(self, filename: str) -> str:
        """Replace unsafe characters in filename.

        Args:
            filename: Original filename.

        Returns:
            Sanitized filename.
        """
        safe = re.sub(r"[^\w\-_.]", "_", filename)
        return safe.strip("_.")

    def _create_backup(self, file_path: Path) -> Path | None:
        """Create timestamped backup of existing file.

        Args:
            file_path: Path to file to backup.

        Returns:
            Path to backup file or None if backup disabled/file doesn't exist.
        """
        if not self.backup_enabled or not file_path.exists():
            return None

        backup_base = Path(self.backup_dir) if self.backup_dir else file_path.parent / ".backups"

        backup_base.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        backup_name = f"{file_path.stem}_{timestamp}{file_path.suffix}"
        backup_path = backup_base / backup_name

        shutil.copy2(file_path, backup_path)
        logger.info("Created backup: %s", backup_path)

        return backup_path

    def _run(self, path: str, content: str, mode: str = "overwrite") -> str:
        """Write content to file.

        Args:
            path: Absolute file path
            content: Content to write
            mode: 'overwrite' or 'append'

        Returns:
            Success message
        """
        try:
            resolved = self._resolve_path(path)

            if mode == "append" and resolved.exists():
                # Read existing content and append
                existing = resolved.read_text(encoding="utf-8")
                content = existing + "\n" + content

            if resolved.exists() and mode == "overwrite" and not self.backup_enabled:
                return (
                    f"Error: File already exists: {resolved}. Use mode='append' or enable backups."
                )

            content_size = len(content.encode("utf-8"))
            if content_size > self.max_file_size:
                return f"Error: Content size ({content_size} bytes) exceeds limit ({self.max_file_size} bytes)"

            backup_path = (
                self._create_backup(resolved) if resolved.exists() and mode == "overwrite" else None
            )

            resolved.parent.mkdir(parents=True, exist_ok=True)

            resolved.write_text(content, encoding="utf-8")

            result = f"Created: {_display_path(resolved, self.work_dir)}"
            if backup_path:
                result += f" (backup: {backup_path.name})"

        except ValueError as e:
            return f"Error: {e}"
        except Exception as e:
            logger.exception("Failed to create file")
            return f"Error creating file: {e}"
        else:
            return result

    async def _arun(self, path: str, content: str, mode: str = "overwrite") -> str:
        """Async execution (delegates to sync)."""
        return self._run(path, content, mode)


class DeleteFileTool(BaseTool):
    """Delete a file.

    Use this tool to remove files from the filesystem.
    Creates backups automatically before deletion.
    """

    name: str = "delete_file"
    description: str = "Delete a file. Parameters: path (required). Returns: confirmation message."

    work_dir: str = Field(default="", description="Working directory")
    backup_enabled: bool = Field(default=True)
    backup_dir: str = Field(default="")
    allow_outside_workdir: bool = Field(default=False)

    def _resolve_path(self, file_path: str) -> Path:
        """Resolve file path relative to work directory.

        Resolution order (for absolute paths that don't exist):
        1. Try as relative path from workspace
        2. Try as relative path from workspace root (for /file paths)

        This handles LLM convention where /file.txt means "relative to workspace root".
        """
        # Use dynamic workspace from ContextVar if available (RFC-103)
        effective_work_dir = _get_effective_work_dir(self.work_dir)

        normalized_input = _normalize_workspace_relative_input(file_path, effective_work_dir)

        # Log if normalization changed the path
        if normalized_input != file_path:
            logger.info("Path normalization: '%s' → '%s'", file_path, normalized_input)

        path = Path(normalized_input)

        if path.is_absolute():
            # If absolute path exists, use it
            if path.exists():
                if effective_work_dir and not self.allow_outside_workdir:
                    work = expand_path(effective_work_dir)
                    try:
                        path.resolve().relative_to(work)
                    except ValueError as err:
                        msg = f"Path {normalized_input} is outside work directory"
                        raise ValueError(msg) from err
                return path

            # If absolute path doesn't exist, try as workspace-relative
            # This handles LLM convention where /file means "relative to workspace root"
            if effective_work_dir:
                base = expand_path(effective_work_dir)
                # Strip leading slash to make it relative
                relative_path = path.relative_to("/") if path.is_absolute() else path
                resolved = (base / relative_path).resolve()

                # If resolved path exists, use it
                if resolved.exists():
                    logger.debug(
                        "Absolute path %s doesn't exist, found at workspace-relative: %s",
                        file_path,
                        resolved,
                    )
                    return resolved

                # Path doesn't exist anywhere - return the workspace-relative version
                # (will fail later with a clearer error message)
                logger.debug(
                    "Absolute path %s doesn't exist, treating as workspace-relative: %s",
                    file_path,
                    resolved,
                )
                return resolved

            # No workspace, return the absolute path (will fail later)
            return path

        # Relative path - resolve relative to workspace
        base = expand_path(effective_work_dir) if effective_work_dir else Path.cwd()
        return (base / path).resolve()

    def _create_backup(self, file_path: Path) -> Path | None:
        """Create backup before deletion."""
        if not self.backup_enabled or not file_path.exists():
            return None

        backup_base = Path(self.backup_dir) if self.backup_dir else file_path.parent / ".backups"

        backup_base.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        backup_name = f"{file_path.stem}_{timestamp}{file_path.suffix}"
        backup_path = backup_base / backup_name

        shutil.copy2(file_path, backup_path)
        return backup_path

    def _run(self, path: str) -> str:
        """Delete file at path.

        Args:
            path: Absolute file path

        Returns:
            Success message
        """
        try:
            resolved = self._resolve_path(path)

            if not resolved.exists():
                return f"Error: File not found: {resolved}"

            if not resolved.is_file():
                return f"Error: Not a file: {resolved}"

            backup_path = self._create_backup(resolved)

            resolved.unlink()

            result = f"Deleted: {_display_path(resolved, self.work_dir)}"
            if backup_path:
                result += f" (backup: {backup_path.name})"

        except ValueError as e:
            return f"Error: {e}"
        except Exception as e:
            logger.exception("Failed to delete file")
            return f"Error deleting file: {e}"
        else:
            return result

    async def _arun(self, path: str) -> str:
        """Async execution (delegates to sync)."""
        return self._run(path)


class SearchFilesTool(BaseTool):
    """Search for pattern in files.

    Use this tool to search for text patterns across multiple files,
    similar to the grep command.
    """

    name: str = "search_files"
    description: str = (
        "Search for pattern in files. "
        "Parameters: pattern (required), path (default: '.'). "
        "Returns: matching files and lines."
    )

    work_dir: str = Field(default="", description="Working directory")

    def _resolve_directory(self, path: str) -> Path:
        """Resolve directory path, ensuring it's within workspace.

        Args:
            path: Directory path (relative or absolute).

        Returns:
            Resolved path within workspace.
        """
        # Use dynamic workspace from LangGraph configurable (RFC-103)
        effective_work_dir = _get_effective_work_dir(self.work_dir)
        base = expand_path(effective_work_dir) if effective_work_dir else Path.cwd()

        if path == "." or not path:
            return base

        path_obj = Path(path)

        # If absolute path, check if it's within workspace
        if path_obj.is_absolute():
            resolved = path_obj.resolve()
            try:
                # Check if this absolute path is within the workspace
                resolved.relative_to(base)
            except ValueError:
                # Path is outside workspace - treat as relative to workspace
                logger.info(
                    "Absolute path '%s' is outside workspace '%s', treating as relative",
                    path,
                    base,
                )
                # Remove leading slash and join with workspace
                relative_part = path.lstrip("/")
                return (base / relative_part).resolve()
            else:
                # Path is within workspace, use it
                return resolved

        # Relative path - resolve relative to workspace
        return (base / path_obj).resolve()

    def _run(self, pattern: str, path: str = ".", file_pattern: str = "*") -> str:
        """Search for regex pattern in files.

        Args:
            pattern: Regex pattern to search
            path: Directory path to search
            file_pattern: File glob pattern (e.g., '*.py')

        Returns:
            Matching files and lines
        """
        try:
            target = self._resolve_directory(path)

            if not target.exists():
                return f"Error: Directory not found: {target}"

            regex = re.compile(pattern, re.IGNORECASE)

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
                except Exception:
                    logger.debug("Failed to read file %s", f, exc_info=True)
                    continue

            if not results:
                return f"No matches found for pattern '{pattern}'"

            return "\n".join(results[:100])

        except re.error as e:
            return f"Error: Invalid regex pattern: {e}"
        except Exception as e:
            logger.exception("Failed to search files")
            return f"Error searching files: {e}"

    async def _arun(self, pattern: str, path: str = ".", file_pattern: str = "*") -> str:
        """Async execution (delegates to sync)."""
        return self._run(pattern, path, file_pattern)


class ListFilesTool(BaseTool):
    """List files matching pattern.

    Use this tool to list files in a directory, optionally filtered
    by a glob pattern.
    """

    name: str = "list_files"
    description: str = (
        "List files matching pattern. "
        "Parameters: pattern (default: '*'), path (default: '.'). "
        "Returns: list of file paths."
    )

    work_dir: str = Field(default="", description="Working directory")

    def _resolve_directory(self, path: str) -> Path:
        """Resolve directory path, ensuring it's within workspace.

        Args:
            path: Directory path (relative or absolute).

        Returns:
            Resolved path within workspace.
        """
        # Use dynamic workspace from LangGraph configurable (RFC-103)
        effective_work_dir = _get_effective_work_dir(self.work_dir)
        base = expand_path(effective_work_dir) if effective_work_dir else Path.cwd()

        if path == "." or not path:
            return base

        path_obj = Path(path)

        # If absolute path, check if it's within workspace
        if path_obj.is_absolute():
            resolved = path_obj.resolve()
            try:
                # Check if this absolute path is within the workspace
                resolved.relative_to(base)
            except ValueError:
                # Path is outside workspace - treat as relative to workspace
                # Strip leading slash and resolve relative to base
                logger.info(
                    "Absolute path '%s' is outside workspace '%s', treating as relative",
                    path,
                    base,
                )
                # Remove leading slash and join with workspace
                relative_part = path.lstrip("/")
                return (base / relative_part).resolve()
            else:
                # Path is within workspace, use it
                return resolved

        # Relative path - resolve relative to workspace
        return (base / path_obj).resolve()

    def _run(self, pattern: str = "*", path: str = ".", recursive: bool = False) -> str:  # noqa: FBT001, FBT002
        """List files matching glob pattern.

        Args:
            pattern: Glob pattern (e.g., '*.py')
            path: Directory path
            recursive: Search recursively

        Returns:
            List of matching file paths
        """
        try:
            target = self._resolve_directory(path)

            if not target.exists():
                return f"Error: Directory not found: {target}"

            if not target.is_dir():
                return f"Error: Not a directory: {target}"

            files = list(target.rglob(pattern)) if recursive else list(target.glob(pattern))

            lines = []
            for f in sorted(files):
                if f.is_file():
                    rel_path = f.relative_to(target)
                    size = f.stat().st_size
                    lines.append(f"{rel_path} ({size} bytes)")

            if not lines:
                return f"No files found matching pattern '{pattern}'"

            return "\n".join(lines)

        except Exception as e:
            logger.exception("Failed to list files")
            return f"Error listing files: {e}"

    async def _arun(self, pattern: str = "*", path: str = ".", recursive: bool = False) -> str:  # noqa: FBT001, FBT002
        """Async execution (delegates to sync)."""
        return self._run(pattern, path, recursive)


class FileInfoTool(BaseTool):
    """Get file metadata.

    Use this tool to retrieve information about a file such as
    size, modification time, and permissions.
    """

    name: str = "file_info"
    description: str = "Get file metadata. Parameters: path (required). Returns: size, modification time, permissions."

    work_dir: str = Field(default="", description="Working directory")
    allow_outside_workdir: bool = Field(default=False)

    def _resolve_path(self, file_path: str) -> Path:
        """Resolve file path relative to work directory."""
        # Use dynamic workspace from ContextVar if available (RFC-103)
        effective_work_dir = _get_effective_work_dir(self.work_dir)

        normalized_input = _normalize_workspace_relative_input(file_path, effective_work_dir)

        # Log if normalization changed the path
        if normalized_input != file_path:
            logger.info("Path normalization: '%s' → '%s'", file_path, normalized_input)

        path = Path(normalized_input)

        if path.is_absolute():
            if self.work_dir and not self.allow_outside_workdir:
                work = expand_path(self.work_dir)
                try:
                    path.resolve().relative_to(work)
                except ValueError as err:
                    msg = f"Path {normalized_input} is outside work directory"
                    raise ValueError(msg) from err
            return path

        base = expand_path(self.work_dir) if self.work_dir else Path.cwd()

        return (base / path).resolve()

    def _run(self, path: str) -> str:
        """Get file information.

        Args:
            path: Absolute file path

        Returns:
            File metadata
        """
        try:
            resolved = self._resolve_path(path)

            if not resolved.exists():
                return f"Error: File not found: {resolved}"

            stat = resolved.stat()

            mtime = datetime.fromtimestamp(stat.st_mtime, tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
            atime = datetime.fromtimestamp(stat.st_atime, tz=UTC).strftime("%Y-%m-%d %H:%M:%S")

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
        except Exception as e:
            logger.exception("Failed to get file info")
            return f"Error getting file info: {e}"

    async def _arun(self, path: str) -> str:
        """Async execution (delegates to sync)."""
        return self._run(path)


def create_file_ops_tools(
    *,
    work_dir: str = "",
    allow_outside_workdir: bool = False,
) -> list[BaseTool]:
    """Create all file operation tools.

    Args:
        work_dir: Working directory for relative paths.
        allow_outside_workdir: Allow access outside workspace.

    Returns:
        List of file operation BaseTool instances.
    """
    return [
        ReadFileTool(work_dir=work_dir, allow_outside_workdir=allow_outside_workdir),
        WriteFileTool(work_dir=work_dir, allow_outside_workdir=allow_outside_workdir),
        DeleteFileTool(work_dir=work_dir, allow_outside_workdir=allow_outside_workdir),
        SearchFilesTool(work_dir=work_dir),
        ListFilesTool(work_dir=work_dir),
        FileInfoTool(work_dir=work_dir, allow_outside_workdir=allow_outside_workdir),
    ]
