"""Welcome banner widget for Soothe."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.color import Color as TColor
from textual.content import Content
from textual.style import Style as TStyle
from textual.widgets import Static

if TYPE_CHECKING:
    from textual.events import Click

from soothe_cli.tui import theme
from soothe_cli.tui._version import __version__
from soothe_cli.tui.config import _is_editable_install, get_banner, get_glyphs
from soothe_cli.tui.tips import pick_session_tip
from soothe_cli.tui.widgets._links import open_style_link


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
        padding: 0;
        margin-bottom: 0;
        background: transparent;
    }
    """

    def __init__(
        self,
        loop_id: str | None = None,
        mcp_tool_count: int = 0,
        **kwargs: Any,
    ) -> None:
        """Initialize the welcome banner.

        Args:
            loop_id: Optional StrangeLoop id to display in the banner.
            mcp_tool_count: Number of MCP tools loaded at startup.
            **kwargs: Additional arguments passed to parent.
        """
        # Avoid collision with Widget._thread_id (Textual internal int)
        self._cli_loop_id: str | None = loop_id
        self._mcp_tool_count = mcp_tool_count
        self._failed = False
        self._failure_error: str = ""
        self._tip: str = pick_session_tip()
        self._update_latest: str | None = None
        """PyPI version string when an update is available; drives banner line only."""

        super().__init__(self._build_banner(), **kwargs)

    @property
    def session_tip(self) -> str:
        """Tip chosen for this session (shown in the status bar when ready)."""
        return self._tip

    def update_loop_id(self, loop_id: str) -> None:
        """Update the displayed loop ID and re-render the banner.

        Args:
            loop_id: The new loop id to display.
        """
        self._cli_loop_id = loop_id
        self.update(self._build_banner())

    def set_connected(self, mcp_tool_count: int = 0) -> None:
        """Refresh the banner after the daemon session is ready.

        Args:
            mcp_tool_count: Number of MCP tools loaded during connection.
        """
        self._failed = False
        self._mcp_tool_count = mcp_tool_count
        self.update(self._build_banner())

    def set_failed(self, error: str) -> None:
        """Transition from "connecting" to a persistent failure state.

        Args:
            error: Error message describing the server startup failure.
        """
        self._failed = True
        self._failure_error = error
        self.update(self._build_banner())

    def set_update_notice(self, latest: str | None) -> None:
        """Show or hide the \"update available\" line in the welcome area.

        Args:
            latest: Newer version from PyPI, or ``None`` to remove the line.
        """
        cleaned = str(latest).strip() if latest else ""
        self._update_latest = cleaned or None
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

        banner = get_banner().rstrip("\n")
        primary_style: str | TStyle = (
            "bold" if ansi else TStyle(foreground=TColor.parse(colors.primary), bold=True)
        )
        parts.append((banner + "\n", primary_style))

        metadata = self._build_metadata_line(colors=colors, ansi=ansi)
        if metadata is not None:
            parts.append(metadata)

        # For ANSI theme, use "bold" (terminal foreground) instead of hex
        success_color: str = "bold green" if ansi else colors.success

        if self._mcp_tool_count > 0:
            parts.append((f"{get_glyphs().checkmark} ", success_color))
            label = "MCP tool" if self._mcp_tool_count == 1 else "MCP tools"
            parts.append(f"Loaded {self._mcp_tool_count} {label}\n")

        if self._failed:
            parts.append(build_failure_footer(self._failure_error))
        return Content.assemble(*parts)

    def _build_metadata_line(self, *, colors: theme.ThemeColors, ansi: bool) -> Content | None:
        """Build the single metadata row: loop id plus version or update notice."""
        segments: list[str | tuple[str, str | TStyle]] = []
        dim_style: str | TStyle = "dim"

        if self._cli_loop_id:
            segments.append((f"Loop: {self._cli_loop_id}", dim_style))

        if self._update_latest and not self._failed:
            from soothe_cli.tui.update_check import upgrade_command

            cmd = upgrade_command()
            update_text = (
                f"Update available: v{self._update_latest} (current: v{__version__}). "
                f"Run: {cmd}  — or /auto-update"
            )
            update_style: str | TStyle = "yellow" if ansi else colors.warning
            if segments:
                segments.append(("  ", dim_style))
            segments.append((update_text, update_style))
        elif not self._failed:
            version_tag = f"v{__version__}"
            if _is_editable_install():
                version_tag += " (local)"
            version_style: str | TStyle = (
                "bold"
                if ansi
                else TStyle(foreground=TColor.parse(colors.tool), bold=True)
                if _is_editable_install()
                else dim_style
            )
            if segments:
                segments.append(("  ", dim_style))
            segments.append((version_tag, version_style))

        if not segments:
            return None
        segments.append("\n")
        return Content.assemble(*segments)


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
