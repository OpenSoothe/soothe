"""File operations toolkit -- surgical file manipulation not provided by deepagents.

After deduplication with deepagents FilesystemMiddleware, this toolkit provides:
- delete_file: Delete files (with optional backup)
- file_info: Get file metadata (size, modification time, permissions)
- edit_file_lines: Replace specific line ranges (surgical, not full-file)
- insert_lines: Insert content at a specific line number
- delete_lines: Delete specific line ranges from a file
- apply_diff: Apply unified diff patches

Tools that DUPLICATE deepagents are NOT included:
- read_file, write_file (use deepagents' versions)
- search_files/grep, list_files/glob/ls (use deepagents' versions)
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from langchain_core.tools import BaseTool
from pydantic import Field
from soothe_sdk.plugin import plugin

from soothe.toolkits._internal.file_edit import (
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
    try:
        from langgraph.config import get_config

        config = get_config()
        configurable = config.get("configurable", {})
        workspace = configurable.get("workspace")
        if workspace:
            return str(workspace)
    except Exception:  # noqa: S110
        pass

    # Priority 2: Try ContextVar
    from soothe.core import FrameworkFilesystem

    dynamic_workspace = FrameworkFilesystem.get_current_workspace()
    if dynamic_workspace:
        return str(dynamic_workspace)

    # Priority 3: Use fallback
    return fallback_work_dir


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
        """Resolve file path relative to work directory."""
        effective_work_dir = _get_effective_work_dir(self.work_dir)
        normalized_input = _normalize_workspace_relative_input(file_path, effective_work_dir)

        if normalized_input != file_path:
            logger.info("Path normalization: '%s' → '%s'", file_path, normalized_input)

        path = Path(normalized_input)

        if path.is_absolute():
            if path.exists():
                if effective_work_dir and not self.allow_outside_workdir:
                    work = expand_path(effective_work_dir)
                    try:
                        path.resolve().relative_to(work)
                    except ValueError as err:
                        msg = f"Path {normalized_input} is outside work directory"
                        raise ValueError(msg) from err
                return path

            if effective_work_dir:
                base = expand_path(effective_work_dir)
                relative_path = path.relative_to("/") if path.is_absolute() else path
                resolved = (base / relative_path).resolve()
                if resolved.exists():
                    return resolved
                return resolved
            return path

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
        effective_work_dir = _get_effective_work_dir(self.work_dir)
        normalized_input = _normalize_workspace_relative_input(file_path, effective_work_dir)

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


class EditFileLinesTool(BaseTool):
    """Replace specific line range in a file.

    Use this tool for surgical code modifications - changing a specific function,
    updating configuration values, or fixing a bug in a specific code section.
    Safer than reading the entire file, modifying in memory, and rewriting completely.
    """

    name: str = "edit_file_lines"
    description: str = (
        "Replace specific line range in a file. "
        "Use for: surgical code modifications without full rewrite. "
        "Parameters: path, start_line, end_line, new_content (all required). "
        "Returns: confirmation with diff summary. "
        "Safer than read → modify → write_full_file."
    )

    work_dir: str = Field(default="", description="Working directory")
    allow_outside_workdir: bool = Field(default=False)

    def _resolve_path(self, path: str) -> Path:
        """Resolve and validate file path."""
        effective_work_dir = _get_effective_work_dir(self.work_dir)
        file_path = Path(path)

        if not file_path.is_absolute():
            base = expand_path(effective_work_dir) if effective_work_dir else Path.cwd()
            file_path = (base / file_path).resolve()

        if not self.allow_outside_workdir and effective_work_dir:
            try:
                file_path.relative_to(expand_path(effective_work_dir))
            except ValueError as err:
                msg = f"Path {path} is outside work directory"
                raise ValueError(msg) from err

        return file_path

    def _run(self, path: str, start_line: int, end_line: int, new_content: str) -> str:
        """Replace lines start_line to end_line (inclusive) with new_content.

        Args:
            path: Absolute file path
            start_line: First line to replace (1-indexed, inclusive)
            end_line: Last line to replace (1-indexed, inclusive)
            new_content: New content to insert

        Returns:
            Success message with diff summary

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If line range is invalid
        """
        try:
            file_path = self._resolve_path(path)
            if not file_path.exists():
                msg = f"File not found: {path}"
                raise FileNotFoundError(msg)

            if not file_path.is_file():
                msg = f"Path is not a file: {path}"
                raise ValueError(msg)

            with file_path.open(encoding="utf-8") as f:
                lines = f.readlines()

            total_lines = len(lines)
            if start_line < 1 or start_line > total_lines:
                msg = f"Invalid start_line: {start_line}. File has {total_lines} lines. Line numbers are 1-indexed."
                raise ValueError(msg)
            if end_line < start_line or end_line > total_lines:
                msg = (
                    f"Invalid end_line: {end_line}. "
                    f"Must be >= start_line ({start_line}) and <= total lines ({total_lines})."
                )
                raise ValueError(msg)

            new_lines = new_content.splitlines(keepends=True)
            if new_lines and not new_lines[-1].endswith("\n"):
                new_lines[-1] += "\n"

            lines_removed = end_line - start_line + 1
            lines_added = len(new_lines)

            lines[start_line - 1 : end_line] = new_lines

            with file_path.open("w", encoding="utf-8") as f:
                f.writelines(lines)

            return (
                f"Updated {_display_path(file_path, self.work_dir)}\n"
                f"Lines {start_line}-{end_line} replaced "
                f"({lines_removed} removed, {lines_added} added)"
            )

        except (FileNotFoundError, ValueError) as e:
            return f"Error: {e}"
        except Exception as e:
            logger.exception("Failed to edit file lines")
            return f"Error editing file: {e}"

    async def _arun(self, path: str, start_line: int, end_line: int, new_content: str) -> str:
        """Async execution (delegates to sync)."""
        return self._run(path, start_line, end_line, new_content)


class InsertLinesTool(BaseTool):
    """Insert content at a specific line.

    Use this tool to add new imports at the top of a file, insert a new function
    between existing functions, or add configuration entries at specific positions.
    """

    name: str = "insert_lines"
    description: str = (
        "Insert content at a specific line. "
        "Parameters: path, line, content (all required). "
        "Returns: confirmation message."
    )

    work_dir: str = Field(default="", description="Working directory")
    allow_outside_workdir: bool = Field(default=False)

    def _resolve_path(self, path: str) -> Path:
        """Resolve and validate file path."""
        effective_work_dir = _get_effective_work_dir(self.work_dir)
        file_path = Path(path)

        if not file_path.is_absolute():
            base = expand_path(effective_work_dir) if effective_work_dir else Path.cwd()
            file_path = (base / file_path).resolve()

        if not self.allow_outside_workdir and effective_work_dir:
            try:
                file_path.relative_to(expand_path(effective_work_dir))
            except ValueError as err:
                msg = f"Path {path} is outside work directory"
                raise ValueError(msg) from err

        return file_path

    def _run(self, path: str, line: int, content: str) -> str:
        """Insert content at line number.

        Args:
            path: Absolute file path
            line: Line number to insert at (1-indexed)
            content: Content to insert

        Returns:
            Success message

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If line number is invalid
        """
        try:
            file_path = self._resolve_path(path)
            if not file_path.exists():
                msg = f"File not found: {path}"
                raise FileNotFoundError(msg)

            lines = Path(file_path).read_text(encoding="utf-8").splitlines(keepends=True)

            total_lines = len(lines)
            if line < 1 or line > total_lines + 1:
                msg = f"Invalid line: {line}. Must be between 1 and {total_lines + 1}."
                raise ValueError(msg)

            new_lines = content.splitlines(keepends=True)
            if new_lines and not new_lines[-1].endswith("\n"):
                new_lines[-1] += "\n"

            lines_inserted = len(new_lines)
            lines[line - 1 : line - 1] = new_lines

            Path(file_path).write_text("".join(lines), encoding="utf-8")

            return f"Inserted {lines_inserted} lines at line {line} in {_display_path(file_path, self.work_dir)}"

        except (FileNotFoundError, ValueError) as e:
            return f"Error: {e}"
        except Exception as e:
            logger.exception("Failed to insert lines")
            return f"Error inserting lines: {e}"

    async def _arun(self, path: str, line: int, content: str) -> str:
        """Async execution (delegates to sync)."""
        return self._run(path, line, content)


class DeleteLinesTool(BaseTool):
    """Delete specific line range from a file.

    Use this tool to remove unused imports, delete deprecated functions,
    or remove commented-out code.
    """

    name: str = "delete_lines"
    description: str = (
        "Delete specific line range from a file. "
        "Parameters: path, start_line, end_line (all required). "
        "Returns: confirmation message."
    )

    work_dir: str = Field(default="", description="Working directory")
    allow_outside_workdir: bool = Field(default=False)

    def _resolve_path(self, path: str) -> Path:
        """Resolve and validate file path."""
        effective_work_dir = _get_effective_work_dir(self.work_dir)
        file_path = Path(path)

        if not file_path.is_absolute():
            base = expand_path(effective_work_dir) if effective_work_dir else Path.cwd()
            file_path = (base / file_path).resolve()

        if not self.allow_outside_workdir and effective_work_dir:
            try:
                file_path.relative_to(expand_path(effective_work_dir))
            except ValueError as err:
                msg = f"Path {path} is outside work directory"
                raise ValueError(msg) from err

        return file_path

    def _run(self, path: str, start_line: int, end_line: int) -> str:
        """Delete lines start_line to end_line (inclusive).

        Args:
            path: Absolute file path
            start_line: First line to delete (1-indexed, inclusive)
            end_line: Last line to delete (1-indexed, inclusive)

        Returns:
            Success message

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If line range is invalid
        """
        try:
            file_path = self._resolve_path(path)
            if not file_path.exists():
                msg = f"File not found: {path}"
                raise FileNotFoundError(msg)

            lines = Path(file_path).read_text(encoding="utf-8").splitlines(keepends=True)

            total_lines = len(lines)
            if start_line < 1 or start_line > total_lines:
                msg = f"Invalid start_line: {start_line}. File has {total_lines} lines."
                raise ValueError(msg)
            if end_line < start_line or end_line > total_lines:
                msg = (
                    f"Invalid end_line: {end_line}. "
                    f"Must be >= start_line ({start_line}) and <= total lines ({total_lines})."
                )
                raise ValueError(msg)

            lines_deleted = end_line - start_line + 1
            del lines[start_line - 1 : end_line]

            Path(file_path).write_text("".join(lines), encoding="utf-8")

        except (FileNotFoundError, ValueError) as e:
            return f"Error: {e}"
        except Exception as e:
            logger.exception("Failed to delete lines")
            return f"Error deleting lines: {e}"
        else:
            display_path = _display_path(file_path, self.work_dir)
            return (
                f"Deleted lines {start_line}-{end_line} ({lines_deleted} lines) from {display_path}"
            )

    async def _arun(self, path: str, start_line: int, end_line: int) -> str:
        """Async execution (delegates to sync)."""
        return self._run(path, start_line, end_line)


class ApplyDiffTool(BaseTool):
    """Apply a unified diff patch to a file.

    Use this tool to apply patches from git diff or code reviews.
    """

    name: str = "apply_diff"
    description: str = (
        "Apply a unified diff patch to a file. "
        "Parameters: path, diff (both required). "
        "Returns: confirmation message. "
        "Use for: applying patches from git diff, code reviews."
    )

    work_dir: str = Field(default="", description="Working directory")
    allow_outside_workdir: bool = Field(default=False)

    def _resolve_path(self, path: str) -> Path:
        """Resolve and validate file path."""
        effective_work_dir = _get_effective_work_dir(self.work_dir)
        file_path = Path(path)

        if not file_path.is_absolute():
            base = expand_path(effective_work_dir) if effective_work_dir else Path.cwd()
            file_path = (base / file_path).resolve()

        if not self.allow_outside_workdir and effective_work_dir:
            try:
                file_path.relative_to(expand_path(effective_work_dir))
            except ValueError as err:
                msg = f"Path {path} is outside work directory"
                raise ValueError(msg) from err

        return file_path

    def _run(self, path: str, diff: str) -> str:
        """Apply unified diff to file.

        Args:
            path: Absolute file path
            diff: Unified diff format patch

        Returns:
            Success message

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If diff is malformed or doesn't apply cleanly
        """
        try:
            file_path = self._resolve_path(path)
            if not file_path.exists():
                msg = f"File not found: {path}"
                raise FileNotFoundError(msg)

            with tempfile.NamedTemporaryFile(mode="w", suffix=".patch", delete=False) as patch_file:
                patch_file.write(diff)
                patch_path = patch_file.name

            try:
                result = subprocess.run(
                    ["patch", "-p0", "-i", patch_path, str(file_path)],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )

                if result.returncode != 0:
                    msg = f"Failed to apply diff:\n{result.stderr}\nEnsure diff is in unified format and applies cleanly."
                    raise ValueError(msg)

                return f"Applied diff to {_display_path(file_path, self.work_dir)}"

            finally:
                Path(patch_path).unlink()

        except (FileNotFoundError, ValueError) as e:
            return f"Error: {e}"
        except subprocess.TimeoutExpired:
            return "Error: Diff application timed out"
        except Exception as e:
            logger.exception("Failed to apply diff")
            return f"Error applying diff: {e}"

    async def _arun(self, path: str, diff: str) -> str:
        """Async execution (delegates to sync)."""
        return self._run(path, diff)


class FileOpsToolkit:
    """Toolkit for file operations not available in deepagents FilesystemMiddleware.

    Provides: delete_file, file_info, edit_file_lines, insert_lines, delete_lines, apply_diff
    Does NOT provide: read_file, write_file, search_files, list_files (use deepagents)
    """

    def __init__(self, *, work_dir: str = "", allow_outside_workdir: bool = False) -> None:
        self._work_dir = work_dir
        self._allow_outside_workdir = allow_outside_workdir

    def get_tools(self) -> list[BaseTool]:
        return [
            DeleteFileTool(
                work_dir=self._work_dir, allow_outside_workdir=self._allow_outside_workdir
            ),
            FileInfoTool(
                work_dir=self._work_dir, allow_outside_workdir=self._allow_outside_workdir
            ),
            EditFileLinesTool(
                work_dir=self._work_dir, allow_outside_workdir=self._allow_outside_workdir
            ),
            InsertLinesTool(
                work_dir=self._work_dir, allow_outside_workdir=self._allow_outside_workdir
            ),
            DeleteLinesTool(
                work_dir=self._work_dir, allow_outside_workdir=self._allow_outside_workdir
            ),
            ApplyDiffTool(
                work_dir=self._work_dir, allow_outside_workdir=self._allow_outside_workdir
            ),
        ]


@plugin(
    name="file_ops", version="1.0.0", description="File system operations", trust_level="built-in"
)
class FileOpsPlugin:
    """File operations tools plugin.

    Provides delete_file, file_info, edit_file_lines, insert_lines, delete_lines, apply_diff.
    """

    def __init__(self) -> None:
        """Initialize the plugin."""
        self._tools: list[BaseTool] = []

    async def on_load(self, context) -> None:
        """Initialize tools with workspace from config.

        Args:
            context: Plugin context with config and logger.
        """
        workspace_root = context.config.get("workspace_root", "")
        toolkit = FileOpsToolkit(work_dir=workspace_root)
        self._tools = toolkit.get_tools()

        context.logger.info(
            "Loaded %d file_ops tools (workspace=%s)",
            len(self._tools),
            workspace_root,
        )

    def get_tools(self) -> list[BaseTool]:
        """Get list of langchain tools.

        Returns:
            List of file operation tool instances.
        """
        return self._tools
