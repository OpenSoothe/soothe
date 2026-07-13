"""Interactive loop selector screen for the /resume command (RFC-503)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, ClassVar, NamedTuple, cast

from rich.cells import cell_len
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.content import Content
from textual.css.query import NoMatches
from textual.fuzzy import Matcher
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Checkbox, Input, Static

if TYPE_CHECKING:
    from collections.abc import Mapping

    from textual.app import ComposeResult
    from textual.events import Click, Key

from soothe_cli.tui import theme
from soothe_cli.tui.config import (
    get_glyphs,
    is_ascii_mode,
)
from soothe_cli.tui.widgets._links import open_style_link

logger = logging.getLogger(__name__)


class _LoopColumnWidthsCache(NamedTuple):
    """Inputs fingerprint for resume-table column width caching."""

    fingerprint: tuple[tuple[str, str | None], ...]
    visible_columns: frozenset[str]
    relative_time: bool
    widths: dict[str, int | None]


_column_widths_cache: _LoopColumnWidthsCache | None = None
"""Module-level cache so repeated `/resume` opens skip column-width computation
when the inputs (loop data + config) haven't changed."""

_LOOP_ID_HEAD_CHARS = 10
_LOOP_ID_TAIL_CHARS = 4
_LOOP_ID_SEPARATOR = "..."
_LOOP_ID_COMPACT_CHARS = _LOOP_ID_HEAD_CHARS + _LOOP_ID_TAIL_CHARS
_COL_LID = _LOOP_ID_COMPACT_CHARS + len(_LOOP_ID_SEPARATOR)
_COL_MESSAGES = 4
_COL_TIMESTAMP = None
_COL_TOPIC = None  # flex column
_MAX_SEARCH_TEXT_LEN = 200
_AUTO_WIDTH_COLUMNS = {"updated_at"}
_COLUMN_ORDER = (
    "topic",
    "updated_at",
    "loop_id",
    "messages",
)
_COLUMN_WIDTHS: dict[str, int | None] = {
    "loop_id": _COL_LID,
    "messages": _COL_MESSAGES,
    "updated_at": _COL_TIMESTAMP,
    "topic": _COL_TOPIC,
}
_COLUMN_LABELS = {
    "loop_id": "LoopID",
    "messages": "Msg",
    "updated_at": "Updated",
    "topic": "Topic",
}
_COLUMN_TOGGLE_LABELS = {
    "loop_id": "Loop ID",
    "messages": "# Messages",
    "updated_at": "Updated At",
    "topic": "Topic",
}
_RIGHT_ALIGNED_COLUMNS: set[str] = {"updated_at", "loop_id"}
_SWITCH_ID_PREFIX = "loop-column-"
_SORT_SWITCH_ID = "loop-sort-toggle"
_RELATIVE_TIME_SWITCH_ID = "loop-relative-time"
_CELL_PADDING_RIGHT = 1

_FormatFns = tuple[
    Callable[[str | None], str],  # format_path
    Callable[[str | None], str],  # format_relative_timestamp
    Callable[[str | None], str],  # format_timestamp
]
"""Cached `(format_path, format_relative_timestamp, format_timestamp)`.

Resolved once on first use via `_get_format_fns()` to avoid the overhead of
a per-call deferred import inside the hot `_format_column_value` loop.
"""

_format_fns_cache: _FormatFns | None = None
"""Cached format functions, populated on first call to `_get_format_fns()`."""


def _get_format_fns() -> _FormatFns:
    """Return cached `(format_path, format_relative_timestamp, format_timestamp)`."""
    global _format_fns_cache  # noqa: PLW0603
    if _format_fns_cache is not None:
        return _format_fns_cache
    from soothe_cli.tui.sessions import (
        format_relative_timestamp,
        format_timestamp,
    )

    # Loops don't have cwd field, so format_path is identity
    def format_path_identity(path: str | None) -> str:
        return path or ""

    _format_fns_cache = (format_path_identity, format_relative_timestamp, format_timestamp)
    return _format_fns_cache


def _apply_column_width(cell: Static, key: str, column_widths: Mapping[str, int | None]) -> None:
    """Apply an explicit width to a table cell when one is configured.

    Args:
        cell: The cell widget to size.
        key: Column key for the cell.
        column_widths: Effective column widths for the current table state.
    """
    width = column_widths.get(key)
    if width is not None:
        cell.styles.width = width
        if key in _AUTO_WIDTH_COLUMNS:
            cell.styles.min_width = width


def _active_sort_key(sort_by_updated: bool) -> str:
    """Return the active timestamp field used for sorting."""
    return "updated_at" if sort_by_updated else "created_at"


def _is_active_loop(loop: dict[str, Any]) -> bool:
    """Return True when a loop is live on the daemon or persisted as running."""
    if loop.get("live"):
        return True
    return str(loop.get("status", "")).strip().lower() == "running"


def _sort_loops(loops: list[dict[str, Any]], *, sort_key: str) -> list[dict[str, Any]]:
    """Sort loops with live/running rows first, then by timestamp descending."""
    active = [loop for loop in loops if _is_active_loop(loop)]
    inactive = [loop for loop in loops if not _is_active_loop(loop)]

    def key_fn(loop: dict[str, Any]) -> str:
        return loop.get(sort_key) or loop.get("created") or ""

    active.sort(key=key_fn, reverse=True)
    inactive.sort(key=key_fn, reverse=True)
    return active + inactive


def _visible_column_keys(columns: dict[str, bool]) -> list[str]:
    """Return visible columns in the on-screen order.

    Args:
        columns: Column visibility settings keyed by column name.

    Returns:
        Visible column keys in display order.
    """
    return [key for key in _COLUMN_ORDER if columns.get(key)]


