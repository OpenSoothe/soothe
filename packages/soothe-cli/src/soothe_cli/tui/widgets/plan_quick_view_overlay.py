"""In-flow plan panel above the thinking row (Ctrl+t quick view)."""

from __future__ import annotations

import logging
from contextlib import suppress
from typing import TYPE_CHECKING, Any

from textual.containers import Vertical, VerticalScroll
from textual.content import Content
from textual.widgets import Static

from soothe_cli.display import theme
from soothe_cli.display.card import (
    _card_body_gutter,
    _card_prefix_width,
)
from soothe_cli.display.preview_limits import PLAN_QUICK_VIEW_STEP_LINE_MAX_CHARS
from soothe_cli.display.tool_display import display_width, truncate_to_width
from soothe_cli.runtime.presentation.id_format import compact_id_suffix
from soothe_cli.settings import get_glyphs
from soothe_cli.tui.widgets.messages._helpers import _RUNNING_SPINNER_INTERVAL_SECONDS

if TYPE_CHECKING:
    from textual.app import ComposeResult
    from textual.timer import Timer

    from soothe_cli.tui.widgets.messages.cognition_goal_tree import CognitionGoalTreeMessage

logger = logging.getLogger(__name__)


def _plan_quick_view_title(
    loop_id: str | None,
    *,
    intake: str | None = None,
    elapsed: str | None = None,
    tokens: str | None = None,
) -> str:
    """Compose the panel title: `Orchestrating [8d26] · complex · 37s · ↑1.2K ↓345`."""
    title = "Orchestrating"
    short_id = compact_id_suffix(loop_id or "")
    if short_id:
        title = f"{title} [{short_id}]"
    label = (intake or "").strip().lower()
    if label:
        title = f"{title} · {label}"
    if elapsed:
        title = f"{title} · {elapsed}"
    if tokens:
        title = f"{title} · {tokens}"
    return title


def _plan_quick_view_header(
    loop_id: str | None,
    *,
    prefix: Content | None = None,
    intake: str | None = None,
    show_enter_hint: bool = False,
    elapsed: str | None = None,
    tokens: str | None = None,
    max_cols: int | None = None,
) -> Content:
    """Build the quick-view title row: status glyph, bold title, dim hints.

    The title carries everything that identifies the running goal — short loop
    id, intake complexity, and live elapsed — so the panel needs no separate
    goal line. It is rendered with the same `SECONDARY_TEXT_STYLE` dim style
    used by the welcome-area Loop ID, then bolded via `bold dim` so the title
    stands out while staying de-emphasized. `prefix` is the goal lifecycle
    glyph from the live goal tree.

    `max_cols` truncates the whole header to one line so it never wraps.
    Hints are dropped first (right-to-left) to preserve the title; if even the
    title exceeds the budget it is ellipsized.
    """
    dim_style = theme.SECONDARY_TEXT_STYLE
    title = _plan_quick_view_title(loop_id, intake=intake, elapsed=elapsed, tokens=tokens)
    hints: list[str] = []
    if show_enter_hint:
        hints.append("Enter runs queued goal")
    hints.append("Ctrl+t to close")
    hint_str = f"  ·  {'  ·  '.join(hints)}"

    if max_cols is not None and max_cols > 0:
        budget = max_cols - (display_width(prefix.plain) if prefix is not None else 0)
        # Drop hints right-to-left until the title + remaining hints fit.
        while hints and display_width(title) + display_width(hint_str) > budget:
            hints.pop()
            hint_str = f"  ·  {'  ·  '.join(hints)}" if hints else ""
        # If still too long (title alone exceeds budget), ellipsize the title.
        if display_width(title) > budget:
            title = truncate_to_width(title, max(0, budget))
            hint_str = ""

    parts: list[object] = []
    if prefix is not None:
        parts.append(prefix)
    parts.append(Content.styled(title, f"bold {dim_style}"))
    if hint_str:
        parts.append(Content.styled(hint_str, dim_style))
    return Content.assemble(*parts)


def get_live_goal_tree(app: Any) -> CognitionGoalTreeMessage | None:
    """Return the active goal tree widget from the UI adapter, if any."""
    adapter = getattr(app, "_ui_adapter", None)
    if adapter is None:
        return None
    tree = getattr(adapter, "_goal_tree_message", None)
    return tree


