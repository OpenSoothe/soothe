"""In-flow plan panel above the thinking row (Ctrl+t quick view)."""

from __future__ import annotations

import logging
from contextlib import suppress
from typing import TYPE_CHECKING, Any

from textual.containers import Vertical, VerticalScroll
from textual.content import Content
from textual.widgets import Static

from soothe_cli.runtime.presentation.id_format import abbreviate_compact_id
from soothe_cli.tui import theme
from soothe_cli.tui.config import get_glyphs
from soothe_cli.tui.preview_limits import PLAN_QUICK_VIEW_STEP_LINE_MAX_CHARS
from soothe_cli.tui.widgets.messages._helpers import _RUNNING_SPINNER_INTERVAL_SECONDS

if TYPE_CHECKING:
    from textual.app import ComposeResult
    from textual.timer import Timer

    from soothe_cli.tui.widgets.messages.cognition_goal_tree import CognitionGoalTreeMessage

logger = logging.getLogger(__name__)


def _plan_quick_view_header(
    loop_id: str | None,
    *,
    show_enter_hint: bool = False,
    elapsed: str | None = None,
) -> Content:
    """Build the quick-view header: bold title, optional elapsed, dim hints.

    The title (including the abbreviated loop id) is rendered with the same
    `SECONDARY_TEXT_STYLE` dim style used by the welcome-area Loop ID, then
    bolded via `bold dim` so the title stands out while staying de-emphasized.
    Live loop elapsed (``12s``) sits in the title row while the goal is open.
    """
    dim_style = theme.SECONDARY_TEXT_STYLE
    title = "Orchestrate"
    abbreviated = abbreviate_compact_id(loop_id or "")
    if abbreviated:
        title = f"Orchestrate ({abbreviated})"
    hints: list[str] = []
    if elapsed:
        hints.append(elapsed)
    if show_enter_hint:
        hints.append("Enter runs queued goal")
    hints.append("Ctrl+t to close")
    return Content.assemble(
        Content.styled(title, f"bold {dim_style}"),
        Content.styled(f"  ·  {'  ·  '.join(hints)}", dim_style),
    )


def get_live_goal_tree(app: Any) -> CognitionGoalTreeMessage | None:
    """Return the active goal tree widget from the UI adapter, if any."""
    adapter = getattr(app, "_ui_adapter", None)
    if adapter is None:
        return None
    tree = getattr(adapter, "_goal_tree_message", None)
    return tree


def _goal_tree_running_live_stats(adapter: Any) -> dict[str, tuple[int, float | None]]:
    """Collect live tool counts and start times from running step cards."""
    stats: dict[str, tuple[int, float | None]] = {}
    for sid, card in getattr(adapter, "_current_step_messages", {}).items():
        if card._status != "running":
            continue
        idx = card._build_row_index()
        stats[sid] = (idx.main_tool_count, card._start_time)
    return stats


