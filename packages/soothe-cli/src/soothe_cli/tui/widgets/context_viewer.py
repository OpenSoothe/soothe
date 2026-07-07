"""Context Engine viewer screen for /context command.

Displays goal DAG and status from the context engine's persisted state:
    SOOTHE_HOME/data/context_engine/{loop_id}/goal_step_dag.json

Read-only view similar to ThemeSelectorScreen modal dialog pattern.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import TYPE_CHECKING, Any, ClassVar

from textual.binding import Binding, BindingType
from textual.containers import ScrollableContainer, Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

if TYPE_CHECKING:
    from textual.app import ComposeResult

from soothe.foundation.sloop.state.persistence.runtime_paths import resolve_context_engine_db_path

from soothe_cli.tui.config import get_glyphs, is_ascii_mode

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
}

STATUS_ICONS: dict[str, str] = {
    "pending": "○",
    "active": "◉",
    "completed": "✓",
    "failed": "✗",
    "cancelled": "⊘",
    "suspended": "⏸",
    "blocked": "⏺",
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


def _load_goals_from_sqlite(loop_id: str) -> list[dict[str, Any]]:
    """Load loop goals from the shared Context Engine SQLite DAG snapshot."""
    raw_loop_id = str(loop_id or "").strip()
    if not raw_loop_id or raw_loop_id == "unknown":
        return []

    db_path = resolve_context_engine_db_path()
    if not db_path.is_file():
        return []

    try:
        with sqlite3.connect(str(db_path), timeout=2.0) as conn:
            row = conn.execute(
                "SELECT dag_json FROM ce_dag WHERE loop_id = ?",
                (raw_loop_id,),
            ).fetchone()
    except sqlite3.Error:
        logger.debug("Failed to read CE SQLite at %s", db_path, exc_info=True)
        return []

    if row is None or not row[0]:
        return []

    try:
        data = json.loads(str(row[0]))
    except json.JSONDecodeError:
        logger.debug("Invalid DAG JSON for loop %s", raw_loop_id, exc_info=True)
        return []

    goals = data.get("goals", []) if isinstance(data, dict) else []
    if not isinstance(goals, list):
        return []
    return [g for g in goals if isinstance(g, dict)]


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
        """Initialize with goal data.

        Args:
            goals: List of goal dicts from GoalStepDAG.
            **kwargs: Passed to parent.
        """
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
        for g in self._goals:
            status = g.get("status", "pending")
            color = STATUS_COLORS.get(status, "dim")
            icon = STATUS_ICONS.get(status, "○")
            gid = g.get("id", "?")
            desc = g.get("description", "")
            # Truncate long descriptions
            if len(desc) > 60:
                desc = desc[:57] + "..."
            # Show dependencies if present
            deps = ""
            if g.get("depends_on"):
                deps = f" [dim](→ {', '.join(g['depends_on'][:3])})[/]"
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
        """Initialize with goal data.

        Args:
            goals: List of goal dicts.
            loop_id: Current loop ID.
            **kwargs: Passed to parent.
        """
        super().__init__(**kwargs)
        self._goals = goals
        self._loop_id = loop_id

    def set_goals(self, goals: list[dict[str, Any]]) -> None:
        """Replace current goals and refresh panel content."""
        self._goals = goals
        self.update(self.render())

    def render(self) -> str:
        """Render status summary."""
        active = sum(1 for g in self._goals if g.get("status") == "active")
        completed = sum(1 for g in self._goals if g.get("status") == "completed")
        pending = sum(1 for g in self._goals if g.get("status") == "pending")
        failed = sum(1 for g in self._goals if g.get("status") == "failed")
        total = len(self._goals)

        lines = [
            f"[bold blue]Context Status[/]  [dim]Loop: {_abbreviate_loop_id(self._loop_id)}[/]",
            f"  Total: {total}  |  Active: {active}  |  Completed: {completed}  |  Pending: {pending}  |  Failed: {failed}",
        ]
        return "\n".join(lines)


class ContextViewerScreen(ModalScreen[None]):
    """Modal dialog displaying context engine goal DAG and status.

    Reads from persisted GoalStepDAG file:
        SOOTHE_HOME/data/context_engine/{loop_id}/goal_step_dag.json

    Press Escape to close.
    """

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

    def __init__(self, loop_id: str | None, **kwargs: Any) -> None:
        """Initialize the ContextViewerScreen.

        Args:
            loop_id: Current loop ID to read context engine data.
            **kwargs: Passed to parent.
        """
        super().__init__()
        self._loop_id = loop_id or "unknown"
        self._goals: list[dict[str, Any]] = []

    def compose(self) -> ComposeResult:
        """Compose the screen layout."""
        glyphs = get_glyphs()
        self._goals = _load_goals_from_sqlite(self._loop_id)

        with Vertical():
            yield Static("Context Engine", classes="context-title")
            yield StatusPanel(goals=self._goals, loop_id=self._loop_id)
            yield ScrollableContainer(
                GoalDagPanel(goals=self._goals),
            )
            yield Static(
                f"{glyphs.arrow_up}/{glyphs.arrow_down} scroll  {glyphs.bullet}  Esc close",
                classes="context-help",
            )

    def on_mount(self) -> None:
        """Apply ASCII border if needed."""
        if is_ascii_mode():
            container = self.query_one(Vertical)
            from soothe_cli.tui import theme

            colors = theme.get_theme_colors(self)
            container.styles.border = ("ascii", colors.success)
        self._refresh_context()
        self.set_interval(_REFRESH_INTERVAL_S, self._refresh_context)

    def action_cancel(self) -> None:
        """Dismiss the modal."""
        self.dismiss(None)

    def _refresh_context(self) -> None:
        """Reload context data and refresh both panels."""
        goals = _load_goals_from_sqlite(self._loop_id)
        self._goals = goals
        try:
            self.query_one(StatusPanel).set_goals(goals)
            self.query_one(GoalDagPanel).set_goals(goals)
        except Exception:
            logger.debug("Failed to refresh context viewer panels", exc_info=True)
