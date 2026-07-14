"""Interactive model-router profile selector for /model-router."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

if TYPE_CHECKING:
    from textual.app import ComposeResult

from soothe_cli.tui import theme
from soothe_cli.tui.config import get_glyphs, is_ascii_mode


class RouterProfileSelectorScreen(ModalScreen[str | None]):
    """Modal list of configured router profile names.

    Returns the selected profile name, ``"--clear"`` to drop the override,
    or ``None`` on cancel.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    CSS = """
    RouterProfileSelectorScreen {
        align: center middle;
        background: transparent;
    }

    RouterProfileSelectorScreen > Vertical {
        width: 56;
        max-width: 90%;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }

    RouterProfileSelectorScreen .router-profile-title {
        text-style: bold;
        color: $primary;
        text-align: center;
        margin-bottom: 1;
    }

    RouterProfileSelectorScreen OptionList {
        height: auto;
        max-height: 16;
        background: $background;
    }

    RouterProfileSelectorScreen .router-profile-help {
        height: 1;
        color: $text-muted;
        text-style: italic;
        margin-top: 1;
        text-align: center;
    }
    """

    def __init__(
        self,
        profiles: list[str],
        *,
        active_default: str | None,
        current_override: str | None,
    ) -> None:
        """Initialize the selector.

        Args:
            profiles: Configured profile names.
            active_default: Process ``active_router_profile`` from daemon.
            current_override: Loop override, if any.
        """
        super().__init__()
        self._profiles = list(profiles)
        self._active_default = active_default
        self._current_override = current_override

    def compose(self) -> ComposeResult:
        """Compose the selector UI."""
        glyphs = get_glyphs()
        options: list[Option] = []
        highlight_index = 0
        effective = self._current_override or self._active_default

        for i, name in enumerate(self._profiles):
            labels: list[str] = [name]
            if name == self._active_default:
                labels.append("config default")
            if name == self._current_override:
                labels.append("this loop")
            elif name == effective and self._current_override is None:
                labels.append("current")
            option_label = name if len(labels) == 1 else f"{name} ({', '.join(labels[1:])})"
            options.append(Option(option_label, id=name))
            if name == effective:
                highlight_index = i

        options.append(Option("Clear loop override (use config default)", id="--clear"))

        with Vertical():
            yield Static("Select Model Router", classes="router-profile-title")
            option_list = OptionList(*options, id="router-profile-options")
            option_list.highlighted = highlight_index
            yield option_list
            help_text = (
                f"{glyphs.arrow_up}/{glyphs.arrow_down} move {glyphs.bullet} "
                f"Enter select {glyphs.bullet} Esc cancel"
            )
            yield Static(help_text, classes="router-profile-help")

    def on_mount(self) -> None:
        """Apply ASCII border when needed."""
        if is_ascii_mode():
            container = self.query_one(Vertical)
            colors = theme.get_theme_colors(self)
            container.styles.border = ("ascii", colors.success)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Return the selected profile id."""
        opt_id = event.option.id
        if isinstance(opt_id, str):
            self.dismiss(opt_id)
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        """Dismiss without changing the override."""
        self.dismiss(None)
