"""SootheFilesystemMiddleware -- surgical file operations."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from deepagents.backends.protocol import BackendProtocol
from deepagents.backends.utils import validate_path
from deepagents.middleware.filesystem import (
    FilesystemMiddleware,
    FilesystemState,
    truncate_if_too_long,
)
from langchain.tools import ToolRuntime
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.types import Command
from pydantic import BaseModel, Field

from soothe.foundation.core.filesystem.discovery_hints import GLOB_TOOL_DESCRIPTION

# OpenAI-compatible chat APIs used by many Soothe providers (e.g. coding-plan) reject
# LangChain ``file`` / ``audio`` tool-result blocks. ``read_file`` on PDFs returns those.
_PROVIDER_SAFE_TOOL_BLOCK_TYPES = frozenset(
    {"text", "image", "image_url", "video", "video_url"},
)


def coerce_provider_safe_tool_message(
    message: ToolMessage | Command[Any],
) -> ToolMessage | Command[Any]:
    """Replace unsupported multimodal tool blocks with plain-text guidance.

    Deepagents ``read_file`` returns ``file`` blocks for PDFs and ``audio`` blocks for
    audio files. Providers that only accept ``text``, ``image_url``, and ``video*``
    then fail the next model turn with ``Invalid value: file``.

    Args:
        message: Tool result from filesystem middleware (or a Command wrapper).

    Returns:
        A copy of the message with unsafe blocks converted to text, or the original
        value when no conversion is needed.
    """
    if not isinstance(message, ToolMessage):
        return message

    blocks = message.content_blocks
    if not blocks:
        return message

    safe_blocks: list[dict[str, Any]] = []
    converted = False
    for block in blocks:
        block_type = block.get("type") if isinstance(block, dict) else None
        if block_type in _PROVIDER_SAFE_TOOL_BLOCK_TYPES:
            safe_blocks.append(block)
            continue

        converted = True
        path = message.additional_kwargs.get("read_file_path", "")
        mime = block.get("mime_type") if isinstance(block, dict) else None
        mime_part = f", mime_type={mime}" if mime else ""
        path_part = f" at {path}" if path else ""
        safe_blocks.append(
            {
                "type": "text",
                "text": (
                    "System reminder: read_file returned a document or media file"
                    f"{path_part} (block type={block_type!r}{mime_part}) that cannot be "
                    "sent inline to this chat model. Use goal attachment text, "
                    "run_command (e.g. pdftotext or a PDF parser), or paginated text "
                    "reads on extracted files instead of read_file on this path."
                ),
            }
        )

    if not converted:
        return message

    return message.model_copy(update={"content": safe_blocks})


# Tool schemas
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
        default=1,
        description=(
            "Line number to insert at (1-indexed). Defaults to 1 for frontmatter at file top. "
            "Valid range: 1 to total_lines+1."
        ),
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


# Tool descriptions
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

    Inherits from FilesystemMiddleware and adds:
    - delete_file: Delete files with optional backup
    - file_info: Get file metadata (size, mtime, permissions)
    - edit_file_lines: Replace specific line ranges (surgical edit)
    - insert_lines: Insert content at specific line number
    - delete_lines: Delete specific line ranges from a file
    - apply_diff: Apply unified diff patches

    All tools follow standard patterns:
    - Schema validation with XxxSchema(BaseModel)
    - ToolRuntime injection for backend access
    - Path validation with validate_path()
    - StructuredTool.from_function() with infer_schema=False

    IG-328: Supports thread workspace resolution via runtime.state["workspace"]
    without using deprecated callable backend pattern.

    Args:
        backup_enabled: Enable automatic backup before file deletion.
        backup_dir: Directory for backup files (default: .backups).
        workspace_root: Root directory for workspace operations.
        workspace_backend_factory: Optional factory for creating workspace backends.
        **kwargs: Additional arguments passed to FilesystemMiddleware.
    """

    def __init__(
        self,
        *,
        backup_enabled: bool = True,
        backup_dir: str | None = None,
        workspace_root: str | None = None,
        workspace_backend_factory: Callable[[str], BackendProtocol] | None = None,
        **kwargs,
    ) -> None:
        """Initialize SootheFilesystemMiddleware.

        Args:
            backup_enabled: Enable automatic backup before deletion.
            backup_dir: Custom backup directory path.
            workspace_root: Workspace root directory for path resolution.
            workspace_backend_factory: Factory function that takes a workspace path
                and returns a BackendProtocol instance. Used for thread workspace
                resolution without callable backend deprecation.
            **kwargs: Passed to FilesystemMiddleware (backend, system_prompt, etc.)
        """
        custom_descriptions = dict(kwargs.pop("custom_tool_descriptions", None) or {})
        custom_descriptions.setdefault("glob", GLOB_TOOL_DESCRIPTION)
        kwargs["custom_tool_descriptions"] = custom_descriptions
        super().__init__(**kwargs)

        # Override deepagents' default "/large_tool_results" and "/conversation_history"
        # prefixes which assume CompositeBackend or root-writable filesystem.
        # With NormalizedPathBackend in non-virtual mode, absolute paths outside workspace
        # are passed as-is, causing OSError on read-only root filesystems (e.g., macOS).
        # Use workspace-relative paths so artifacts land inside the workspace.
        self._large_tool_results_prefix = ".soothe/large_tool_results"
        self._conversation_history_prefix = ".soothe/conversation_history"

        self._backup_enabled = backup_enabled
        self._backup_dir = backup_dir
        self._workspace_root = workspace_root
        self._workspace_backend_factory = workspace_backend_factory

        # Add surgical file tools
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

    def _get_backend(self, runtime: ToolRuntime | None = None) -> BackendProtocol:
        """Get backend, resolving the effective stream workspace when available.

        Args:
            runtime: Tool runtime with config/state containing potential thread workspace.

        Returns:
            BackendProtocol instance for the effective workspace.
        """
        from soothe.foundation.workspace.normalized_backend import get_workspace_backend
        from soothe.foundation.workspace.runtime_resolution import (
            resolve_workspace_for_tool_execution,
        )

        workspace = resolve_workspace_for_tool_execution(
            runtime=runtime,
            fallback=self._workspace_root,
            use_langgraph_config=True,
        )
        if workspace is None:
            return self.backend

        ws_str = str(workspace)
        if self._workspace_backend_factory is not None:
            return self._workspace_backend_factory(ws_str)

        virtual_mode = bool(getattr(self.backend, "virtual_mode", False))
        max_mb = 10
        if runtime is not None and isinstance(getattr(runtime, "config", None), dict):
            configurable = runtime.config.get("configurable") or {}
            if isinstance(configurable, dict):
                soothe_config = configurable.get("soothe_config")
                if soothe_config is not None:
                    from soothe.foundation.workspace.tool_path_resolution import (
                        filesystem_virtual_mode_from_soothe_config,
                        max_file_size_mb_for_filesystem_backend,
                    )

                    virtual_mode = filesystem_virtual_mode_from_soothe_config(soothe_config)
                    max_mb = max_file_size_mb_for_filesystem_backend(soothe_config)

        return get_workspace_backend(
            workspace,
            virtual_mode=virtual_mode,
            max_file_size_mb=max_mb,
        )

    def _create_glob_tool(self) -> BaseTool:
        """Create glob tool without deepagents' 20s internal cap.

        Glob invocation timeout is enforced solely by ``ToolTimeoutMiddleware``
        (``config.agent.loop.tool_timeout.per_tool.glob``).
        """
        tool_description = self._custom_tool_descriptions.get("glob") or GLOB_TOOL_DESCRIPTION

        def sync_glob(
            pattern: Annotated[
                str,
                "Glob pattern to match files (e.g., '**/*.py', '*.txt', '/subdir/**/*.md').",
            ],
            runtime: ToolRuntime[None, FilesystemState],
            path: Annotated[str, "Base directory to search from. Defaults to root '/'."] = "/",
        ) -> str:
            resolved_backend = self._get_backend(runtime)
            try:
                validated_path = validate_path(path)
            except ValueError as e:
                return f"Error: {e}"
            infos = resolved_backend.glob_info(pattern, path=validated_path)
            paths = [fi.get("path", "") for fi in infos]
            return str(truncate_if_too_long(paths))

        async def async_glob(
            pattern: Annotated[
                str,
                "Glob pattern to match files (e.g., '**/*.py', '*.txt', '/subdir/**/*.md').",
            ],
            runtime: ToolRuntime[None, FilesystemState],
            path: Annotated[str, "Base directory to search from. Defaults to root '/'."] = "/",
        ) -> str:
            resolved_backend = self._get_backend(runtime)
            try:
                validated_path = validate_path(path)
            except ValueError as e:
                return f"Error: {e}"
            infos = await resolved_backend.aglob_info(pattern, path=validated_path)
            paths = [fi.get("path", "") for fi in infos]
            return str(truncate_if_too_long(paths))

        return StructuredTool.from_function(
            name="glob",
            description=tool_description,
            func=sync_glob,
            coroutine=async_glob,
        )

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        """Evict oversized tool results and coerce unsupported multimodal blocks."""
        result = super().wrap_tool_call(request, handler)
        return coerce_provider_safe_tool_message(result)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        """Async: evict oversized tool results and coerce unsupported multimodal blocks."""
        result = await super().awrap_tool_call(request, handler)
        return coerce_provider_safe_tool_message(result)

    def _backend_for_tools(self, runtime: ToolRuntime | None) -> BackendProtocol:
        """Resolve backend for surgical tools (IG-316, IG-328).

        Uses the overridden ``_get_backend`` which handles thread workspace
        resolution without the deprecated callable backend pattern.

        IG-328: Allow None runtime (fallback to initial backend).
        """
        return self._get_backend(runtime)

    def _try_resolve_os_path(
        self, logical_path: str, runtime: ToolRuntime | None
    ) -> tuple[Path | None, str | None]:
        """Map logical tool path to OS path via unified filesystem resolution."""
        try:
            rb = self._backend_for_tools(runtime)
            if hasattr(rb, "resolve_os_path"):
                return rb.resolve_os_path(logical_path), None
            if hasattr(rb, "_resolve_path"):
                return rb._resolve_path(logical_path), None
            return Path(logical_path).expanduser().resolve(), None
        except (ValueError, RuntimeError) as e:
            return None, str(e)

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

            resolved_path, res_err = self._try_resolve_os_path(validated_path, runtime)
            if res_err or resolved_path is None:
                return f"Error: {res_err or 'Path resolution failed'}"

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

            resolved_path, res_err = self._try_resolve_os_path(validated_path, runtime)
            if res_err or resolved_path is None:
                return f"Error: {res_err or 'Path resolution failed'}"

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

            resolved_path, res_err = self._try_resolve_os_path(validated_path, runtime)
            if res_err or resolved_path is None:
                return f"Error: {res_err or 'Path resolution failed'}"

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

            # Write back using backend edit (logical path for virtual_mode)
            resolved_backend = self._backend_for_tools(runtime)
            edit_result = resolved_backend.edit(
                validated_path,
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

            resolved_path, res_err = self._try_resolve_os_path(validated_path, runtime)
            if res_err or resolved_path is None:
                return f"Error: {res_err or 'Path resolution failed'}"

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
            resolved_backend = self._backend_for_tools(runtime)
            edit_result = resolved_backend.edit(
                validated_path,
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

            resolved_path, res_err = self._try_resolve_os_path(validated_path, runtime)
            if res_err or resolved_path is None:
                return f"Error: {res_err or 'Path resolution failed'}"

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
            resolved_backend = self._backend_for_tools(runtime)
            edit_result = resolved_backend.edit(
                validated_path,
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

            resolved_path, res_err = self._try_resolve_os_path(validated_path, runtime)
            if res_err or resolved_path is None:
                return f"Error: {res_err or 'Path resolution failed'}"

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
