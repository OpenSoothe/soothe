"""Welcome banner widget for Soothe."""

from __future__ import annotations

import random
from pathlib import Path
from typing import TYPE_CHECKING, Any

from textual.color import Color as TColor
from textual.content import Content
from textual.style import Style as TStyle
from textual.widgets import Static

if TYPE_CHECKING:
    from textual.events import Click

from soothe_cli.tui import theme
from soothe_cli.tui._version import __version__
from soothe_cli.tui.config import (
    _get_editable_install_path,
    _is_editable_install,
    get_banner,
    get_glyphs,
)
from soothe_cli.tui.widgets._links import open_style_link

_TIPS: list[str] = [
    "Use @ to reference files and / for commands",
    "Try /loops to resume a previous AgentLoop instance",
    "Use /tokens to check context usage",
    "Use /mcp to see your loaded tools and servers",
    "Use /remember to save learnings from this conversation",
    "Use /model to switch models mid-conversation",
    "Press ctrl+x to compose prompts in your external editor",
    "Press ctrl+u to delete to the start of the line in the chat input",
    "Use /skill:<name> to invoke a skill directly",
    "Type /update to check for and install updates",
    "Use /theme to customize the CLI colors and style",
    "Use /skill:skill-creator to build reusable agent skills",
    "Use /auto-update to toggle automatic CLI updates",
]
"""Rotating tips shown under the Loop line when the session is ready.

One is picked per session.
"""


class WelcomeBanner(Static):
    """Welcome banner displayed at startup."""

    # Disable Textual's auto_links to prevent a flicker cycle: Style.__add__
    # calls .copy() for linked styles, generating a fresh random _link_id on
    # each render. This means highlight_link_id never stabilizes, causing an
    # infinite hover-refresh loop.
    auto_links = False

    DEFAULT_CSS = """
    WelcomeBanner {
        height: auto;
        padding: 1;
        margin-bottom: 1;
        background: transparent;
    }
    """

    def __init__(
        self,
        loop_id: str | None = None,
        mcp_tool_count: int = 0,
        workspace_path: str | None = None,
        *,
        connecting: bool = False,
        **kwargs: Any,
    ) -> None:
        """Initialize the welcome banner.

        Args:
            loop_id: Optional AgentLoop id to display in the banner.
            mcp_tool_count: Number of MCP tools loaded at startup.
            workspace_path: Session workspace path shown in the source row.
            connecting: When `True`, show a connecting footer instead of
                the normal ready prompt. Call `set_connected` to transition.
            **kwargs: Additional arguments passed to parent.
        """
        # Avoid collision with Widget._thread_id (Textual internal int)
        self._cli_loop_id: str | None = loop_id
        self._mcp_tool_count = mcp_tool_count
        self._workspace_path = workspace_path
        self._connecting = connecting
        self._failed = False
        self._failure_error: str = ""
        self._tip: str = random.choice(_TIPS)  # noqa: S311

        super().__init__(self._build_banner(), **kwargs)

    def update_loop_id(self, loop_id: str) -> None:
        """Update the displayed loop ID and re-render the banner.

        Args:
            loop_id: The new loop id to display.
        """
        self._cli_loop_id = loop_id
        self.update(self._build_banner())

    def set_connected(self, mcp_tool_count: int = 0) -> None:
        """Transition from "connecting" to "ready" state.

        Args:
            mcp_tool_count: Number of MCP tools loaded during connection.
        """
        self._connecting = False
        self._failed = False
        self._mcp_tool_count = mcp_tool_count
        self.update(self._build_banner())

    def set_failed(self, error: str) -> None:
        """Transition from "connecting" to a persistent failure state.

        Args:
            error: Error message describing the server startup failure.
        """
        self._connecting = False
        self._failed = True
        self._failure_error = error
        self.update(self._build_banner())

    def on_click(self, event: Click) -> None:  # noqa: PLR6301  # Textual event handler
        """Open style-embedded hyperlinks on single click."""
        open_style_link(event)

    def _build_banner(self) -> Content:
        """Build the banner content.

        Returns:
            Content object containing the formatted banner.
        """
        parts: list[str | tuple[str, str | TStyle] | Content] = []
        colors = theme.get_theme_colors(self)
        ansi = self.app.theme == "textual-ansi"

        banner = get_banner()
        primary_style: str | TStyle = (
            "bold" if ansi else TStyle(foreground=TColor.parse(colors.primary), bold=True)
        )

        if not ansi and _is_editable_install():
            # Highlight local-install version tag with tool accent; art stays primary.
            dev_style = TStyle(foreground=TColor.parse(colors.tool), bold=True)
            version_tag = f"v{__version__} (local)"
            idx = banner.rfind(version_tag)
            if idx >= 0:
                parts.extend(
                    [
                        (banner[:idx], primary_style),
                        (version_tag, dev_style),
                        (banner[idx + len(version_tag) :] + "\n", primary_style),
                    ]
                )
            else:
                parts.append((banner + "\n", primary_style))
        else:
            parts.append((banner + "\n", primary_style))

        # For ANSI theme, use "bold" (terminal foreground) instead of hex
        success_color: str = "bold green" if ansi else colors.success

        editable_path = _get_editable_install_path()
        source_path = resolve_source_display_path(
            workspace_path=self._workspace_path,
            editable_path=editable_path,
        )
        if source_path:
            parts.extend([("Source: ", "dim"), (source_path, "dim"), "\n"])

        tip_ready = not self._failed and not self._connecting
        tip_line: str | None = f"{self._tip}\n" if tip_ready else None

        if self._cli_loop_id:
            parts.append((f"Loop: {self._cli_loop_id}\n", "dim"))
            if tip_line is not None:
                parts.append((tip_line, "dim"))
                tip_line = None

        if self._mcp_tool_count > 0:
            parts.append((f"{get_glyphs().checkmark} ", success_color))
            label = "MCP tool" if self._mcp_tool_count == 1 else "MCP tools"
            parts.append(f"Loaded {self._mcp_tool_count} {label}\n")

        if tip_line is not None:
            parts.append((tip_line, "dim"))

        if self._failed:
            parts.append(build_failure_footer(self._failure_error))
        elif self._connecting:
            parts.append(build_connecting_footer())
        return Content.assemble(*parts)


def build_failure_footer(error: str) -> Content:
    """Build a footer shown when the daemon connection failed.

    Args:
        error: Error message describing the failure.

    Returns:
        Content with a persistent failure message.
    """
    colors = theme.get_theme_colors()
    return Content.assemble(
        ("\nCould not connect to daemon: ", f"bold {colors.error}"),
        (error, colors.error),
        ("\n", colors.error),
    )


def build_connecting_footer() -> Content:
    """Build a footer shown while waiting for the daemon session."""
    return Content.styled("\nConnecting to daemon...\n", "dim")


def resolve_source_display_path(
    *, workspace_path: str | None, editable_path: str | None
) -> str | None:
    """Resolve the banner source row path.

    Prefer the session workspace path so the welcome banner and status bar stay
    consistent. Fall back to editable-install metadata for local-dev installs.
    """
    if workspace_path and workspace_path.strip():
        return _format_path_for_display(workspace_path)
    if editable_path and editable_path.strip():
        return editable_path
    return None


def _format_path_for_display(path: str) -> str:
    """Format a path with `~` contraction when under the user home."""
    try:
        resolved = Path(path).expanduser().resolve()
        home = Path.home()
        if resolved == home:
            return "~"
        if resolved.is_relative_to(home):
            return "~/" + resolved.relative_to(home).as_posix()
        return str(resolved)
    except (RuntimeError, OSError, ValueError):
        return path