def _goal_tree_running_live_stats(
    adapter: Any,
) -> dict[str, tuple[int, float | None, int, int]]:
    """Collect live tool counts, start times, and token counts from running step cards."""
    stats: dict[str, tuple[int, float | None, int, int]] = {}
    for sid, card in getattr(adapter, "_current_step_messages", {}).items():
        if card._status != "running":
            continue
        idx = card._build_row_index()
        stats[sid] = (
            idx.main_tool_count,
            card._start_time,
            card._input_tokens,
            card._output_tokens,
        )
    return stats


class PlanQuickViewOverlay(Vertical):
    """In-flow plan panel above the thinking row and chat input.

    Auto-shows while a goal is executing (`_loop_executing()`) when the
    preferred visibility is on (`CLIConfig.plan_panel_default_visible`,
    default False). Auto-hides once the loop reaches a terminal footer
    (`set_loop_finished` / `set_interrupted`). Toggle with `Ctrl+t`.
    Mounted as a Screen sibling between `#chat` and
    `#bottom-app-container` so expanding it shrinks the transcript
    instead of floating over the sticky bottom chrome. Snapshots in-memory
    goal tree state on the UI adapter (not mounted in the main message list).
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
        overflow: hidden;
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

    def __init__(self, *, default_visible: bool = False, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._preferred_visible: bool = default_visible
        # True when the user explicitly opened the panel (Ctrl+t). Suppresses
        # auto-hide-on-completion so a user can view a finished plan; cleared
        # when the user closes it or a new executing goal appears.
        self._user_pinned: bool = False
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
        # User-initiated open: pin so auto-hide-on-completion is suppressed
        # until the user closes it or a new executing goal appears.
        self._user_pinned = True
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
            self._user_pinned = False
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
        """Sync visibility from the live goal tree and repaint when expanded.

        Lifecycle rules (preferred visibility on, the default):
        - No live goal tree → hide.
        - Executing goal (loop open, no terminal footer) → auto-expand.
        - Completed/interrupted goal (terminal footer visible) → auto-hide,
        unless the user pinned the panel open with Ctrl+t.
        """
        tree = get_live_goal_tree(self.app)
        if tree is None:
            if self.is_expanded:
                self.collapse()
            return
        executing = tree._loop_executing()
        if executing:
            # New executing goal cancels any stale user pin from a prior plan.
            self._user_pinned = False
        if self._preferred_visible and executing and not self._user_pinned:
            if not self.is_expanded:
                self.expand()
                return
        elif not executing and not self._user_pinned:
            # Goal finished (success/interrupted) — auto-hide. ``collapse``
            # (forget_preference=False) keeps the refresh timer running so the
            # panel re-shows when the next executing goal appears.
            if self.is_expanded:
                self.collapse()
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
            prefix: Content | None = None
            intake: str | None = None
            tokens: str | None = None
            with suppress(Exception):
                elapsed = tree.loop_elapsed_label()
            with suppress(Exception):
                prefix = tree.plan_panel_prefix_content()
                intake = tree.intake_label()
            with suppress(Exception):
                tokens = tree.goal_token_suffix()
            self._header.update(
                _plan_quick_view_header(
                    getattr(self.app, "_lc_loop_id", None),
                    prefix=prefix,
                    intake=intake,
                    show_enter_hint=show_enter_hint,
                    elapsed=elapsed,
                    tokens=tokens,
                    max_cols=self._panel_content_width(),
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
            gutter = _card_body_gutter(get_glyphs().subagent_prefix)
            self._content.update(Content.styled(f"{gutter}(plan view unavailable)", "dim"))

    def _panel_content_width(self, reserved: int = 0) -> int:
        """Columns available inside the overlay chrome, minus `reserved`.

        Expanded chrome takes the left tall border (1) plus horizontal
        padding (2).
        """
        overlay_padding = 3
        width = self.size.width if self.size.width else 0
        return max(PLAN_QUICK_VIEW_STEP_LINE_MAX_CHARS, width - overlay_padding - reserved)

    def _plan_quick_view_line_width(self) -> int:
        """Available columns for one plan step row inside the overlay."""
        # Step rows sit under the title row's subagent glyph; the body gutter
        # pads to that prefix width, so the line-width budget must subtract the
        # same width (not just the raw glyph + 1).
        return self._panel_content_width(_card_prefix_width(get_glyphs().subagent_prefix))
