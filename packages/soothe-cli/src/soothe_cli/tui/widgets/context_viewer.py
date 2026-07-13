"""Context Engine viewer screen for /context command.

Displays token usage, goal DAG, and status from the Context Engine using the
configured persistence backend (SQLite or PostgreSQL).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, ClassVar

from textual import events
from textual.binding import Binding, BindingType
from textual.containers import ScrollableContainer, Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

if TYPE_CHECKING:
    from textual.app import ComposeResult

from soothe_cli.tui.config import get_glyphs, is_ascii_mode
from soothe_cli.tui.widgets.context_data import (
    LoadTokenSnapshotFn,
    TokenUsageSnapshot,
    format_token_usage,
    load_ce_goals,
    summarize_goal_statuses,
)

logger = logging.getLogger(__name__)
_REFRESH_INTERVAL_S = 1.0
_COMPACT_MIN_WIDTH = 116
_COMPACT_MIN_HEIGHT = 32

# Status color mapping for goal/context display
STATUS_COLORS: dict[str, str] = {
    "pending": "dim",
    "active": "yellow",
    "validated": "blue",
    "completed": "green",
    "failed": "red",
    "cancelled": "dim red",
    "suspended": "magenta",
    "blocked": "orange",
    "awaiting_clarification": "magenta",
}

STATUS_ICONS: dict[str, str] = {
    "pending": "○",
    "active": "◉",
    "completed": "✓",
    "failed": "✗",
    "cancelled": "⊘",
    "suspended": "⏸",
    "blocked": "●",
    "awaiting_clarification": "?",
    "validated": "◆",
}


def _abbreviate_loop_id(loop_id: str) -> str:
    """Render loop id in ``prefix...suffix`` form for compact status lines."""
    raw = str(loop_id or "").strip().strip("[]")
    if not raw:
        return "unknown"
    compact = raw.replace("-", "")
    if "..." in compact:
        return compact
    if len(compact) <= 14:
        return compact
    return f"{compact[:8]}...{compact[-4:]}"


def _truncate_text(value: str, *, max_len: int) -> str:
    """Truncate ``value`` to ``max_len`` characters with ellipsis."""
    normalized = value.strip()
    if max_len <= 3:
        return normalized[:max_len]
    if len(normalized) <= max_len:
        return normalized
    return f"{normalized[: max_len - 3]}..."


def _abbreviate_goal_id(goal_id: str) -> str:
    """Render verbose goal ids in compact ``prefix...suffix`` form."""
    raw = str(goal_id or "").strip()
    if len(raw) <= 14:
        return raw
    return f"{raw[:8]}...{raw[-4:]}"


def _join_with_wrap(segments: list[str], *, width: int, prefix: str = "  ") -> list[str]:
    """Join segments into wrapped status lines using `` | `` separators."""
    if not segments:
        return [prefix.rstrip()]
    max_width = max(28, width)
    lines: list[str] = []
    current = prefix
    for segment in segments:
        candidate = segment if current.strip() == "" else f" | {segment}"
        if len(current) + len(candidate) > max_width and current.strip():
            lines.append(current)
            current = f"{prefix}{segment}"
            continue
        current += candidate
    if current.strip():
        lines.append(current)
    return lines


class TokenUsagePanel(Static):
    """Displays context window token usage."""

    DEFAULT_CSS = """
    TokenUsagePanel {
        width: 1fr;
        height: auto;
        min-height: 3;
        padding: 0 1;
        margin-bottom: 1;
    }
    """

    def __init__(self, snapshot: TokenUsageSnapshot | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._snapshot = snapshot

    def set_snapshot(self, snapshot: TokenUsageSnapshot | None) -> None:
        """Replace the token snapshot and refresh."""
        self._snapshot = snapshot
        self.update(self.render())

    def render(self) -> str:
        """Render token usage summary."""
        if self._snapshot is None:
            return "[bold cyan]Token Usage[/]\n  [dim]Loading…[/]"
        body = format_token_usage(self._snapshot)
        return f"[bold cyan]Token Usage[/]\n  {body}"


class GoalDagPanel(Static):
    """Displays goal DAG as a text tree."""

    DEFAULT_CSS = """
    GoalDagPanel {
        width: 1fr;
        height: auto;
        padding: 0 1;
    }
    """

    def __init__(self, goals: list[dict[str, Any]], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._goals = goals

    def set_goals(self, goals: list[dict[str, Any]]) -> None:
        """Replace current goals and refresh panel content."""
        self._goals = goals
        self.update(self.render())

    def render(self) -> str:
        """Render goal DAG as styled text."""
        if not self._goals:
            return "[bold green]Goal DAG[/]\n\n  [dim]No goals in context engine[/]"

        lines = ["[bold green]Goal DAG[/]", ""]
        panel_width = self.size.width if self.size.width > 0 else 80
        desc_max_len = max(40, panel_width - 24)
        for goal in self._goals:
            status = str(goal.get("status") or "pending")
            color = STATUS_COLORS.get(status, "dim")
            icon = STATUS_ICONS.get(status, "○")
            gid = _abbreviate_goal_id(str(goal.get("id", "?")))
            desc = str(goal.get("description") or "")
            desc = _truncate_text(desc, max_len=desc_max_len)
            base_line = f"  [{color}]{icon}[/] [{color}]{gid}[/]"
            if desc:
                base_line = f"{base_line} {desc}"
            lines.append(base_line)

            depends_on = goal.get("depends_on")
            if depends_on:
                dep_list = [str(dep) for dep in depends_on[:4]]
                dep_suffix = ""
                remaining = len(depends_on) - len(dep_list)
                if remaining > 0:
                    dep_suffix = f" (+{remaining} more)"
                deps_text = _truncate_text(
                    ", ".join(dep_list) + dep_suffix,
                    max_len=max(24, panel_width - 18),
                )
                lines.append(f"    [dim]depends on: {deps_text}[/]")

        return "\n".join(lines)


class StatusPanel(Static):
    """Displays context engine status summary."""

    DEFAULT_CSS = """
    StatusPanel {
        width: 1fr;
        height: auto;
        min-height: 3;
        padding: 0 1;
        margin-bottom: 1;
    }
    """

    def __init__(self, goals: list[dict[str, Any]], loop_id: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._goals = goals
        self._loop_id = loop_id

    def set_goals(self, goals: list[dict[str, Any]]) -> None:
        """Replace current goals and refresh panel content."""
        self._goals = goals
        self.update(self.render())

    def render(self) -> str:
        """Render status summary."""
        total, counts = summarize_goal_statuses(self._goals)
        panel_width = self.size.width if self.size.width > 0 else 80
        if total == 0:
            lines = [
                f"[bold blue]Context Status[/]  [dim]Loop: {_abbreviate_loop_id(self._loop_id)}[/]",
                "  Total: 0",
            ]
            return "\n".join(lines)
        else:
            primary_parts = [f"Total: {total}"]
            for status in ("active", "completed", "pending"):
                value = counts.get(status, 0)
                if value:
                    primary_parts.append(f"{status.title()}: {value}")

            secondary_order = (
                "failed",
                "validated",
                "suspended",
                "blocked",
                "awaiting_clarification",
                "cancelled",
            )
            secondary_parts: list[str] = []
            for status in secondary_order:
                value = counts.get(status, 0)
                if value:
                    secondary_parts.append(f"{status.title()}: {value}")
            for status, value in sorted(counts.items()):
                if status in {"active", "completed", "pending", *secondary_order}:
                    continue
                if value:
                    secondary_parts.append(f"{status.title()}: {value}")
            status_lines = _join_with_wrap(primary_parts, width=panel_width - 2)
            if secondary_parts:
                status_lines.extend(
                    _join_with_wrap(
                        [f"Other: {secondary_parts[0]}", *secondary_parts[1:]],
                        width=panel_width - 2,
                    )
                )

        lines = [
            f"[bold blue]Context Status[/]  [dim]Loop: {_abbreviate_loop_id(self._loop_id)}[/]",
            *status_lines,
        ]
        return "\n".join(lines)


class ContextViewerScreen(ModalScreen[None]):
    """Modal dialog displaying token usage and Context Engine goal DAG/status."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Close", show=False, priority=True),
        Binding("up,k", "scroll_up", "Up", show=False, priority=True),
        Binding("down,j", "scroll_down", "Down", show=False, priority=True),
        Binding("pageup", "page_up", "Page up", show=False, priority=True),
        Binding("pagedown", "page_down", "Page down", show=False, priority=True),
    ]

    CSS = """
    ContextViewerScreen {
        align: center middle;
        background: transparent;
    }

    ContextViewerScreen > Vertical {
        width: 96;
        max-width: 96%;
        height: 84%;
        max-height: 90%;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }

    ContextViewerScreen .context-title {
        text-style: bold;
        color: $primary;
        text-align: center;
        margin-bottom: 1;
    }

    ContextViewerScreen .context-summary {
        height: 1fr;
        min-height: 8;
        background: $background;
        padding: 0 1;
        margin-bottom: 1;
    }

    ContextViewerScreen ScrollableContainer {
        height: 2fr;
        min-height: 12;
        scrollbar-gutter: stable;
        background: $background;
        padding: 0 1;
    }

    ContextViewerScreen .context-help {
        height: 1;
        color: $text-muted;
        text-style: italic;
        margin-top: 1;
        text-align: center;
    }

    ContextViewerScreen.compact > Vertical {
        width: 98%;
        max-width: 98%;
        height: 91%;
        max-height: 96%;
        padding: 0 1;
    }

    ContextViewerScreen.compact .context-summary {
        min-height: 6;
        margin-bottom: 0;
    }

    ContextViewerScreen.compact ScrollableContainer {
        min-height: 9;
    }

    ContextViewerScreen.compact .context-title {
        margin-bottom: 0;
    }

    ContextViewerScreen.compact .context-help {
        margin-top: 0;
    }
    """

    def __init__(
        self,
        loop_id: str | None,
        *,
        load_token_snapshot: LoadTokenSnapshotFn | None = None,
        initial_token_snapshot: TokenUsageSnapshot | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the ContextViewerScreen.

        Args:
            loop_id: Current loop ID to read context engine data.
            load_token_snapshot: Optional async callback to refresh token usage.
            initial_token_snapshot: Seed token snapshot before the first refresh.
            **kwargs: Passed to parent.
        """
        super().__init__()
        self._loop_id = loop_id or "unknown"
        self._goals: list[dict[str, Any]] = []
        self._load_token_snapshot = load_token_snapshot
        self._token_snapshot = initial_token_snapshot

    def compose(self) -> ComposeResult:
        """Compose the screen layout."""
        glyphs = get_glyphs()
        with Vertical():
            yield Static("Context", classes="context-title")
            with Vertical(classes="context-summary"):
                yield TokenUsagePanel(snapshot=self._token_snapshot)
                yield StatusPanel(goals=self._goals, loop_id=self._loop_id)
            yield ScrollableContainer(
                GoalDagPanel(goals=self._goals),
            )
            yield Static(
                f"{glyphs.arrow_up}/{glyphs.arrow_down} scroll  {glyphs.bullet}  Esc close",
                classes="context-help",
            )

    def on_mount(self) -> None:
        """Apply ASCII border if needed and start refresh workers."""
        self._apply_responsive_mode()
        if is_ascii_mode():
            container = self.query_one(Vertical)
            from soothe_cli.tui import theme

            colors = theme.get_theme_colors(self)
            container.styles.border = ("ascii", colors.success)
        self.query_one(ScrollableContainer).focus()
        self.run_worker(self._async_refresh(), exclusive=False, group="context-viewer")
        self.set_interval(_REFRESH_INTERVAL_S, self._schedule_refresh)

    def action_cancel(self) -> None:
        """Dismiss the modal."""
        self.dismiss(None)

    def _scroll(self, *, delta: int) -> None:
        """Scroll the goal list by ``delta`` lines."""
        body = self.query_one(ScrollableContainer)
        body.scroll_relative(y=delta, animate=False)

    def action_scroll_up(self) -> None:
        """Scroll one line up in the goal list."""
        self._scroll(delta=-1)

    def action_scroll_down(self) -> None:
        """Scroll one line down in the goal list."""
        self._scroll(delta=1)

    def action_page_up(self) -> None:
        """Scroll up by half the visible body height."""
        body = self.query_one(ScrollableContainer)
        self._scroll(delta=-max(1, body.size.height // 2))

    def action_page_down(self) -> None:
        """Scroll down by half the visible body height."""
        body = self.query_one(ScrollableContainer)
        self._scroll(delta=max(1, body.size.height // 2))

    def on_resize(self, _event: events.Resize) -> None:
        """Re-evaluate compact layout mode when terminal size changes."""
        self._apply_responsive_mode()

    def _schedule_refresh(self) -> None:
        """Kick off a background refresh on the timer tick."""
        self.run_worker(self._async_refresh(), exclusive=False, group="context-viewer")

    def _apply_responsive_mode(self) -> None:
        """Toggle compact layout when terminal is narrow/short."""
        size = self.app.size
        is_compact = size.width < _COMPACT_MIN_WIDTH or size.height < _COMPACT_MIN_HEIGHT
        if is_compact:
            self.add_class("compact")
            return
        self.remove_class("compact")

    async def _async_refresh(self) -> None:
        """Reload context data and refresh all panels."""
        goals = await load_ce_goals(self._loop_id)
        token_snapshot = self._token_snapshot
        if self._load_token_snapshot is not None:
            try:
                token_snapshot = await self._load_token_snapshot()
            except Exception:
                logger.debug("Failed to refresh token usage snapshot", exc_info=True)
        self._goals = goals
        self._token_snapshot = token_snapshot
        try:
            self.query_one(TokenUsagePanel).set_snapshot(token_snapshot)
            self.query_one(StatusPanel).set_goals(goals)
            self.query_one(GoalDagPanel).set_goals(goals)
        except Exception:
            logger.debug("Failed to refresh context viewer panels", exc_info=True)