def _collapse_whitespace(value: str) -> str:
    """Normalize a text value onto a single display line.

    Args:
        value: Raw text to display in a single cell.

    Returns:
        The input text collapsed to a single line.
    """
    return " ".join(value.split())


def _truncate_value(value: str, width: int | None) -> str:
    """Trim text to fit a fixed-width column.

    Args:
        value: Raw cell text.
        width: Maximum column width, or `None` for no truncation.

    Returns:
        The possibly truncated display string.
    """
    if width is None:
        return value

    display = _collapse_whitespace(value)
    if len(display) <= width:
        return display

    glyphs = get_glyphs()
    ellipsis = glyphs.ellipsis
    if width <= len(ellipsis):
        return display[:width]
    return display[: width - len(ellipsis)] + ellipsis


def _abbreviate_loop_id(value: str) -> str:
    """Render loop IDs as ``10-char prefix + ... + 4-char suffix``."""
    text = _collapse_whitespace(value)
    if len(text) <= _COL_LID:
        return text
    return f"{text[:_LOOP_ID_HEAD_CHARS]}{_LOOP_ID_SEPARATOR}{text[-_LOOP_ID_TAIL_CHARS:]}"


def _format_column_value(loop: dict[str, Any], key: str, *, relative_time: bool = False) -> str:
    """Return the display text for one loop column.

    Args:
        loop: Loop metadata dict for the row.
        key: Column key to format.
        relative_time: Use relative timestamps instead of absolute.

    Returns:
        Formatted display text for the column cell.
    """
    format_path, format_relative_ts, format_ts = _get_format_fns()
    fmt = format_relative_ts if relative_time else format_ts

    value: str
    if key == "loop_id":
        compact_id = loop["loop_id"].replace("-", "")
        value = _abbreviate_loop_id(compact_id)
    elif key == "messages":
        raw_count = loop.get("messages")
        value = str(raw_count) if raw_count is not None else "..."
    elif key == "updated_at":
        value = fmt(loop.get("updated") or loop.get("created"))
    elif key == "topic":
        raw_topic = str(loop.get("topic") or loop.get("prompt") or "").strip() or "(no goal)"
        if loop.get("live"):
            value = f"● {raw_topic}"
        elif str(loop.get("status", "")).strip().lower() == "running":
            value = f"◐ {raw_topic}"
        else:
            value = raw_topic
    else:
        value = ""

    return _truncate_value(value, _COLUMN_WIDTHS.get(key))


def _format_header_label(key: str) -> str:
    """Return the rendered header label for a column."""
    return _truncate_value(_COLUMN_LABELS[key], _COLUMN_WIDTHS[key])


def _header_cell_classes(key: str, *, sort_key: str) -> str:
    """Return CSS classes for a header cell.

    Args:
        key: Column key for the header cell.
        sort_key: Currently active sort column.

    Returns:
        Space-delimited classes for the header cell widget.
    """
    classes = f"loop-cell loop-cell-{key}"
    if key == sort_key:
        classes += " loop-cell-sorted"
    return classes


class LoopOption(Horizontal):
    """A clickable loop option in the selector."""

    def __init__(
        self,
        loop: dict[str, Any],
        index: int,
        *,
        columns: dict[str, bool],
        column_widths: Mapping[str, int | None],
        selected: bool,
        current: bool,
        relative_time: bool = False,
        cell_text: dict[tuple[str, str], str] | None = None,
        classes: str = "",
    ) -> None:
        """Initialize a loop option row.

        Args:
            loop: Loop metadata dict for the row.
            index: The index of this option in the filtered list.
            columns: Column visibility settings.
            column_widths: Effective widths for the visible columns.
            selected: Whether the row is highlighted.
            current: Whether the row is the active loop.
            relative_time: Use relative timestamps.
            cell_text: Pre-formatted cell values keyed by `(loop_id, key)`.
            classes: CSS classes for styling.
        """
        super().__init__(classes=classes)
        self.loop = loop
        self.loop_id = loop["loop_id"]
        self.index = index
        self._columns = dict(columns)
        self._column_widths = dict(column_widths)
        self._selected = selected
        self._current = current
        self._relative_time = relative_time
        self._cell_text = cell_text

    class Clicked(Message):
        """Message sent when a loop option is clicked."""

        def __init__(self, loop_id: str, index: int) -> None:
            """Initialize the Clicked message.

            Args:
                loop_id: The loop identifier.
                index: The index of the clicked option.
            """
            super().__init__()
            self.loop_id = loop_id
            self.index = index

    def compose(self) -> ComposeResult:
        """Compose the row cells.

        Yields:
            Static cells for each visible column.
        """
        yield Static(
            self._cursor_text(),
            classes="loop-cell loop-cell-cursor",
            markup=False,
        )
        tid = self.loop_id
        for key in _visible_column_keys(self._columns):
            if self._cell_text is not None and (tid, key) in self._cell_text:
                text = self._cell_text[tid, key]
            else:
                text = _format_column_value(self.loop, key, relative_time=self._relative_time)
            cell = Static(
                text,
                classes=f"loop-cell loop-cell-{key}",
                expand=key == "topic",
                markup=False,
            )
            _apply_column_width(cell, key, self._column_widths)
            yield cell

    def _cursor_text(self) -> str:
        """Return the cursor indicator for the row."""
        return get_glyphs().cursor if self._selected else ""

    def set_selected(self, selected: bool) -> None:
        """Update row selection styling without rebuilding the row.

        Args:
            selected: Whether the row should be highlighted.
        """
        self._selected = selected
        if selected:
            self.add_class("loop-option-selected")
        else:
            self.remove_class("loop-option-selected")

        try:
            cursor = self.query_one(".loop-cell-cursor", Static)
        except NoMatches:
            return
        cursor.update(self._cursor_text())

    def on_click(self, event: Click) -> None:
        """Handle click on this option.

        Args:
            event: The click event.
        """
        event.stop()
        self.post_message(self.Clicked(self.loop_id, self.index))


