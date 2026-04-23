"""Welcome banner widget for Soothe."""

from __future__ import annotations

import random
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
"""Rotating tips shown in the welcome footer.

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
    }
    """

    def __init__(
        self,
        thread_id: str | None = None,
        mcp_tool_count: int = 0,
        *,
        connecting: bool = False,
        resuming: bool = False,
        local_server: bool = False,
        **kwargs: Any,
    ) -> None:
        """Initialize the welcome banner.

        Args:
            thread_id: Optional loop ID to display in the banner (mapped from loop_id).
            mcp_tool_count: Number of MCP tools loaded at startup.
            connecting: When `True`, show a "Connecting..." footer instead of
                the normal ready prompt. Call `set_connected` to transition.
            resuming: When `True`, the connecting footer says "Resuming..."
                instead of any `'Connecting...'` variant.
            local_server: When `True`, the connecting footer qualifies the
                server as "local" (i.e. a server process managed by the
                CLI).

                Ignored when `resuming` is `True`.
            **kwargs: Additional arguments passed to parent.
        """
        # Avoid collision with Widget._thread_id (Textual internal int)
        # Note: Parameter named thread_id for backward compatibility with build_stream_config
        # which maps loop_id to thread_id in langgraph's configurable dict
        self._cli_loop_id: str | None = thread_id
        self._mcp_tool_count = mcp_tool_count
        self._connecting = connecting
        self._resuming = resuming
        self._local_server = local_server
        self._failed = False
        self._failure_error: str = ""
        self._tip: str = random.choice(_TIPS)  # noqa: S311

        super().__init__(self._build_banner(), **kwargs)

    def update_loop_id(self, loop_id: str) -> None:
        """Update the displayed loop ID and re-render the banner.

        Args:
            loop_id: The new loop ID to display (mapped to thread_id internally).
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
        if editable_path:
            parts.extend([("Source: ", "dim"), (editable_path, "dim"), "\n"])

        if self._cli_loop_id:
            parts.append((f"Loop: {self._cli_loop_id}\n", "dim"))

        if self._mcp_tool_count > 0:
            parts.append((f"{get_glyphs().checkmark} ", success_color))
            label = "MCP tool" if self._mcp_tool_count == 1 else "MCP tools"
            parts.append(f"Loaded {self._mcp_tool_count} {label}\n")

        if self._failed:
            parts.append(build_failure_footer(self._failure_error))
        elif self._connecting:
            parts.append(
                build_connecting_footer(
                    resuming=self._resuming,
                    local_server=self._local_server,
                )
            )
        else:
            ready_color = "bold" if ansi else colors.primary
            parts.append(build_welcome_footer(primary_color=ready_color, tip=self._tip))
        return Content.assemble(*parts)


def build_failure_footer(error: str) -> Content:
    """Build a footer shown when the server failed to start.

    Args:
        error: Error message describing the failure.

    Returns:
        Content with a persistent failure message.
    """
    colors = theme.get_theme_colors()
    return Content.assemble(
        ("\nServer failed to start: ", f"bold {colors.error}"),
        (error, colors.error),
        ("\n", colors.error),
    )


def build_connecting_footer(*, resuming: bool = False, local_server: bool = False) -> Content:
    """Build a footer shown while waiting for the server to connect.

    Args:
        resuming: Show `'Resuming...'` instead of any `'Connecting...'` variant.
        local_server: Qualify the server as "local" in the connecting message.

            Ignored when `resuming` is `True`.

    Returns:
        Content with a connecting status message.
    """
    if resuming:
        text = "\nResuming...\n"
    elif local_server:
        text = "\nConnecting to local server...\n"
    else:
        text = "\nConnecting to server...\n"
    return Content.styled(text, "dim")


def build_welcome_footer(*, primary_color: str = theme.PRIMARY, tip: str | None = None) -> Content:
    """Build the footer shown at the bottom of the welcome banner.

    Includes a tip to help users discover features.

    Args:
        primary_color: Color string for the ready prompt.

            Defaults to the module-level ANSI `PRIMARY` constant; widget callers
            should pass the active theme's hex value.
        tip: Tip text to display. When `None`, a random tip is selected.

            Pass an explicit value to keep the tip stable across re-renders.

    Returns:
        Content with the ready prompt and a tip.
    """
    if tip is None:
        tip = random.choice(_TIPS)  # noqa: S311
    return Content.assemble(
        ("\nReady to unleash your thinking?\n", primary_color),
        (f"Tip: {tip}", "dim italic"),
    )
