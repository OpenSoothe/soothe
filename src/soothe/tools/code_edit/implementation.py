"""Surgical code editing tools (RFC-0016).

These tools enable line-based modifications without requiring full-file rewrites,
dramatically reducing the risk of errors and improving workflow efficiency.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

from langchain_core.tools import BaseTool
from pydantic import Field

from soothe.tools._internal.file_edit import _display_path
from soothe.tools.code_edit.events import (
    FileEditCompletedEvent,
    FileEditFailedEvent,
    FileEditStartedEvent,
)
from soothe.utils import expand_path
from soothe.utils.progress import emit_progress

logger = logging.getLogger(__name__)


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
        file_path = Path(path)

        # Handle relative paths
        if not file_path.is_absolute():
            base = expand_path(self.work_dir) if self.work_dir else Path.cwd()
            file_path = (base / file_path).resolve()

        # Security check
        if not self.allow_outside_workdir and self.work_dir:
            try:
                file_path.relative_to(expand_path(self.work_dir))
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
        # Emit edit started event
        emit_progress(
            FileEditStartedEvent(
                path=path,
                operation="edit_lines",
            ).to_dict(),
            logger,
        )

        try:
            # Validate path
            file_path = self._resolve_path(path)
            if not file_path.exists():
                msg = f"File not found: {path}"
                raise FileNotFoundError(msg)

            if not file_path.is_file():
                msg = f"Path is not a file: {path}"
                raise ValueError(msg)

            # Read file
            with file_path.open(encoding="utf-8") as f:
                lines = f.readlines()

            # Validate line range
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

            # Prepare new content (ensure it ends with newline if original lines did)
            new_lines = new_content.splitlines(keepends=True)
            if new_lines and not new_lines[-1].endswith("\n"):
                new_lines[-1] += "\n"

            # Count lines before/after
            lines_removed = end_line - start_line + 1
            lines_added = len(new_lines)

            # Perform replacement
            lines[start_line - 1 : end_line] = new_lines

            # Write back
            with file_path.open("w", encoding="utf-8") as f:
                f.writelines(lines)

            # Emit edit completed event
            emit_progress(
                FileEditCompletedEvent(
                    path=path,
                    lines_removed=lines_removed,
                    lines_added=lines_added,
                ).to_dict(),
                logger,
            )

            return (
                f"Updated {_display_path(file_path, self.work_dir)}\n"
                f"Lines {start_line}-{end_line} replaced "
                f"({lines_removed} removed, {lines_added} added)"
            )

        except (FileNotFoundError, ValueError) as e:
            emit_progress(
                FileEditFailedEvent(path=path, error=str(e)).to_dict(),
                logger,
            )
            return f"Error: {e}"
        except Exception as e:
            logger.exception("Failed to edit file lines")
            emit_progress(
                FileEditFailedEvent(path=path, error=str(e)).to_dict(),
                logger,
            )
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
        file_path = Path(path)

        if not file_path.is_absolute():
            base = expand_path(self.work_dir) if self.work_dir else Path.cwd()
            file_path = (base / file_path).resolve()

        if not self.allow_outside_workdir and self.work_dir:
            try:
                file_path.relative_to(expand_path(self.work_dir))
            except ValueError as err:
                msg = f"Path {path} is outside work directory"
                raise ValueError(msg) from err

        return file_path

    def _run(self, path: str, line: int, content: str) -> str:
        """Insert content at line number.

        Args:
            path: Absolute file path
            line: Line number to insert at (1-indexed)
                  - line=1 inserts at beginning
                  - line=N inserts before line N
                  - line=N+1 appends at end
            content: Content to insert

        Returns:
            Success message

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If line number is invalid
        """
        try:
            # Validate path
            file_path = self._resolve_path(path)
            if not file_path.exists():
                msg = f"File not found: {path}"
                raise FileNotFoundError(msg)

            # Read file
            lines = Path(file_path).read_text(encoding="utf-8").splitlines(keepends=True)

            # Validate line number
            total_lines = len(lines)
            if line < 1 or line > total_lines + 1:
                msg = f"Invalid line: {line}. Must be between 1 and {total_lines + 1}."
                raise ValueError(msg)

            # Prepare content
            new_lines = content.splitlines(keepends=True)
            if new_lines and not new_lines[-1].endswith("\n"):
                new_lines[-1] += "\n"

            # Insert
            lines_inserted = len(new_lines)
            lines[line - 1 : line - 1] = new_lines

            # Write back
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
        file_path = Path(path)

        if not file_path.is_absolute():
            base = expand_path(self.work_dir) if self.work_dir else Path.cwd()
            file_path = (base / file_path).resolve()

        if not self.allow_outside_workdir and self.work_dir:
            try:
                file_path.relative_to(expand_path(self.work_dir))
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
            # Validate path
            file_path = self._resolve_path(path)
            if not file_path.exists():
                msg = f"File not found: {path}"
                raise FileNotFoundError(msg)

            # Read file
            lines = Path(file_path).read_text(encoding="utf-8").splitlines(keepends=True)

            # Validate line range
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

            # Delete
            lines_deleted = end_line - start_line + 1
            del lines[start_line - 1 : end_line]

            # Write back
            Path(file_path).write_text("".join(lines), encoding="utf-8")

        except (FileNotFoundError, ValueError) as e:
            return f"Error: {e}"
        except Exception as e:
            logger.exception("Failed to delete lines")
            return f"Error deleting lines: {e}"
        else:
            display_path = _display_path(file_path, self.work_dir)
            return f"Deleted lines {start_line}-{end_line} ({lines_deleted} lines) from {display_path}"

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
        file_path = Path(path)

        if not file_path.is_absolute():
            base = expand_path(self.work_dir) if self.work_dir else Path.cwd()
            file_path = (base / file_path).resolve()

        if not self.allow_outside_workdir and self.work_dir:
            try:
                file_path.relative_to(expand_path(self.work_dir))
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
            # Validate path
            file_path = self._resolve_path(path)
            if not file_path.exists():
                msg = f"File not found: {path}"
                raise FileNotFoundError(msg)

            # Create temporary patch file
            with tempfile.NamedTemporaryFile(mode="w", suffix=".patch", delete=False) as patch_file:
                patch_file.write(diff)
                patch_path = patch_file.name

            try:
                # Apply patch using patch command
                result = subprocess.run(
                    ["patch", "-p0", "-i", patch_path, str(file_path)],  # noqa: S607
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )

                if result.returncode != 0:
                    msg = (
                        f"Failed to apply diff:\n{result.stderr}\nEnsure diff is in unified format and applies cleanly."
                    )
                    raise ValueError(msg)

                return f"Applied diff to {_display_path(file_path, self.work_dir)}"

            finally:
                # Clean up temporary file
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


def create_code_edit_tools(
    *,
    work_dir: str = "",
    allow_outside_workdir: bool = False,
) -> list[BaseTool]:
    """Create all surgical code editing tools.

    Args:
        work_dir: Working directory for relative paths.
        allow_outside_workdir: Allow access outside workspace.

    Returns:
        List of surgical editing BaseTool instances.
    """
    return [
        EditFileLinesTool(work_dir=work_dir, allow_outside_workdir=allow_outside_workdir),
        InsertLinesTool(work_dir=work_dir, allow_outside_workdir=allow_outside_workdir),
        DeleteLinesTool(work_dir=work_dir, allow_outside_workdir=allow_outside_workdir),
        ApplyDiffTool(work_dir=work_dir, allow_outside_workdir=allow_outside_workdir),
    ]