class LoopSelectorScreen(ModalScreen[str | None]):
    """Modal dialog for browsing and resuming loops.

    Displays recent loops with keyboard navigation, fuzzy search,
    configurable columns, and delete support.

    Returns a `loop_id` string on selection, or `None` on cancel.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("up", "move_up", "Up", show=False, priority=True),
        Binding("k", "move_up", "Up", show=False, priority=True),
        Binding("down", "move_down", "Down", show=False, priority=True),
        Binding("j", "move_down", "Down", show=False, priority=True),
        Binding("pageup", "page_up", "Page up", show=False, priority=True),
        Binding("pagedown", "page_down", "Page down", show=False, priority=True),
        Binding("enter", "select", "Select", show=False, priority=True),
        Binding("s", "toggle_sort", "Toggle sort", show=False, priority=True),
        Binding(
            "r",
            "toggle_relative_time",
            "Toggle relative time",
            show=False,
            priority=True,
        ),
        Binding("escape", "cancel", "Cancel", show=False, priority=True),
    ]

    CSS = """
    LoopSelectorScreen {
        align: center middle;
    }

    LoopSelectorScreen #loop-selector-shell {
        width: 92%;
        max-width: 120;
        height: 78%;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }

    LoopSelectorScreen .loop-selector-title {
        text-style: bold;
        color: $primary;
        text-align: center;
        margin-bottom: 1;
    }

    LoopSelectorScreen #loop-filter {
        margin-bottom: 1;
        border: solid $primary-lighten-2;
    }

    LoopSelectorScreen #loop-filter:focus {
        border: solid $primary;
    }

    LoopSelectorScreen .loop-selector-body {
        height: 1fr;
    }

    LoopSelectorScreen .loop-table-pane {
        width: 1fr;
        min-width: 40;
        height: 1fr;
    }

    LoopSelectorScreen .loop-controls {
        width: 28;
        min-width: 24;
        height: 1fr;
        margin-left: 1;
        padding-left: 1;
        border-left: solid $primary-lighten-2;
    }

    LoopSelectorScreen .loop-controls-title {
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }

    LoopSelectorScreen .loop-controls-help {
        color: $text-muted;
        margin-bottom: 1;
    }

    LoopSelectorScreen .loop-column-toggle {
        width: 1fr;
        height: auto;
    }

    LoopSelectorScreen .loop-list-header {
        height: 1;
        padding: 0 1;
        color: $text-muted;
        text-style: bold;
        width: 100%;
        overflow-x: hidden;
    }

    LoopSelectorScreen .loop-list-header .loop-cell-sorted {
        color: $primary;
    }

    LoopSelectorScreen .loop-list {
        height: 1fr;
        min-height: 5;
        scrollbar-gutter: stable;
        background: $background;
    }

    LoopSelectorScreen .loop-option {
        height: 1;
        width: 100%;
        padding: 0 1;
        overflow-x: hidden;
    }

    LoopSelectorScreen .loop-option:hover {
        background: $surface-lighten-1;
    }

    LoopSelectorScreen .loop-option-selected {
        background: $primary;
        color: $background;
        text-style: bold;
    }

    LoopSelectorScreen .loop-option-selected:hover {
        background: $primary-lighten-1;
    }

    LoopSelectorScreen .loop-option-current {
        text-style: italic;
    }

    LoopSelectorScreen .loop-cell {
        height: 1;
        padding-right: 1;
    }

    LoopSelectorScreen .loop-cell-cursor {
        width: 2;
        color: $primary;
    }

    LoopSelectorScreen .loop-cell-loop_id {
        width: auto;
        content-align: right middle;
    }

    LoopSelectorScreen .loop-cell-agent_name {
        width: auto;
        overflow-x: hidden;
        text-wrap: nowrap;
        text-overflow: ellipsis;
    }

    LoopSelectorScreen .loop-cell-messages {
        width: auto;
        content-align: right middle;
    }

    LoopSelectorScreen .loop-cell-updated_at {
        width: auto;
        content-align: right middle;
    }

    LoopSelectorScreen .loop-cell-topic {
        width: 1fr;
        min-width: 8;
        overflow-x: hidden;
        text-wrap: nowrap;
        text-overflow: ellipsis;
    }

    LoopSelectorScreen .loop-selector-help {
        height: auto;
        color: $text-muted;
        text-style: italic;
        margin-top: 1;
        text-align: center;
    }

    LoopSelectorScreen .loop-empty {
        color: $text-muted;
        text-align: center;
        margin-top: 2;
    }

    """

    def __init__(
        self,
        current_loop: str | None = None,
        *,
        loop_limit: int | None = None,
        initial_loops: list[dict[str, Any]] | None = None,
        daemon_session: Any | None = None,
    ) -> None:
        """Initialize the `LoopSelectorScreen`.

        Args:
            current_loop: The currently active loop ID (to highlight).
            loop_limit: Maximum number of rows to fetch when querying DB.
            initial_loops: Optional preloaded rows to render immediately.
            daemon_session: TuiDaemonSession instance for WebSocket RPC loop listing.
        """
        super().__init__()
        self._current_loop = current_loop
        self._loop_limit = loop_limit
        self._loops: list[dict[str, Any]] = list(initial_loops) if initial_loops is not None else []
        self._filtered_loops: list[dict[str, Any]] = list(self._loops)
        self._has_initial_loops = initial_loops is not None
        self._selected_index = 0
        self._option_widgets: list[LoopOption] = []
        self._filter_text = ""
        self._confirming_delete = False
        self._render_lock = asyncio.Lock()
        self._filter_input: Input | None = None
        self._filter_controls: list[Input | Checkbox] | None = None
        self._cell_text: dict[tuple[str, str], str] = {}
        self._daemon_session = daemon_session

        from soothe_cli.tui.model_config import load_loop_config

        cfg = load_loop_config()
        self._columns = dict(cfg.columns)
        self._relative_time = cfg.relative_time
        self._sort_by_updated = cfg.sort_order == "updated_at"

        # Cached loops are pre-sorted by updated_at DESC (the only sort
        # order the cache stores).  Skip the O(n log n) re-sort when that
        # matches the user's preference.
        if not (self._has_initial_loops and self._sort_by_updated):
            self._apply_sort()
        self._sync_selected_index()
        self._column_widths = self._compute_column_widths()

    @staticmethod
    def _switch_id(column_key: str) -> str:
        """Return the DOM id for a column toggle switch."""
        return f"{_SWITCH_ID_PREFIX}{column_key}"

    @staticmethod
    def _switch_column_key(switch_id: str | None) -> str | None:
        """Extract the column key from a switch id.

        Args:
            switch_id: Widget id for a switch in the control panel.

        Returns:
            The corresponding column key, or `None` for unrelated ids.
        """
        if not switch_id or not switch_id.startswith(_SWITCH_ID_PREFIX):
            return None
        return switch_id.removeprefix(_SWITCH_ID_PREFIX)

    def _sync_selected_index(self) -> None:
        """Select the current loop when it exists in the loaded rows."""
        self._selected_index = 0
        for i, loop in enumerate(self._filtered_loops):
            if loop["loop_id"] == self._current_loop:
                self._selected_index = i
                break

    def _build_title(self) -> str:
        """Build the title with the current loop ID.

        Returns:
            Plain string with the current loop ID.
        """
        if not self._current_loop:
            return "Select Loop"
        return f"Select Loop (current: {self._current_loop})"

    def _build_help_text(self) -> str:
        """Build the footer help text for the selector.

        Returns:
            Footer guidance for the active selector bindings.
        """
        glyphs = get_glyphs()
        lines = (
            f"{glyphs.arrow_up}/{glyphs.arrow_down} navigate"
            f" {glyphs.bullet} Enter select"
            f" {glyphs.bullet} S toggle sort"
            f" {glyphs.bullet} R toggle relative timestamps"
            f" {glyphs.bullet} Esc cancel"
        )
        limit = self._effective_loop_limit()
        if len(self._loops) >= limit:
            lines += f"\nShowing last {limit} loops. Set DA_CLI_RECENT_LOOPS to override."
        return lines

    def _effective_loop_limit(self) -> int:
        """Return the resolved loop limit for display purposes."""
        if self._loop_limit is not None:
            return self._loop_limit
        from soothe_cli.tui.sessions import get_loop_limit

        return get_loop_limit()

    def _format_sort_toggle_label(self) -> str:
        """Return the control-panel sort label for the toggle switch."""
        label = "Updated At" if self._sort_by_updated else "Created At"
        return f"Sort by {label}"

    def _get_filter_input(self) -> Input:
        """Return the cached search input widget."""
        if self._filter_input is None:
            self._filter_input = self.query_one("#loop-filter", Input)
        return self._filter_input

    def _filter_focus_order(self) -> list[Input | Checkbox]:
        """Return focusable controls for the selector."""
        return [self._get_filter_input()]

    def compose(self) -> ComposeResult:
        """Compose the screen layout.

        Yields:
            Widgets for the loop selector UI.
        """
        with Vertical(id="loop-selector-shell"):
            yield Static(self._build_title(), classes="loop-selector-title", id="loop-title")

            yield Input(
                placeholder="Type to search loops...",
                select_on_focus=False,
                id="loop-filter",
            )

            with Vertical(classes="loop-selector-body loop-table-pane"):
                with Horizontal(
                    classes="loop-list-header",
                    id="loop-header",
                ):
                    yield Static("", classes="loop-cell loop-cell-cursor")
                    sort_key = _active_sort_key(self._sort_by_updated)
                    for key in _visible_column_keys(self._columns):
                        cell = Static(
                            _format_header_label(key),
                            classes=_header_cell_classes(key, sort_key=sort_key),
                            expand=key == "topic",
                            markup=False,
                        )
                        _apply_column_width(cell, key, self._column_widths)
                        yield cell

                with VerticalScroll(classes="loop-list"):
                    if self._has_initial_loops:
                        if self._filtered_loops:
                            self._option_widgets, _ = self._create_option_widgets()
                            yield from self._option_widgets
                        else:
                            yield Static(
                                Content.styled("No loops found", "dim"),
                                classes="loop-empty",
                            )
                    else:
                        yield Static(
                            Content.styled("Loading loops...", "dim"),
                            classes="loop-empty",
                            id="loop-loading",
                        )

            yield Static(
                self._build_help_text(),
                classes="loop-selector-help",
                id="loop-help",
            )

    async def on_mount(self) -> None:
        """Fetch loops, configure border for ASCII terminals, and build the list."""
        if is_ascii_mode():
            container = self.query_one("#loop-selector-shell", Vertical)
            colors = theme.get_theme_colors(self)
            container.styles.border = ("ascii", colors.success)

        filter_input = self._get_filter_input()
        filter_input.focus()

        if self._has_initial_loops:
            self.call_after_refresh(self._scroll_selected_into_view)

        if self._has_initial_loops:
            # Defer by one message cycle so Textual finishes processing
            # mount messages before we start the DB refresh.
            self.call_after_refresh(self._start_loop_load)
        else:
            # _load_loops replaces self._loops and schedules background
            # enrichment (message counts, initial prompts) after load
            # completes.  Launch immediately when there are no cached rows
            # to render.
            self.run_worker(self._load_loops, exclusive=True, group="loop-selector-load")

    def _start_loop_load(self) -> None:
        """Launch the loop-load worker after the initial layout pass."""
        if not self.is_attached:
            return
        self.run_worker(self._load_loops, exclusive=True, group="loop-selector-load")

    def on_input_changed(self, event: Input.Changed) -> None:
        """Filter loops as user types.

        Args:
            event: The input changed event.
        """
        self._filter_text = event.value
        self._schedule_filter_and_rebuild()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key when filter input is focused.

        Args:
            event: The input submitted event.
        """
        event.stop()
        self.action_select()

    def on_key(self, event: Key) -> None:
        """Return focus to search when letters are typed from other controls.

        Args:
            event: The key event.
        """
        filter_input = self._get_filter_input()
        if filter_input.has_focus:
            return

        character = event.character
        if not character or not character.isalpha():
            return

        filter_input.focus()
        filter_input.insert_text_at_cursor(character)
        self.set_timer(0.01, self._collapse_search_selection)
        event.stop()

    def _collapse_search_selection(self) -> None:
        """Place the search cursor at the end without an active selection."""
        filter_input = self._get_filter_input()
        filter_input.selection = type(filter_input.selection).cursor(len(filter_input.value))

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        """Route sort, relative-time, and column-visibility checkbox changes.

        Args:
            event: The checkbox change event.
        """
        if event.checkbox.id == _SORT_SWITCH_ID:
            if self._sort_by_updated == event.value:
                return
            self._sort_by_updated = event.value
            self._apply_sort()
            self._sync_selected_index()
            self._update_help_widgets()
            self._schedule_list_rebuild()

            self._persist_sort_order("updated_at" if event.value else "created_at")
            return

        if event.checkbox.id == _RELATIVE_TIME_SWITCH_ID:
            if self._relative_time == event.value:
                return
            self._relative_time = event.value

            from soothe_cli.tui.model_config import save_loop_relative_time

            self.run_worker(
                asyncio.to_thread(save_loop_relative_time, event.value),
                group="loop-selector-save",
            )
            self._schedule_list_rebuild()
            return

        column_key = self._switch_column_key(event.checkbox.id)
        if column_key is None or column_key not in self._columns:
            return
        if self._columns[column_key] == event.value:
            return

        self._columns[column_key] = event.value
        self._apply_sort()
        self._sync_selected_index()
        self._update_help_widgets()

        snapshot = dict(self._columns)

        from soothe_cli.tui.model_config import save_loop_columns

        self.run_worker(
            asyncio.to_thread(save_loop_columns, snapshot),
            group="loop-selector-save",
        )
        self._schedule_list_rebuild()

    def _update_filtered_list(self) -> None:
        """Update filtered loops based on search text using fuzzy matching."""
        query = self._filter_text.strip()
        if not query:
            self._filtered_loops = list(self._loops)
            self._apply_sort()
            self._sync_selected_index()
            self._column_widths = self._compute_column_widths()
            return

        tokens = query.split()
        try:
            matchers = [Matcher(token, case_sensitive=False) for token in tokens]
            scored: list[tuple[float, dict[str, Any]]] = []
            for loop in self._loops:
                search_text = self._get_search_text(loop)
                scores = [matcher.match(search_text) for matcher in matchers]
                if all(score > 0 for score in scores):
                    scored.append((min(scores), loop))
        except Exception:
            logger.warning(
                "Fuzzy matcher failed for query %r, falling back to full list",
                query,
                exc_info=True,
            )
            self._filtered_loops = list(self._loops)
            self._apply_sort()
            self._sync_selected_index()
            self._column_widths = self._compute_column_widths()
            return

        sort_key = _active_sort_key(self._sort_by_updated)
        self._filtered_loops = [
            loop
            for _, loop in sorted(
                scored,
                key=lambda item: (
                    item[0],
                    item[1].get(sort_key) or "",
                    item[1].get("updated_at") or "",
                    item[1]["loop_id"],
                ),
                reverse=True,
            )
        ]
        self._selected_index = 0
        self._column_widths = self._compute_column_widths()

    def _compute_column_widths(self) -> dict[str, int | None]:
        """Return effective widths for the current table state.

        Textual's `width: auto` computes per-widget widths, so this method
        derives shared widths from the visible data instead. Also populates
        `self._cell_text` as a side effect so that `LoopOption.compose()` can
        reuse the formatted strings.

        Returns:
            Dict mapping column keys to their effective cell widths, with
                `None` for flex columns.
        """
        global _column_widths_cache  # noqa: PLW0603  # Module-level cache requires global statement

        visible_keys = _visible_column_keys(self._columns)
        visible = frozenset(visible_keys)
        fingerprint = tuple(
            (t["loop_id"], t.get("latest_checkpoint_id")) for t in self._filtered_loops
        )

        if _column_widths_cache is not None:
            cached = _column_widths_cache
            if (
                cached.fingerprint == fingerprint
                and cached.visible_columns == visible
                and cached.relative_time == self._relative_time
                and self._cell_text
            ):
                return dict(cached.widths)

        # Pre-format every visible cell in one pass.
        cell_text: dict[tuple[str, str], str] = {}
        for loop in self._filtered_loops:
            tid = loop["loop_id"]
            for key in visible_keys:
                cell_text[tid, key] = _format_column_value(
                    loop, key, relative_time=self._relative_time
                )
        self._cell_text = cell_text

        # Derive auto-widths from the pre-formatted values.
        widths = dict(_COLUMN_WIDTHS)
        for key in _AUTO_WIDTH_COLUMNS:
            if key not in visible:
                continue
            header_len = cell_len(_format_header_label(key))
            max_cell = max(
                (cell_len(cell_text[t["loop_id"], key]) for t in self._filtered_loops),
                default=0,
            )
            widths[key] = max(header_len, max_cell) + _CELL_PADDING_RIGHT

        _column_widths_cache = _LoopColumnWidthsCache(
            fingerprint=fingerprint,
            visible_columns=visible,
            relative_time=self._relative_time,
            widths=widths,
        )
        return widths

    @staticmethod
    def _get_search_text(loop: dict[str, Any]) -> str:
        """Build searchable text from loop fields.

        The result is capped at `_MAX_SEARCH_TEXT_LEN` characters so that
        Textual's fuzzy `Matcher` (which uses recursive backtracking) does
        not hit exponential performance on long initial prompts with
        repeated characters.

        Args:
            loop: Loop metadata dict.

        Returns:
            Concatenated searchable string, truncated to a safe length.
        """
        parts = [
            loop["loop_id"],
            loop.get("topic") or "",
            loop.get("prompt") or "",
        ]
        text = " ".join(parts)
        return text[:_MAX_SEARCH_TEXT_LEN]

    def _schedule_filter_and_rebuild(self) -> None:
        """Queue a filter + rebuild, coalescing rapid keystrokes."""
        self.run_worker(
            self._filter_and_build,
            exclusive=True,
            group="loop-selector-render",
        )

    async def _filter_and_build(self) -> None:
        """Run fuzzy filtering in a loop then rebuild the list."""
        query = self._filter_text.strip()
        loops = list(self._loops)
        sort_by_updated = self._sort_by_updated

        filtered = await asyncio.to_thread(self._compute_filtered, query, loops, sort_by_updated)
        self._filtered_loops = filtered
        if query:
            self._selected_index = 0
        else:
            self._sync_selected_index()
        self._column_widths = self._compute_column_widths()
        await self._build_list(recompute_widths=False)

    @staticmethod
    def _compute_filtered(
        query: str,
        loops: list[dict[str, Any]],
        sort_by_updated: bool,
    ) -> list[dict[str, Any]]:
        """Compute filtered loop list off the main loop.

        Args:
            query: Current search query text.
            loops: Full loop list snapshot.
            sort_by_updated: Whether to sort by `updated_at`.

        Returns:
            Filtered and sorted loop list.
        """
        sort_key = _active_sort_key(sort_by_updated)

        if not query:
            return _sort_loops(list(loops), sort_key=sort_key)

        tokens = query.split()
        try:
            matchers = [Matcher(token, case_sensitive=False) for token in tokens]
            scored: list[tuple[float, dict[str, Any]]] = []
            for loop in loops:
                search_text = LoopSelectorScreen._get_search_text(loop)
                scores = [matcher.match(search_text) for matcher in matchers]
                if all(score > 0 for score in scores):
                    scored.append((min(scores), loop))
        except Exception:
            logger.warning(
                "Fuzzy matcher failed for query %r, falling back to full list",
                query,
                exc_info=True,
            )
            result = list(loops)
            return _sort_loops(result, sort_key=sort_key)

        matched = [
            loop
            for _, loop in sorted(
                scored,
                key=lambda item: (
                    item[0],
                    item[1].get(sort_key) or item[1].get("created") or "",
                    item[1].get("created") or "",
                    item[1]["loop_id"],
                ),
                reverse=True,
            )
        ]
        active = [loop for loop in matched if _is_active_loop(loop)]
        inactive = [loop for loop in matched if not _is_active_loop(loop)]
        return active + inactive

    def _schedule_list_rebuild(self) -> None:
        """Queue a list rebuild, coalescing rapid updates."""
        self.run_worker(
            self._build_list,
            exclusive=True,
            group="loop-selector-render",
        )

    @staticmethod
    def _loops_match(old: list[dict[str, Any]], new: list[dict[str, Any]]) -> bool:
        """Check whether two loop lists have the same IDs in order.

        Args:
            old: Previous loop list.
            new: Fresh loop list.

        Returns:
            True if both lists have identical loop IDs.
        """
        if len(old) != len(new):
            return False
        for a, b in zip(old, new, strict=True):
            if a["loop_id"] != b["loop_id"]:
                return False
        return True

    async def _load_loops(self) -> None:
        """Load loop rows first, then kick off background enrichment."""
        old_loops = list(self._loops)

        try:
            limit = self._loop_limit
            if limit is None:
                from soothe_cli.tui.sessions import get_loop_limit

                limit = get_loop_limit()
            sort_by = "updated" if self._sort_by_updated else "created"

            # Use daemon RPC if available (queries actual loop persistence)
            if self._daemon_session is not None:
                from soothe_cli.tui.sessions import list_loops_via_daemon_rpc

                self._loops = await list_loops_via_daemon_rpc(
                    daemon_session=self._daemon_session,
                    limit=limit,
                    sort_by=sort_by,
                )
            else:
                # No daemon session available - cannot load loops
                logger.warning("No daemon session available for loop listing")
                self._loops = []
                await self._show_mount_error("Daemon session required for loop listing")
                return
        except Exception as exc:
            logger.exception("Failed to load loops for loop selector")
            await self._show_mount_error(str(exc))
            return

        self._update_filtered_list()
        self._sync_selected_index()

        # Short-circuit: when the fresh data matches what is already rendered,
        # update widget references and cell labels without tearing down the DOM.
        if (
            self._has_initial_loops
            and self._option_widgets
            and self._loops_match(old_loops, self._filtered_loops)
        ):
            for widget, loop in zip(
                self._option_widgets,
                self._filtered_loops,
                strict=True,
            ):
                widget.loop = loop
            self._refresh_cell_labels()
        else:
            await self._build_list()

    def _refresh_cell_labels(self) -> None:
        """Update visible cell text in-place without rebuilding the DOM."""
        visible_keys = _visible_column_keys(self._columns)

        # Recompute because loop data may have changed since
        # _compute_column_widths populated the cache.
        cell_text: dict[tuple[str, str], str] = {}
        for loop in self._filtered_loops:
            tid = loop["loop_id"]
            for key in visible_keys:
                cell_text[tid, key] = _format_column_value(
                    loop, key, relative_time=self._relative_time
                )
        self._cell_text = cell_text

        for widget in self._option_widgets:
            tid = widget.loop_id
            for key in visible_keys:
                try:
                    cell = widget.query_one(f".loop-cell-{key}", Static)
                except NoMatches:
                    continue
                cell.update(cell_text[tid, key])

    async def _show_mount_error(self, detail: str) -> None:
        """Display an error message inside the loop list and refocus.

        Args:
            detail: Human-readable error detail to show.
        """
        try:
            async with self._render_lock:
                scroll = self.query_one(".loop-list", VerticalScroll)
                await scroll.remove_children()
                await scroll.mount(
                    Static(
                        Content.from_markup(
                            "[red]Failed to load loops: $detail. Press Esc to close.[/red]",
                            detail=detail,
                        ),
                        classes="loop-empty",
                    )
                )
        except Exception:
            logger.warning(
                "Could not display error message in loop selector UI",
                exc_info=True,
            )
        self.focus()

    async def _build_list(self, *, recompute_widths: bool = True) -> None:
        """Build the loop option widgets.

        Args:
            recompute_widths: Whether to recalculate shared column widths first.
        """
        async with self._render_lock:
            try:
                scroll = self.query_one(".loop-list", VerticalScroll)
            except NoMatches:
                return

            if recompute_widths:
                self._column_widths = self._compute_column_widths()
            with self.app.batch_update():
                await scroll.remove_children()
                self._update_help_widgets()

                if not self._filtered_loops:
                    self._option_widgets = []
                    await scroll.mount(
                        Static(
                            Content.styled("No loops found", "dim"),
                            classes="loop-empty",
                        )
                    )
                    return

                self._option_widgets, selected_widget = self._create_option_widgets()
                await scroll.mount(*self._option_widgets)

            if selected_widget:
                self.call_after_refresh(self._scroll_selected_into_view)

    def _create_option_widgets(self) -> tuple[list[LoopOption], LoopOption | None]:
        """Build option widgets from filtered loops without mounting.

        Returns:
            Tuple of all option widgets and the currently selected widget.
        """
        widgets: list[LoopOption] = []
        selected_widget: LoopOption | None = None

        for i, loop in enumerate(self._filtered_loops):
            is_current = loop["loop_id"] == self._current_loop
            is_selected = i == self._selected_index

            classes = "loop-option"
            if is_selected:
                classes += " loop-option-selected"
            if is_current:
                classes += " loop-option-current"

            widget = LoopOption(
                loop=loop,
                index=i,
                columns=self._columns,
                column_widths=self._column_widths,
                selected=is_selected,
                current=is_current,
                relative_time=self._relative_time,
                cell_text=self._cell_text or None,
                classes=classes,
            )
            widgets.append(widget)
            if is_selected:
                selected_widget = widget

        return widgets, selected_widget

    def _scroll_selected_into_view(self) -> None:
        """Scroll selected option into view without animation."""
        if not self._option_widgets:
            return
        if self._selected_index >= len(self._option_widgets):
            return
        try:
            scroll = self.query_one(".loop-list", VerticalScroll)
        except NoMatches:
            return

        if self._selected_index == 0:
            scroll.scroll_home(animate=False)
        else:
            self._option_widgets[self._selected_index].scroll_visible(animate=False)

    def _update_help_widgets(self) -> None:
        """Update visible header and help text after state changes."""
        self._schedule_header_rebuild()

        try:
            help_widget = self.query_one("#loop-help", Static)
            help_widget.update(self._build_help_text())
        except NoMatches:
            logger.debug("Help widget #loop-help not found during update")

        with contextlib.suppress(NoMatches):
            sort_checkbox = self.query_one(f"#{_SORT_SWITCH_ID}", Checkbox)
            sort_checkbox.label = self._format_sort_toggle_label()
            if sort_checkbox.value != self._sort_by_updated:
                sort_checkbox.value = self._sort_by_updated

    def _schedule_header_rebuild(self) -> None:
        """Queue a header rebuild to reflect column/sort changes."""
        self.run_worker(
            self._rebuild_header,
            exclusive=True,
            group="loop-selector-header",
        )

    async def _rebuild_header(self) -> None:
        """Replace header cells to match current visible columns."""
        try:
            header = self.query_one("#loop-header", Horizontal)
        except NoMatches:
            return
        sort_key = _active_sort_key(self._sort_by_updated)
        self._column_widths = self._compute_column_widths()
        with self.app.batch_update():
            await header.remove_children()
            cells: list[Static] = [Static("", classes="loop-cell loop-cell-cursor")]
            for key in _visible_column_keys(self._columns):
                cell = Static(
                    _format_header_label(key),
                    classes=_header_cell_classes(key, sort_key=sort_key),
                    expand=key == "topic",
                    markup=False,
                )
                _apply_column_width(cell, key, self._column_widths)
                cells.append(cell)
            await header.mount(*cells)

    def _apply_sort(self) -> None:
        """Sort filtered loops with live/running rows first."""
        key = _active_sort_key(self._sort_by_updated)
        self._filtered_loops = _sort_loops(self._filtered_loops, sort_key=key)

    def _move_selection(self, delta: int) -> None:
        """Move selection by delta, updating only the affected rows.

        Args:
            delta: Positions to move (negative for up, positive for down).
        """
        if not self._filtered_loops or not self._option_widgets:
            return

        count = len(self._filtered_loops)
        old_index = self._selected_index
        new_index = (old_index + delta) % count
        self._selected_index = new_index

        self._option_widgets[old_index].set_selected(False)
        self._option_widgets[new_index].set_selected(True)

        if new_index == 0:
            scroll = self.query_one(".loop-list", VerticalScroll)
            scroll.scroll_home(animate=False)
        else:
            self._option_widgets[new_index].scroll_visible()

    def action_move_up(self) -> None:
        """Move selection up."""
        self._move_selection(-1)

    def action_move_down(self) -> None:
        """Move selection down."""
        self._move_selection(1)

    def _visible_page_size(self) -> int:
        """Return the number of loop options that fit in one visual page.

        Returns:
            Number of loop options per page, at least 1.
        """
        default_page_size = 10
        try:
            scroll = self.query_one(".loop-list", VerticalScroll)
            height = scroll.size.height
        except NoMatches:
            logger.debug(
                "Loop list widget not found in _visible_page_size; using default page size %d",
                default_page_size,
            )
            return default_page_size
        if height <= 0:
            return default_page_size
        return max(1, height)

    def action_page_up(self) -> None:
        """Move selection up by one visible page."""
        if not self._filtered_loops:
            return
        page = self._visible_page_size()
        target = max(0, self._selected_index - page)
        delta = target - self._selected_index
        if delta != 0:
            self._move_selection(delta)

    def action_page_down(self) -> None:
        """Move selection down by one visible page."""
        if not self._filtered_loops:
            return
        count = len(self._filtered_loops)
        page = self._visible_page_size()
        target = min(count - 1, self._selected_index + page)
        delta = target - self._selected_index
        if delta != 0:
            self._move_selection(delta)

    def action_select(self) -> None:
        """Confirm the highlighted loop and dismiss the selector."""
        if self._filtered_loops:
            loop_id = self._filtered_loops[self._selected_index]["loop_id"]
            self.dismiss(loop_id)

    def action_focus_next_filter(self) -> None:
        """Move focus through the filter and column-toggle controls."""
        controls = self._filter_focus_order()
        focused = self.focused
        if focused not in controls:
            controls[0].focus()
            return

        index = controls.index(cast("Input | Checkbox", focused))
        controls[(index + 1) % len(controls)].focus()

    def action_focus_previous_filter(self) -> None:
        """Move focus backward through the filter and column-toggle controls."""
        controls = self._filter_focus_order()
        focused = self.focused
        if focused not in controls:
            controls[-1].focus()
            return

        index = controls.index(cast("Input | Checkbox", focused))
        controls[(index - 1) % len(controls)].focus()

    def action_toggle_sort(self) -> None:
        """Toggle sort between updated_at and created_at."""
        self._sort_by_updated = not self._sort_by_updated
        self._apply_sort()
        self._sync_selected_index()
        self._update_help_widgets()
        self._schedule_list_rebuild()

        self._persist_sort_order("updated_at" if self._sort_by_updated else "created_at")

    def action_toggle_relative_time(self) -> None:
        """Toggle timestamp display between relative and absolute."""
        self._relative_time = not self._relative_time

        from soothe_cli.tui.model_config import save_loop_relative_time

        self.run_worker(
            asyncio.to_thread(save_loop_relative_time, self._relative_time),
            group="loop-selector-save",
        )
        self._schedule_list_rebuild()

    def _persist_sort_order(self, order: str) -> None:
        """Save sort-order preference to config, notifying on failure."""

        async def _save() -> None:
            from soothe_cli.tui.model_config import save_loop_sort_order

            ok = await asyncio.to_thread(save_loop_sort_order, order)
            if not ok:
                self.app.notify("Could not save sort preference", severity="warning")

        self.run_worker(_save(), group="loop-selector-save")

    def on_click(self, event: Click) -> None:  # noqa: PLR6301  # Textual event handler
        """Open Rich-style hyperlinks on single click."""
        open_style_link(event)

    def on_loop_option_clicked(self, event: LoopOption.Clicked) -> None:
        """Handle click on a loop option.

        Args:
            event: The clicked message with loop ID and index.
        """
        if 0 <= event.index < len(self._filtered_loops):
            self._selected_index = event.index
            self.dismiss(event.loop_id)

    def action_cancel(self) -> None:
        """Cancel the selection."""
        self.dismiss(None)
