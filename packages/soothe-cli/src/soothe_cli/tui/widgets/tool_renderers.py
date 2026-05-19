"""Tool renderers for approval widgets - registry pattern."""

from __future__ import annotations

import difflib
from typing import TYPE_CHECKING, Any

from soothe_cli.tui.file_ops import resolve_physical_path
from soothe_cli.tui.preview_limits import TOOL_APPROVAL_PREVIEW_LINES
from soothe_cli.tui.widgets.tool_widgets import (
    DeleteFileApprovalWidget,
    EditFileApprovalWidget,
    GenericApprovalWidget,
    WriteFileApprovalWidget,
)

if TYPE_CHECKING:
    from soothe_cli.tui.widgets.tool_widgets import ToolApprovalWidget


class ToolRenderer:
    """Strategy for building a tool's HITL approval widget.

    Each renderer maps a tool name to a `(widget_class, data)` pair that
    controls what the user sees in the approval box. Tools not registered
    in `_RENDERER_REGISTRY` fall through to the default, which dumps all
    args as `key: value` lines via `GenericApprovalWidget`.
    """

    @staticmethod
    def get_approval_widget(
        tool_args: dict[str, Any],
    ) -> tuple[type[ToolApprovalWidget], dict[str, Any]]:
        """Get the approval widget class and data for this tool.

        Args:
            tool_args: The tool arguments from action_request

        Returns:
            Tuple of (widget_class, data_dict)
        """
        return GenericApprovalWidget, tool_args


class WriteFileRenderer(ToolRenderer):
    """Renderer for write_file tool - shows full file content."""

    @staticmethod
    def get_approval_widget(  # noqa: D102  # Protocol method — docstring on base class
        tool_args: dict[str, Any],
    ) -> tuple[type[ToolApprovalWidget], dict[str, Any]]:
        # Extract file extension for syntax highlighting
        file_path = tool_args.get("file_path", "")
        content = tool_args.get("content", "")

        # Get file extension
        file_extension = "text"
        if "." in file_path:
            file_extension = file_path.rsplit(".", 1)[-1]

        physical = resolve_physical_path(file_path, None)
        existed = bool(physical and physical.exists())
        data = {
            "file_path": file_path,
            "content": content,
            "file_extension": file_extension,
            "is_new_file": not existed,
        }
        return WriteFileApprovalWidget, data


class TaskRenderer(ToolRenderer):
    """Renderer for task tool — interrupt description provides full context."""

    @staticmethod
    def get_approval_widget(  # noqa: D102  # Protocol method — docstring on base class
        tool_args: dict[str, Any],  # noqa: ARG004  # Unused; interrupt description already formats task args
    ) -> tuple[type[ToolApprovalWidget], dict[str, Any]]:
        return GenericApprovalWidget, {}


class EditFileRenderer(ToolRenderer):
    """Renderer for edit_file tool - shows unified diff."""

    @staticmethod
    def get_approval_widget(  # noqa: D102  # Protocol method — docstring on base class
        tool_args: dict[str, Any],
    ) -> tuple[type[ToolApprovalWidget], dict[str, Any]]:
        file_path = tool_args.get("file_path", "")
        old_string = tool_args.get("old_string", "")
        new_string = tool_args.get("new_string", "")

        # Generate unified diff
        diff_lines = EditFileRenderer._generate_diff(old_string, new_string)

        data = {
            "file_path": file_path,
            "diff_lines": diff_lines,
            "old_string": old_string,
            "new_string": new_string,
        }
        return EditFileApprovalWidget, data

    @staticmethod
    def _generate_diff(old_string: str, new_string: str) -> list[str]:
        """Generate unified diff lines from old and new strings.

        Returns:
            List of diff lines without the file headers.
        """
        if not old_string and not new_string:
            return []

        old_lines = old_string.split("\n") if old_string else []
        new_lines = new_string.split("\n") if new_string else []

        # Generate unified diff
        diff = difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile="before",
            tofile="after",
            lineterm="",
            n=3,  # Context lines
        )

        # Skip the first two header lines (--- and +++)
        diff_list = list(diff)
        return diff_list[2:] if len(diff_list) > 2 else diff_list  # noqa: PLR2004  # Column count threshold


class DeleteFileRenderer(ToolRenderer):
    """Renderer for delete_file — shows path and a short preview of removed content."""

    @staticmethod
    def get_approval_widget(  # noqa: D102  # Protocol method — docstring on base class
        tool_args: dict[str, Any],
    ) -> tuple[type[ToolApprovalWidget], dict[str, Any]]:
        file_path = tool_args.get("file_path", "") or tool_args.get("path", "")
        content = ""
        physical = resolve_physical_path(str(file_path), None)
        if physical and physical.is_file():
            try:
                content = physical.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                content = ""
        lines = content.splitlines() if content else []
        return DeleteFileApprovalWidget, {
            "file_path": file_path,
            "preview_lines": lines[:TOOL_APPROVAL_PREVIEW_LINES],
            "total_lines": len(lines),
        }


_RENDERER_REGISTRY: dict[str, type[ToolRenderer]] = {
    "task": TaskRenderer,
    "write_file": WriteFileRenderer,
    "edit_file": EditFileRenderer,
    "delete_file": DeleteFileRenderer,
}
"""Registry mapping tool names to renderers

Note: bash/shell/execute use minimal approval (no renderer) — see
ApprovalMenu._MINIMAL_TOOLS
"""


def get_renderer(tool_name: str) -> ToolRenderer:
    """Get the renderer for a tool by name.

    Args:
        tool_name: The name of the tool

    Returns:
        The appropriate ToolRenderer instance
    """
    renderer_class = _RENDERER_REGISTRY.get(tool_name, ToolRenderer)
    return renderer_class()