class PlanQuickViewOverlay(Vertical):
    """In-flow plan panel above the thinking row and chat input.

    Auto-shows when a goal plan is active and preferred visibility is on
    (``CLIConfig.plan_panel_default_visible``, default True). Auto-hides when
    there is no active plan. Toggle with ``Ctrl+t``. Mounted as a Screen
    sibling between ``#chat`` and ``#bottom-app-container`` so expanding it
    shrinks the transcript instead of floating over the sticky bottom chrome.
    Snapshots in-memory goal tree state on the UI adapter (not mounted in the
    main message list).
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
        max-height: 14;
        opacity: 1;
        padding: 0 1;
        margin: 0 1;
        background: transparent;
        border: none;
        border-left: tall $cognition;
    }

    PlanQuickViewOverlay .plan-quick-view-header {
        height: 1;
        width: 1fr;
        color: $text-muted;
        margin: 0;
        padding: 0;
    }

    PlanQuickViewOverlay .plan-quick-view-body {
        height: auto;
        max-height: 12;
        width: 1fr;
        scrollbar-size-vertical: 1;
        scrollbar-color: $foreground-muted 40%;
        scrollbar-background: transparent;
    }

    PlanQuickViewOverlay .plan-quick-view-content {
        height: auto;
        width: 1fr;
        margin: 0;
        padding: 0;
    }
    """

    def __init__(self, *, default_visible: bool = True, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._preferred_visible: bool = default_visible
        self._refresh_timer: Timer | None = None
        self._header: Static | None = None
        self._content: Static | None = None

    def compose(self) -> ComposeResult:
        yield Static(
            _plan_quick_view_header(None),
            classes="plan-quick-view-header",
            id="plan-quick-view-header",
        )
        with VerticalScroll(classes="plan-quick-view-body", id="plan-quick-view-body"):
            yield Static("", classes="plan-quick-view-content", id="plan-quick-view-content")

    def on_mount(self) -> None:
        self._header = self.query_one("#plan-quick-view-header", Static)
        self._content = self.query_one("#plan-quick-view-content", Static)
        self.query_one("#plan-quick-view-body", VerticalScroll).can_focus = False
        self.display = False
        if self._preferred_visible:
            self._start_refresh_timer()
            self.refresh_content()

    @property
    def is_expanded(self) -> bool:
        """Return whether the overlay panel is visible."""
        return self.has_class("-expanded")

    def toggle(self) -> None:
        """Expand or collapse the overlay, updating the preferred visibility."""
        if self.is_expanded:
            self.collapse(forget_preference=True)
            return
        self._preferred_visible = True
        if get_live_goal_tree(self.app) is not None:
            self.expand()
        else:
            self._start_refresh_timer()

    def expand(self) -> None:
        """Show the overlay and start live refresh."""
        self.display = True
        self.add_class("-expanded")
        self._start_refresh_timer()
        self.refresh_content()

    def collapse(self, *, forget_preference: bool = False) -> None:
        """Hide the overlay.

        Args:
            forget_preference: When True (Ctrl+t / Esc), stay hidden until the
                user opts in again. When False (no active plan), keep watching
                so a new plan can auto-show.
        """
        if forget_preference:
            self._preferred_visible = False
        self.remove_class("-expanded")
        self.display = False
        if self._preferred_visible:
            self._start_refresh_timer()
        else:
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
        """Sync visibility from the live goal tree and repaint when expanded."""
        tree = get_live_goal_tree(self.app)
        if tree is None:
            if self.is_expanded:
                self.collapse()
            return
        if self._preferred_visible and not self.is_expanded:
            self.expand()
            return
        if not self.is_expanded or self._content is None:
            return
        if self._header is not None:
            show_enter_hint = False
            can_run_queued = getattr(self.app, "_can_run_queued_goal_now_from_enter", None)
            if callable(can_run_queued):
                with suppress(Exception):
                    show_enter_hint = bool(can_run_queued())
            elapsed: str | None = None
            with suppress(Exception):
                elapsed = tree.loop_elapsed_label()
            self._header.update(
                _plan_quick_view_header(
                    getattr(self.app, "_lc_loop_id", None),
                    show_enter_hint=show_enter_hint,
                    elapsed=elapsed,
                )
            )
        try:
            adapter = getattr(self.app, "_ui_adapter", None)
            if adapter is not None:
                tree.sync_running_live_stats(_goal_tree_running_live_stats(adapter))
            tree.tick_running_spinner()
            max_line_width = self._plan_quick_view_line_width()
            self._content.update(tree.plan_quick_view_content(max_line_width=max_line_width))
        except Exception:  # noqa: BLE001
            logger.debug("Failed to render plan quick view", exc_info=True)
            self._content.update(Content.styled("(plan view unavailable)", "dim"))

    def _plan_quick_view_line_width(self) -> int:
        """Available columns for one plan step row inside the overlay."""
        # Expanded chrome: left tall border (1) + horizontal padding (2).
        overlay_padding = 3
        gutter_len = len(get_glyphs().output_prefix) + 1
        width = self.size.width if self.size.width else 0
        if width > overlay_padding + gutter_len:
            return max(PLAN_QUICK_VIEW_STEP_LINE_MAX_CHARS, width - overlay_padding - gutter_len)
        return PLAN_QUICK_VIEW_STEP_LINE_MAX_CHARS
