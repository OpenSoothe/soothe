"""Sticky overlay above chat input showing the live goal/plan aggregate."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from textual.containers import Vertical, VerticalScroll
from textual.content import Content
from textual.widgets import Static

from soothe_cli.tui.widgets.messages._helpers import _RUNNING_SPINNER_INTERVAL_SECONDS

if TYPE_CHECKING:
    from textual.app import ComposeResult
    from textual.timer import Timer

    from soothe_cli.tui.widgets.messages.cognition_goal_tree import CognitionGoalTreeMessage

logger = logging.getLogger(__name__)


def get_live_goal_tree(app: Any) -> CognitionGoalTreeMessage | None:
    """Return the active goal tree widget from the UI adapter, if any."""
    adapter = getattr(app, "_ui_adapter", None)
    if adapter is None:
        return None
    tree = getattr(adapter, "_goal_tree_message", None)
    return tree


class PlanQuickViewOverlay(Vertical):
    """Floating quick-view panel of the full plan above the chat prompt.

    Toggle with ``Ctrl+t``. Snapshots in-memory goal tree state on the UI adapter
    (not mounted in the main message list).
    """

    DEFAULT_CSS = """
    PlanQuickViewOverlay {
        height: auto;
        max-height: 0;
        overflow: hidden;
        opacity: 0;
        padding: 0;
        margin: 0;
        border: none;
        background: transparent;
    }

    PlanQuickViewOverlay.-expanded {
        layer: plan-quick-view;
        max-height: 18;
        opacity: 1;
        padding: 0 1;
        margin: 0 0 1 0;
        background: $surface;
        border: solid $cognition;
    }

    PlanQuickViewOverlay .plan-quick-view-header {
        height: 1;
        color: $cognition;
        text-style: bold;
        margin: 0 0 1 0;
    }

    PlanQuickViewOverlay .plan-quick-view-body {
        height: auto;
        max-height: 14;
        width: 1fr;
    }

    PlanQuickViewOverlay .plan-quick-view-content {
        height: auto;
        width: 1fr;
        margin: 0;
        padding: 0;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._refresh_timer: Timer | None = None
        self._content: Static | None = None

    def compose(self) -> ComposeResult:
        yield Static(
            "Plan  ·  Ctrl+t to close",
            classes="plan-quick-view-header",
            id="plan-quick-view-header",
        )
        with VerticalScroll(classes="plan-quick-view-body", id="plan-quick-view-body"):
            yield Static("", classes="plan-quick-view-content", id="plan-quick-view-content")

    def on_mount(self) -> None:
        self._content = self.query_one("#plan-quick-view-content", Static)
        self.display = False

    @property
    def is_expanded(self) -> bool:
        """Return whether the overlay panel is visible."""
        return self.has_class("-expanded")

    def toggle(self) -> None:
        """Expand or collapse the overlay."""
        if self.is_expanded:
            self.collapse()
        else:
            self.expand()

    def expand(self) -> None:
        """Show the overlay and start live refresh."""
        self.display = True
        self.add_class("-expanded")
        self.refresh_content()
        self._start_refresh_timer()

    def collapse(self) -> None:
        """Hide the overlay and stop live refresh."""
        self.remove_class("-expanded")
        self.display = False
        self._stop_refresh_timer()

    def _start_refresh_timer(self) -> None:
        self._stop_refresh_timer()
        self._refresh_timer = self.set_interval(
            _RUNNING_SPINNER_INTERVAL_SECONDS,
            self.refresh_content,
        )

    def _stop_refresh_timer(self) -> None:
        if self._refresh_timer is not None:
            self._refresh_timer.stop()
            self._refresh_timer = None

    def refresh_content(self) -> None:
        """Repaint the plan snapshot from the live goal tree."""
        if not self.is_expanded or self._content is None:
            return
        tree = get_live_goal_tree(self.app)
        if tree is None:
            self._content.update(Content.styled("No active plan.", "dim"))
            return
        try:
            tree.tick_running_spinner()
            self._content.update(tree.plan_quick_view_content())
        except Exception:  # noqa: BLE001
            logger.debug("Failed to render plan quick view", exc_info=True)
            self._content.update(Content.styled("(plan view unavailable)", "dim"))
