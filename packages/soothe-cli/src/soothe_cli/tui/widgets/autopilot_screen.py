"""RFC-204: Autopilot Dashboard Screen for Textual TUI.

A full-screen, read-only dashboard that replaces the chat TUI when
viewing autopilot state. Pushed as a modal screen from the main app
via the `/status` slash command.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from soothe_sdk.client.config import SOOTHE_HOME
from textual.binding import Binding
from textual.screen import Screen

from soothe_cli.tui.widgets.autopilot_dashboard import AutopilotDashboard

if TYPE_CHECKING:
    from textual.app import ComposeResult


class AutopilotScreen(Screen):
    """Full-screen autopilot dashboard.

    Pushed as a modal screen from the main TUI.
    Press Q or Escape to return to the chat TUI.
    """

    BINDINGS: ClassVar[list] = [
        Binding("q", "quit", "Close", show=True),
    ]

    def __init__(self, *, is_narrow: bool = False) -> None:
        """Initialize screen.

        Args:
            is_narrow: Whether to use vertical layout.
        """
        super().__init__()
        self._is_narrow = is_narrow
        self._dashboard = AutopilotDashboard(is_narrow=is_narrow)

    def compose(self) -> ComposeResult:
        """Build the screen with the dashboard."""
        yield self._dashboard

    def on_show(self) -> None:
        """Refresh goals when screen is shown."""
        self._dashboard.update_goals(self._load_goals())

    def _load_goals(self) -> list[dict]:
        """Parse goals from SOOTHE_HOME/autopilot/ files.

        Returns:
            List of goal info dicts.
        """
        from pathlib import Path

        from soothe_cli.tui.widgets.autopilot_dashboard import _parse_autopilot_files

        autopilot_dir = Path(SOOTHE_HOME) / "autopilot"
        if not autopilot_dir.exists():
            return []
        return _parse_autopilot_files(autopilot_dir)
