"""Special tool behaviors for custom tree rendering (RFC-0019).

This module provides a registry for custom tool rendering behaviors,
allowing complex tools to override the default two-level tree structure
with multi-step progress displays.
"""

from __future__ import annotations

from typing import Any, Protocol


class ToolBehavior(Protocol):
    """Protocol for custom tool rendering behaviors.

    Tools can implement custom behaviors to show multi-step progress
    instead of the default start/complete tree.
    """

    def render_start(self, event: dict[str, Any]) -> str:
        """Render tool start event.

        Args:
            event: Tool start event data.

        Returns:
            Rendered string for the parent node.
        """
        ...

    def render_progress(self, event: dict[str, Any]) -> str | None:
        """Render intermediate progress event.

        Args:
            event: Progress event data.

        Returns:
            Rendered string for intermediate node, or None to skip.
        """
        ...

    def render_complete(self, event: dict[str, Any]) -> str:
        """Render tool complete event.

        Args:
            event: Complete event data.

        Returns:
            Rendered string for the final child node.
        """
        ...


class DefaultToolBehavior:
    """Default two-level tree behavior for most tools."""

    def render_start(self, event: dict[str, Any]) -> str:
        """Render tool start with name and args."""
        from soothe.tools.display_names import get_tool_display_name
        from soothe.ux.shared.message_processing import format_tool_call_args

        tool_name = event.get("tool", event.get("name", "tool"))
        args = event.get("args", {})
        display_name = get_tool_display_name(tool_name)
        args_str = format_tool_call_args(tool_name, {"args": args}) if args else ""

        return f"⚙ {display_name}{args_str}"

    def render_progress(self, event: dict[str, Any]) -> str | None:  # noqa: ARG002
        """No intermediate progress for default tools."""
        return None

    def render_complete(self, event: dict[str, Any]) -> str:
        """Render tool result summary."""
        result = event.get("result", "")
        success = event.get("success", True)
        duration_ms = event.get("duration_ms", 0)

        from soothe.ux.shared.message_processing import extract_tool_brief

        tool_name = event.get("tool", event.get("name", "tool"))
        brief = extract_tool_brief(tool_name, result, max_length=60)

        if duration_ms > 0:
            duration_s = duration_ms / 1000
            brief += f" ({duration_s:.1f}s)"

        icon = "✓" if success else "✗"
        return f"└ {icon} {brief}"


class BrowserToolBehavior:
    """Multi-step behavior for browser subagent."""

    def render_start(self, event: dict[str, Any]) -> str:
        """Render browser start with goal."""
        from soothe.tools.display_names import get_tool_display_name

        tool_name = event.get("tool", "browser")
        display_name = get_tool_display_name(tool_name)
        goal = str(event.get("goal", event.get("args", {}).get("goal", "")))[:40]

        return f'⚙ {display_name}("{goal}")'

    def render_progress(self, event: dict[str, Any]) -> str | None:
        """Render browser step progress."""
        event_type = event.get("type", "")

        if "browser.step" in event_type:
            step = event.get("step", "?")
            action = str(event.get("action", ""))[:30]
            url = str(event.get("url", ""))[:25]

            parts = [f"├ Step {step}"]
            if action:
                parts.append(f": {action}")
            if url:
                parts.append(f" @ {url}")

            return "".join(parts)

        return None

    def render_complete(self, event: dict[str, Any]) -> str:
        """Render browser completion."""
        duration_ms = event.get("duration_ms", 0)
        pages = event.get("pages_visited", 0)

        summary = "Completed"
        if pages > 0:
            summary += f" ({pages} pages)"
        if duration_ms > 0:
            duration_s = duration_ms / 1000
            summary += f" in {duration_s:.1f}s"

        return f"└ ✓ {summary}"


class FileOperationBehavior:
    """Behavior for file read/write operations."""

    def render_start(self, event: dict[str, Any]) -> str:
        """Render file operation start."""
        from soothe.tools.display_names import get_tool_display_name

        tool_name = event.get("tool", event.get("name", "file"))
        display_name = get_tool_display_name(tool_name)
        path = str(event.get("path", event.get("args", {}).get("path", "")))[:50]

        return f'⚙ {display_name}("{path}")'

    def render_progress(self, event: dict[str, Any]) -> str | None:  # noqa: ARG002
        """No intermediate progress for file ops."""
        return None

    def render_complete(self, event: dict[str, Any]) -> str:
        """Render file operation result."""
        result = event.get("result", "")
        success = event.get("success", True)

        # Try to extract lines/size info
        lines = result.count("\n") + 1 if result else 0
        size = len(result) if result else 0

        summary = f"{lines} lines ({size / 1024:.1f}kb)" if size > 0 else "Empty file"
        icon = "✓" if success else "✗"

        return f"└ {icon} {summary}"


class ExecutionBehavior:
    """Behavior for command execution tools."""

    def render_start(self, event: dict[str, Any]) -> str:
        """Render command execution start."""
        from soothe.tools.display_names import get_tool_display_name

        tool_name = event.get("tool", event.get("name", "execute"))
        display_name = get_tool_display_name(tool_name)
        cmd = str(event.get("command", event.get("args", {}).get("command", "")))[:40]

        return f'⚙ {display_name}("{cmd}")'

    def render_progress(self, event: dict[str, Any]) -> str | None:  # noqa: ARG002
        """No intermediate progress for execution."""
        return None

    def render_complete(self, event: dict[str, Any]) -> str:
        """Render execution result."""
        success = event.get("success", True)
        exit_code = event.get("exit_code", 0)
        duration_ms = event.get("duration_ms", 0)

        summary = "Success" if success else f"Failed (exit code {exit_code})"

        if duration_ms > 0:
            duration_s = duration_ms / 1000
            summary += f" in {duration_s:.1f}s"

        icon = "✓" if success else "✗"
        return f"└ {icon} {summary}"


# Tool behavior registry
TOOL_BEHAVIORS: dict[str, ToolBehavior] = {
    "browser": BrowserToolBehavior(),
    "read_file": FileOperationBehavior(),
    "write_file": FileOperationBehavior(),
    "edit_file": FileOperationBehavior(),
    "run_command": ExecutionBehavior(),
    "execute": ExecutionBehavior(),
    "run_python": ExecutionBehavior(),
}


def get_tool_behavior(tool_name: str) -> ToolBehavior:
    """Get behavior for a tool, falling back to default.

    Args:
        tool_name: Name of the tool.

    Returns:
        ToolBehavior instance for the tool.
    """
    return TOOL_BEHAVIORS.get(tool_name, DefaultToolBehavior())
