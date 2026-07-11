"""Context Engine viewer screen for /context command.

Displays token usage, goal DAG, and status from the Context Engine using the
configured persistence backend (SQLite or PostgreSQL).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, ClassVar

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
    "blocked": "⏺",
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


class TokenUsagePanel(Static):
    """Displays context window token usage."""

    DEFAULT_CSS = """
    TokenUsagePanel {
        width: 1fr;
        height: auto;
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
        max-height: 16;
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
            return "[dim]No goals in context engine[/]"

        lines = ["[bold green]Goal DAG[/]", ""]
        for goal in self._goals:
            status = str(goal.get("status") or "pending")
            color = STATUS_COLORS.get(status, "dim")
            icon = STATUS_ICONS.get(status, "○")
            gid = goal.get("id", "?")
            desc = str(goal.get("description") or "")
            if len(desc) > 60:
                desc = desc[:57] + "..."
            deps = ""
            depends_on = goal.get("depends_on")
            if depends_on:
                deps = f" [dim](→ {', '.join(depends_on[:3])})[/]"
            lines.append(f"  [{color}]{icon}[/] [{color}]{gid}[/] {desc}{deps}")

        return "\n".join(lines)


class StatusPanel(Static):
    """Displays context engine status summary."""

    DEFAULT_CSS = """
    StatusPanel {
        width: 1fr;
        height: auto;
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
        if total == 0:
            status_line = "  Total: 0"
        else:
            parts = [f"Total: {total}"]
            for status in (
                "active",
                "completed",
                "pending",
                "failed",
                "validated",
                "suspended",
                "blocked",
                "awaiting_clarification",
                "cancelled",
            ):
                value = counts.get(status, 0)
                if value:
                    parts.append(f"{status.title()}: {value}")
            for status, value in sorted(counts.items()):
                if status in {
                    "active",
                    "completed",
                    "pending",
                    "failed",
                    "validated",
                    "suspended",
                    "blocked",
                    "awaiting_clarification",
                    "cancelled",
                }:
                    continue
                if value:
                    parts.append(f"{status.title()}: {value}")
            status_line = "  " + "  |  ".join(parts)

        return "\n".join(
            [
                f"[bold blue]Context Status[/]  [dim]Loop: {_abbreviate_loop_id(self._loop_id)}[/]",
                status_line,
            ]
        )


class ContextViewerScreen(ModalScreen[None]):
    """Modal dialog displaying token usage and Context Engine goal DAG/status."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Close", show=False),
    ]

    CSS = """
    ContextViewerScreen {
        align: center middle;
        background: transparent;
    }

    ContextViewerScreen > Vertical {
        width: 60;
        max-width: 90%;
        height: auto;
        max-height: 80%;
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

    ContextViewerScreen ScrollableContainer {
        height: auto;
        max-height: 16;
        background: $background;
    }

    ContextViewerScreen .context-help {
        height: 1;
        color: $text-muted;
        text-style: italic;
        margin-top: 1;
        text-align: center;
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
        if is_ascii_mode():
            container = self.query_one(Vertical)
            from soothe_cli.tui import theme

            colors = theme.get_theme_colors(self)
            container.styles.border = ("ascii", colors.success)
        self.run_worker(self._async_refresh(), exclusive=False, group="context-viewer")
        self.set_interval(_REFRESH_INTERVAL_S, self._schedule_refresh)

    def action_cancel(self) -> None:
        """Dismiss the modal."""
        self.dismiss(None)

    def _schedule_refresh(self) -> None:
        """Kick off a background refresh on the timer tick."""
        self.run_worker(self._async_refresh(), exclusive=False, group="context-viewer")

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
