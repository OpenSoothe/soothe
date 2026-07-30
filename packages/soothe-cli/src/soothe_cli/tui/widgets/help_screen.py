"""Help modal for /help — slash commands and keyboard shortcuts."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual.binding import Binding, BindingType
from textual.containers import ScrollableContainer, Vertical
from textual.content import Content
from textual.screen import ModalScreen
from textual.widgets import Static

if TYPE_CHECKING:
    from textual.app import ComposeResult

from soothe_cli.tui import theme
from soothe_cli.tui._version import DOCS_URL
from soothe_cli.tui.command_registry import COMMANDS as SLASH_COMMANDS
from soothe_cli.tui.config import get_glyphs, is_ascii_mode, newline_shortcut

_EXTRA_COMMANDS: tuple[tuple[str, str], ...] = (
    ("/skill:<name>", "Run a discovered skill by name"),
    ("/«subagent»", "Route to a plugin subagent by id (built-ins listed above)"),
)


def build_command_rows() -> list[tuple[str, str]]:
    """Return slash-command rows for the help modal.

    Returns:
        Sorted list of ``(command, description)`` tuples.
    """
    rows: list[tuple[str, str]] = []
    for cmd in SLASH_COMMANDS:
        label = cmd.name
        if cmd.aliases:
            label = f"{cmd.name} ({', '.join(cmd.aliases)})"
        rows.append((label, cmd.description))
    rows.extend(_EXTRA_COMMANDS)
    rows.sort(key=lambda row: row[0].lower())
    return rows


def build_keyboard_shortcut_rows() -> list[tuple[str, str]]:
    """Return keyboard shortcut rows for the TUI help modal.

    Returns:
        Ordered list of ``(shortcut, description)`` tuples.
    """
    newline = newline_shortcut()
    return [
        ("Enter", "Submit message"),
        (
            f"{newline}, Shift+Enter, Alt+Enter, Ctrl+Enter",
            "Insert newline in the chat input",
        ),
        ("Esc", "Dismiss modal, plan overlay, or autocomplete"),
        ("Ctrl+D", "Type exit, quit, or /quit to exit the TUI"),
        (
            "Ctrl+C",
            "Clear input or interrupt running agent/shell",
        ),
        ("Ctrl+X", "Open prompt in external editor ($VISUAL/$EDITOR)"),
        ("Ctrl+Y", "Copy selected text to clipboard"),
        ("Ctrl+T", "Toggle plan panel above thinking row"),
        ("Ctrl+O", "Toggle expand/collapse of the most recent skill or tool card"),
        ("Shift+Tab", "Toggle clarification relay mode (Auto/Manual)"),
        ("@filename", "Autocomplete files and inject content"),
        ("/command", "Slash commands (e.g. /help, /clear, /quit)"),
        ("!command", "Run shell commands directly"),
    ]


def _format_section(title: str, rows: list[tuple[str, str]]) -> Content:
    """Format a titled two-column section for the help body.

    Args:
        title: Section heading.
        rows: ``(label, description)`` rows to render.

    Returns:
        Styled ``Content`` for a ``Static`` widget.
    """
    if not rows:
        return Content.from_markup(f"[bold]{title}[/]\n[dim italic]None[/]")
    key_width = max(len(key) for key, _ in rows)
    lines = [f"[bold]{title}[/]", ""]
    for key, desc in rows:
        lines.append(f"  [bold cyan]{key:<{key_width}}[/]  {desc}")
    return Content.from_markup("\n".join(lines))


def build_help_content() -> Content:
    """Build the full scrollable help body.

    Returns:
        Combined help ``Content`` with commands, input modes, shortcuts, and docs link.
    """
    command_section = _format_section("Slash Commands", build_command_rows())
    shortcut_section = _format_section("Keyboard Shortcuts", build_keyboard_shortcut_rows())
    docs_line = Content.assemble(
        ("\n", ""),
        ("Documentation: ", "dim"),
        (DOCS_URL, "dim italic link"),
    )
    return Content.assemble(
        command_section,
        ("\n\n", ""),
        shortcut_section,
        docs_line,
    )


class HelpScreen(ModalScreen[None]):
    """Modal dialog listing slash commands and keyboard shortcuts."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Close", show=False, priority=True),
        Binding("up,k", "scroll_up", "Up", show=False, priority=True),
        Binding("down,j", "scroll_down", "Down", show=False, priority=True),
        Binding("pageup", "page_up", "Page up", show=False, priority=True),
        Binding("pagedown", "page_down", "Page down", show=False, priority=True),
    ]

    CSS = """
    HelpScreen {
        align: center middle;
        background: transparent;
    }

    HelpScreen > Vertical {
        width: 88;
        max-width: 92%;
        height: 85%;
        max-height: 90%;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }

    HelpScreen .help-title {
        text-style: bold;
        color: $primary;
        text-align: center;
        margin-bottom: 1;
    }

    HelpScreen .help-body {
        height: 1fr;
        min-height: 5;
        scrollbar-gutter: stable;
        background: $background;
        padding: 0 1;
    }

    HelpScreen .help-footer {
        height: 1;
        color: $text-muted;
        text-style: italic;
        margin-top: 1;
        text-align: center;
    }
    """

    def compose(self) -> ComposeResult:
        """Compose the help modal layout."""
        glyphs = get_glyphs()
        with Vertical():
            yield Static("Soothe TUI Help", classes="help-title")
            with ScrollableContainer(classes="help-body"):
                yield Static(build_help_content(), id="help-content")
            yield Static(
                f"{glyphs.arrow_up}/{glyphs.arrow_down} scroll  {glyphs.bullet}  Esc close",
                classes="help-footer",
            )

    def on_mount(self) -> None:
        """Apply ASCII border styling and focus the scroll area."""
        if is_ascii_mode():
            container = self.query_one(Vertical)
            colors = theme.get_theme_colors(self)
            container.styles.border = ("ascii", colors.success)
        self.query_one(ScrollableContainer).focus()

    def action_cancel(self) -> None:
        """Dismiss the modal."""
        self.dismiss(None)

    def _scroll(self, *, delta: int) -> None:
        """Scroll the help body by ``delta`` lines."""
        body = self.query_one(ScrollableContainer)
        body.scroll_relative(y=delta, animate=False)

    def action_scroll_up(self) -> None:
        """Scroll the help body up."""
        self._scroll(delta=-1)

    def action_scroll_down(self) -> None:
        """Scroll the help body down."""
        self._scroll(delta=1)

    def action_page_up(self) -> None:
        """Scroll the help body up one page."""
        body = self.query_one(ScrollableContainer)
        self._scroll(delta=-max(1, body.size.height // 2))

    def action_page_down(self) -> None:
        """Scroll the help body down one page."""
        body = self.query_one(ScrollableContainer)
        self._scroll(delta=max(1, body.size.height // 2))
