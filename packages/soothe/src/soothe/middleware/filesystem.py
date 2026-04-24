"""SootheFilesystemMiddleware -- surgical file operations extending deepagents."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from deepagents.backends.utils import validate_path
from deepagents.middleware.filesystem import FilesystemMiddleware
from langchain.tools import ToolRuntime
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field


# Tool schemas (following deepagents pattern)
class DeleteFileSchema(BaseModel):
    """Input schema for the `delete_file` tool."""

    file_path: str = Field(
        description="Absolute path to the file to delete. Must be absolute, not relative."
    )


class FileInfoSchema(BaseModel):
    """Input schema for the `file_info` tool."""

    path: str = Field(
        description="Absolute path to get metadata for. Must be absolute, not relative."
    )


class EditFileLinesSchema(BaseModel):
    """Input schema for the `edit_file_lines` tool."""

    file_path: str = Field(
        description="Absolute path to the file to edit. Must be absolute, not relative."
    )
    start_line: int = Field(
        description="First line to replace (1-indexed, inclusive). Example: 1 means first line."
    )
    end_line: int = Field(
        description="Last line to replace (1-indexed, inclusive). Must be >= start_line."
    )
    new_content: str = Field(
        description="New content to insert. Will replace lines from start_line to end_line."
    )


class InsertLinesSchema(BaseModel):
    """Input schema for the `insert_lines` tool."""

    file_path: str = Field(description="Absolute path to the file. Must be absolute, not relative.")
    line: int = Field(
        description="Line number to insert at (1-indexed). Can be 1 to total_lines+1."
    )
    content: str = Field(description="Content to insert at the specified line.")


class DeleteLinesSchema(BaseModel):
    """Input schema for the `delete_lines` tool."""

    file_path: str = Field(description="Absolute path to the file. Must be absolute, not relative.")
    start_line: int = Field(description="First line to delete (1-indexed, inclusive).")
    end_line: int = Field(
        description="Last line to delete (1-indexed, inclusive). Must be >= start_line."
    )


class ApplyDiffSchema(BaseModel):
    """Input schema for the `apply_diff` tool."""

    file_path: str = Field(
        description="Absolute path to the file to patch. Must be absolute, not relative."
    )
    diff: str = Field(description="Unified diff content to apply. Must be in standard diff format.")


# Tool descriptions (following deepagents pattern)
DELETE_FILE_TOOL_DESCRIPTION = """Delete a file with optional backup before deletion.

Usage:
- Creates automatic backup in .backups directory before deletion
- Backup files are timestamped for easy recovery
- Returns error if file doesn't exist or is not a file
- Use with caution - deletion is permanent (backup is the safety net)"""

FILE_INFO_TOOL_DESCRIPTION = """Get file metadata (size, modification time, permissions).

Usage:
- Returns comprehensive file information: size, timestamps, file type
- Useful for checking file details before operations
- Returns error if path doesn't exist"""

EDIT_FILE_LINES_TOOL_DESCRIPTION = """Replace specific line range in a file (surgical edit).

Usage:
- More efficient than read → modify → write for targeted changes
- Line numbers are 1-indexed (first line is line 1)
- Both start_line and end_line are inclusive
- Safer for large files - only loads needed sections"""

INSERT_LINES_TOOL_DESCRIPTION = """Insert content at a specific line number.

Usage:
- Line numbers are 1-indexed (first line is line 1)
- Can insert at beginning (line=1), middle, or end (line=total_lines+1)
- Useful for adding imports, functions, or configuration entries"""

DELETE_LINES_TOOL_DESCRIPTION = """Delete specific line range from a file.

Usage:
- Line numbers are 1-indexed and inclusive
- Useful for removing unused imports, deprecated functions
- More precise than edit_file for removing sections"""

APPLY_DIFF_TOOL_DESCRIPTION = """Apply a unified diff patch to a file.

Usage:
- Diff must be in standard unified diff format
- Uses the 'patch' command-line tool
- Useful for applying changes from git diff or code reviews
- Returns error if diff doesn't apply cleanly"""


class SootheFilesystemMiddleware(FilesystemMiddleware):
    """Extended filesystem middleware with surgical file operations.

    Inherits from deepagents FilesystemMiddleware and adds:
    - delete_file: Delete files with optional backup
    - file_info: Get file metadata (size, mtime, permissions)
    - edit_file_lines: Replace specific line ranges (surgical edit)
    - insert_lines: Insert content at specific line number
    - delete_lines: Delete specific line ranges from a file
    - apply_diff: Apply unified diff patches

    All tools follow deepagents patterns:
    - Schema validation with XxxSchema(BaseModel)
    - ToolRuntime injection for backend access
    - Path validation with validate_path()
    - StructuredTool.from_function() with infer_schema=False

    Args:
        backup_enabled: Enable automatic backup before file deletion.
        backup_dir: Directory for backup files (default: .backups).
        workspace_root: Root directory for workspace operations.
        **kwargs: Additional arguments passed to FilesystemMiddleware.
    """

    def __init__(
        self,
        *,
        backup_enabled: bool = True,
        backup_dir: str | None = None,
        workspace_root: str | None = None,
        **kwargs,
    ) -> None:
        """Initialize SootheFilesystemMiddleware.

        Args:
            backup_enabled: Enable automatic backup before deletion.
            backup_dir: Custom backup directory path.
            workspace_root: Workspace root directory for path resolution.
            **kwargs: Passed to FilesystemMiddleware (backend, system_prompt, etc.)
        """
        super().__init__(**kwargs)

        self._backup_enabled = backup_enabled
        self._backup_dir = backup_dir
        self._workspace_root = workspace_root

        # Add surgical file tools following deepagents pattern
        self.tools.extend(
            [
                self._create_delete_file_tool(),
                self._create_file_info_tool(),
                self._create_edit_file_lines_tool(),
                self._create_insert_lines_tool(),
                self._create_delete_lines_tool(),
                self._create_apply_diff_tool(),
            ]
        )

    def _create_delete_file_tool(self) -> BaseTool:
        """Create the delete_file tool with backup support."""

        def sync_delete_file(
            file_path: Annotated[
                str, "Absolute path to the file to delete. Must be absolute, not relative."
            ],
            runtime: ToolRuntime | None = None,
        ) -> str:
            """Synchronous wrapper for delete_file tool."""
            try:
                validated_path = validate_path(file_path)
            except ValueError as e:
                return f"Error: {e}"

            resolved_path = Path(validated_path)

            if not resolved_path.exists():
                return f"Error: File not found: {file_path}"

            if not resolved_path.is_file():
                return f"Error: Not a file: {file_path}"

            # Create backup if enabled
            backup_path = None
            if self._backup_enabled:
                backup_base = Path(self._backup_dir or resolved_path.parent / ".backups")
                backup_base.mkdir(parents=True, exist_ok=True)

                timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
                backup_name = f"{resolved_path.stem}_{timestamp}{resolved_path.suffix}"
                backup_path = backup_base / backup_name

                shutil.copy2(resolved_path, backup_path)

            # Delete file
            resolved_path.unlink()

            result = f"Deleted: {file_path}"
            if backup_path:
                result += f" (backup: {backup_path.name})"

            return result

        async def async_delete_file(
            file_path: Annotated[
                str, "Absolute path to the file to delete. Must be absolute, not relative."
            ],
            runtime: ToolRuntime | None = None,
        ) -> str:
            """Asynchronous wrapper for delete_file tool."""
            # File deletion is inherently synchronous
            return sync_delete_file(file_path, runtime=runtime)

        return StructuredTool.from_function(
            name="delete_file",
            description=DELETE_FILE_TOOL_DESCRIPTION,
            func=sync_delete_file,
            coroutine=async_delete_file,
            infer_schema=False,
            args_schema=DeleteFileSchema,
        )

    def _create_file_info_tool(self) -> BaseTool:
        """Create the file_info tool for metadata retrieval."""

        def sync_file_info(
            path: Annotated[
                str, "Absolute path to get metadata for. Must be absolute, not relative."
            ],
            runtime: ToolRuntime | None = None,
        ) -> str:
            """Synchronous wrapper for file_info tool."""
            try:
                validated_path = validate_path(path)
            except ValueError as e:
                return f"Error: {e}"

            resolved_path = Path(validated_path)

            if not resolved_path.exists():
                return f"Error: File not found: {path}"

            stat = resolved_path.stat()
            mtime = datetime.fromtimestamp(stat.st_mtime, tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
            atime = datetime.fromtimestamp(stat.st_atime, tz=UTC).strftime("%Y-%m-%d %H:%M:%S")

            info = [
                f"Path: {resolved_path}",
                f"Size: {stat.st_size} bytes ({stat.st_size / 1024:.2f} KB)",
                f"Modified: {mtime}",
                f"Accessed: {atime}",
                f"Is File: {resolved_path.is_file()}",
                f"Is Directory: {resolved_path.is_dir()}",
            ]

            return "\n".join(info)

        async def async_file_info(
            path: Annotated[
                str, "Absolute path to get metadata for. Must be absolute, not relative."
            ],
            runtime: ToolRuntime | None = None,
        ) -> str:
            """Asynchronous wrapper for file_info tool."""
            return sync_file_info(path, runtime=runtime)

        return StructuredTool.from_function(
            name="file_info",
            description=FILE_INFO_TOOL_DESCRIPTION,
            func=sync_file_info,
            coroutine=async_file_info,
            infer_schema=False,
            args_schema=FileInfoSchema,
        )

    def _create_edit_file_lines_tool(self) -> BaseTool:
        """Create the edit_file_lines tool for surgical line replacement."""

        def sync_edit_file_lines(
            file_path: Annotated[
                str, "Absolute path to the file to edit. Must be absolute, not relative."
            ],
            start_line: Annotated[int, "First line to replace (1-indexed, inclusive)."],
            end_line: Annotated[int, "Last line to replace (1-indexed, inclusive)."],
            new_content: Annotated[str, "New content to insert."],
            runtime: ToolRuntime | None = None,
        ) -> str:
            """Synchronous wrapper for edit_file_lines tool."""
            try:
                validated_path = validate_path(file_path)
            except ValueError as e:
                return f"Error: {e}"

            resolved_path = Path(validated_path)

            if not resolved_path.exists():
                return f"Error: File not found: {file_path}"

            if not resolved_path.is_file():
                return f"Error: Not a file: {file_path}"

            # Read raw file content directly
            try:
                original_content = resolved_path.read_text(encoding="utf-8")
            except OSError as e:
                return f"Error reading file: {e}"

            lines = original_content.splitlines(keepends=True)

            total_lines = len(lines)

            # Validate line range
            if start_line < 1 or start_line > total_lines:
                return f"Error: Invalid start_line: {start_line}. File has {total_lines} lines (1-indexed)."

            if end_line < start_line or end_line > total_lines:
                return f"Error: Invalid end_line: {end_line}. Must be >= {start_line} and <= {total_lines}."

            # Prepare new content
            new_lines = new_content.splitlines(keepends=True)
            if new_lines and not new_lines[-1].endswith("\n"):
                new_lines[-1] += "\n"

            lines_removed = end_line - start_line + 1
            lines_added = len(new_lines)

            # Replace lines
            lines[start_line - 1 : end_line] = new_lines
            modified_content = "".join(lines)

            # Write back using backend edit
            resolved_backend = self._get_backend(runtime) if runtime else self.backend
            edit_result = resolved_backend.edit(
                str(resolved_path),
                original_content,
                modified_content,
                replace_all=False,
            )
            if edit_result.error:
                return f"Error: {edit_result.error}"

            return (
                f"Updated {file_path}\n"
                f"Lines {start_line}-{end_line} replaced "
                f"({lines_removed} removed, {lines_added} added)"
            )

        async def async_edit_file_lines(
            file_path: Annotated[str, "Absolute path to the file to edit."],
            start_line: Annotated[int, "First line to replace (1-indexed)."],
            end_line: Annotated[int, "Last line to replace (1-indexed)."],
            new_content: Annotated[str, "New content to insert."],
            runtime: ToolRuntime | None = None,
        ) -> str:
            """Asynchronous wrapper for edit_file_lines tool."""
            # File read/line ops are synchronous, delegate
            return sync_edit_file_lines(
                file_path, start_line, end_line, new_content, runtime=runtime
            )

        return StructuredTool.from_function(
            name="edit_file_lines",
            description=EDIT_FILE_LINES_TOOL_DESCRIPTION,
            func=sync_edit_file_lines,
            coroutine=async_edit_file_lines,
            infer_schema=False,
            args_schema=EditFileLinesSchema,
        )

    def _create_insert_lines_tool(self) -> BaseTool:
        """Create the insert_lines tool."""

        def sync_insert_lines(
            file_path: Annotated[str, "Absolute path to the file."],
            line: Annotated[int, "Line number to insert at (1-indexed)."],
            content: Annotated[str, "Content to insert at the specified line."],
            runtime: ToolRuntime | None = None,
        ) -> str:
            """Synchronous wrapper for insert_lines tool."""
            try:
                validated_path = validate_path(file_path)
            except ValueError as e:
                return f"Error: {e}"

            resolved_path = Path(validated_path)

            if not resolved_path.exists():
                return f"Error: File not found: {file_path}"

            # Read raw file content directly
            try:
                file_content = resolved_path.read_text(encoding="utf-8")
            except OSError as e:
                return f"Error reading file: {e}"

            lines = file_content.splitlines(keepends=True)

            total_lines = len(lines)

            # Validate line number
            if line < 1 or line > total_lines + 1:
                return f"Error: Invalid line: {line}. Must be between 1 and {total_lines + 1}."

            # Prepare new lines
            new_lines = content.splitlines(keepends=True)
            if new_lines and not new_lines[-1].endswith("\n"):
                new_lines[-1] += "\n"

            lines_inserted = len(new_lines)

            # Insert at position
            lines[line - 1 : line - 1] = new_lines

            # Write back using backend edit
            modified_content = "".join(lines)
            resolved_backend = self._get_backend(runtime) if runtime else self.backend
            edit_result = resolved_backend.edit(
                str(resolved_path),
                file_content,
                modified_content,
                replace_all=False,
            )
            if edit_result.error:
                return f"Error: {edit_result.error}"

            return f"Inserted {lines_inserted} lines at line {line} in {file_path}"

        async def async_insert_lines(
            file_path: Annotated[str, "Absolute path to the file."],
            line: Annotated[int, "Line number to insert at (1-indexed)."],
            content: Annotated[str, "Content to insert at the specified line."],
            runtime: ToolRuntime | None = None,
        ) -> str:
            """Asynchronous wrapper for insert_lines tool."""
            return sync_insert_lines(file_path, line, content, runtime=runtime)

        return StructuredTool.from_function(
            name="insert_lines",
            description=INSERT_LINES_TOOL_DESCRIPTION,
            func=sync_insert_lines,
            coroutine=async_insert_lines,
            infer_schema=False,
            args_schema=InsertLinesSchema,
        )

    def _create_delete_lines_tool(self) -> BaseTool:
        """Create the delete_lines tool."""

        def sync_delete_lines(
            file_path: Annotated[str, "Absolute path to the file."],
            start_line: Annotated[int, "First line to delete (1-indexed)."],
            end_line: Annotated[int, "Last line to delete (1-indexed)."],
            runtime: ToolRuntime | None = None,
        ) -> str:
            """Synchronous wrapper for delete_lines tool."""
            try:
                validated_path = validate_path(file_path)
            except ValueError as e:
                return f"Error: {e}"

            resolved_path = Path(validated_path)

            if not resolved_path.exists():
                return f"Error: File not found: {file_path}"

            # Read raw file content directly
            try:
                file_content = resolved_path.read_text(encoding="utf-8")
            except OSError as e:
                return f"Error reading file: {e}"

            lines = file_content.splitlines(keepends=True)

            total_lines = len(lines)

            # Validate line range
            if start_line < 1 or start_line > total_lines:
                return f"Error: Invalid start_line: {start_line}. File has {total_lines} lines."

            if end_line < start_line or end_line > total_lines:
                return f"Error: Invalid end_line: {end_line}. Must be >= {start_line} and <= {total_lines}."

            lines_deleted = end_line - start_line + 1

            # Delete lines
            del lines[start_line - 1 : end_line]

            # Write back using backend edit
            modified_content = "".join(lines)
            resolved_backend = self._get_backend(runtime) if runtime else self.backend
            edit_result = resolved_backend.edit(
                str(resolved_path),
                file_content,
                modified_content,
                replace_all=False,
            )
            if edit_result.error:
                return f"Error: {edit_result.error}"

            return f"Deleted lines {start_line}-{end_line} ({lines_deleted} lines) from {file_path}"

        async def async_delete_lines(
            file_path: Annotated[str, "Absolute path to the file."],
            start_line: Annotated[int, "First line to delete (1-indexed)."],
            end_line: Annotated[int, "Last line to delete (1-indexed)."],
            runtime: ToolRuntime | None = None,
        ) -> str:
            """Asynchronous wrapper for delete_lines tool."""
            return sync_delete_lines(file_path, start_line, end_line, runtime=runtime)

        return StructuredTool.from_function(
            name="delete_lines",
            description=DELETE_LINES_TOOL_DESCRIPTION,
            func=sync_delete_lines,
            coroutine=async_delete_lines,
            infer_schema=False,
            args_schema=DeleteLinesSchema,
        )

    def _create_apply_diff_tool(self) -> BaseTool:
        """Create the apply_diff tool for patch application."""

        def sync_apply_diff(
            file_path: Annotated[str, "Absolute path to the file to patch."],
            diff: Annotated[str, "Unified diff content to apply."],
            runtime: ToolRuntime | None = None,
        ) -> str:
            """Synchronous wrapper for apply_diff tool."""
            try:
                validated_path = validate_path(file_path)
            except ValueError as e:
                return f"Error: {e}"

            resolved_path = Path(validated_path)

            if not resolved_path.exists():
                return f"Error: File not found: {file_path}"

            try:
                # Create temporary patch file
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".patch", delete=False
                ) as patch_file:
                    patch_file.write(diff)
                    patch_path = patch_file.name

                try:
                    # Apply patch using patch command
                    result = subprocess.run(
                        ["patch", "-p0", "-i", patch_path, str(resolved_path)],
                        capture_output=True,
                        text=True,
                        timeout=10,
                        check=False,
                    )

                    if result.returncode != 0:
                        return (
                            f"Failed to apply diff:\n{result.stderr}\n"
                            "Ensure diff is in unified format and applies cleanly."
                        )

                    return f"Applied diff to {file_path}"

                finally:
                    # Clean up temp file
                    Path(patch_path).unlink()

            except subprocess.TimeoutExpired:
                return "Error: Diff application timed out"
            except Exception as e:
                return f"Error applying diff: {e}"

        async def async_apply_diff(
            file_path: Annotated[str, "Absolute path to the file to patch."],
            diff: Annotated[str, "Unified diff content to apply."],
            runtime: ToolRuntime | None = None,
        ) -> str:
            """Asynchronous wrapper for apply_diff tool."""
            # Patch application is inherently synchronous via subprocess
            return sync_apply_diff(file_path, diff, runtime=runtime)

        return StructuredTool.from_function(
            name="apply_diff",
            description=APPLY_DIFF_TOOL_DESCRIPTION,
            func=sync_apply_diff,
            coroutine=async_apply_diff,
            infer_schema=False,
            args_schema=ApplyDiffSchema,
        )
