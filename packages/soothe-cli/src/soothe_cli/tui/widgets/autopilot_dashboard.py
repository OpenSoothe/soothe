"""RFC-204: Autopilot TUI Dashboard — read-only monitoring view.

Four-panel layout (responsive):
  Wide terminal:  Goal DAG (left) | Status + Findings + Controls (right)
  Narrow terminal: Vertical stack (DAG → Status → Findings → Controls)

All panels are read-only; control actions are done via CLI commands.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from soothe.config import SOOTHE_HOME
from soothe.utils.text_preview import preview_first
from textual.containers import Container, ScrollableContainer
from textual.reactive import reactive
from textual.widgets import Static

if TYPE_CHECKING:
    from textual.app import ComposeResult

logger = logging.getLogger(__name__)


class GoalDagWidget(Static):
    """Displays the goal DAG as a text tree."""

    goals: list[dict] = reactive([])

    DEFAULT_CSS = """
    GoalDagWidget {
        width: 1fr;
        height: 1fr;
        border: solid green;
        padding: 0 1;
    }
    """

    def render(self) -> str:
        """Render the goal DAG as styled text."""
        if not self.goals:
            return "[dim]No goals loaded[/]"
        status_colors = {
            "pending": "dim",
            "active": "yellow",
            "validated": "blue",
            "completed": "green",
            "failed": "red",
            "suspended": "magenta",
            "blocked": "orange",
        }
        icons = {
            "pending": "○",
            "active": "◉",
            "completed": "✓",
            "failed": "✗",
            "suspended": "⏸",
            "blocked": "⏺",
        }
        lines = ["[bold green]Goal DAG[/]", ""]
        for g in self.goals:
            status = g.get("status", "pending")
            color = status_colors.get(status, "dim")
            icon = icons.get(status, "○")
            deps = ""
            if g.get("depends_on"):
                deps = f" [dim](deps: {', '.join(g['depends_on'][:3])})[/]"
            informs = ""
            if g.get("informs"):
                informs = f" [dim](→ {', '.join(g['informs'][:3])})[/]"
            gid = g.get("id", "?")
            desc = preview_first(g.get("description", ""), 50)
            lines.append(f"  [{color}]{icon}[/] [{color}]{gid}[/] {desc}{deps}{informs}")
        return "\n".join(lines)


class StatusWidget(Static):
    """Displays overall autopilot status."""

    state: str = reactive("idle")
    active_count: int = reactive(0)
    completed_count: int = reactive(0)
    iteration_count: int = reactive(0)

    DEFAULT_CSS = """
    StatusWidget {
        width: 1fr;
        height: auto;
        border: solid blue;
        padding: 0 1;
        margin-bottom: 1;
    }
    """

    def render(self) -> str:
        """Render the status panel as styled text."""
        parts = [
            f"[bold blue]Status[/]  [{self.state}]",
            f"  Active: {self.active_count}  |  "
            f"Completed: {self.completed_count}  |  "
            f"Iterations: {self.iteration_count}",
        ]
        return "\n".join(parts)


class FindingsWidget(ScrollableContainer):
    """Displays key findings from completed goals."""

    findings: list[str] = reactive([])

    DEFAULT_CSS = """
    FindingsWidget {
        width: 1fr;
        height: 1fr;
        border: solid cyan;
        padding: 0 1;
    }
    """

    def render(self) -> str:
        """Render the findings panel as styled text."""
        if not self.findings:
            return "[dim]No findings yet[/]"
        lines = ["[bold cyan]Findings[/]", ""]
        for i, f in enumerate(self.findings[-20:], 1):
            lines.append(f"  {i}. {preview_first(f, 80)}")
        return "\n".join(lines)


class ControlsWidget(Static):
    """Displays available CLI commands (read-only)."""

    _COMMANDS: ClassVar[list[tuple[str, str]]] = [
        ("soothe autopilot submit 'task'", "Submit task"),
        ("soothe autopilot status", "Check status"),
        ("soothe autopilot list", "List goals"),
        ("soothe autopilot goal <id>", "Goal details"),
        ("soothe autopilot cancel <id>", "Cancel goal"),
        ("soothe autopilot wake", "Exit dreaming"),
        ("soothe autopilot inbox", "View inbox"),
    ]

    DEFAULT_CSS = """
    ControlsWidget {
        width: 1fr;
        height: auto;
        border: solid yellow;
        padding: 0 1;
    }
    """

    def render(self) -> str:
        """Render the controls panel as styled text."""
        lines = ["[bold yellow]Available Commands[/] (use CLI)", ""]
        for cmd, desc in self._COMMANDS:
            lines.append(f"  [bold]{cmd}[/]  [dim]— {desc}[/]")
        return "\n".join(lines)


class AutopilotDashboard(Container):
    """Top-level container for the autopilot dashboard."""

    DEFAULT_CSS = """
    AutopilotDashboard {
        layout: horizontal;
    }
    AutopilotDashboard.narrow-layout {
        layout: vertical;
    }
    """

    def __init__(self, *, is_narrow: bool = False, **kwargs: Any) -> None:
        """Initialize dashboard.

        Args:
            is_narrow: Whether to use vertical layout.
            **kwargs: Passed to parent.
        """
        super().__init__(**kwargs)
        self._is_narrow = is_narrow
        self.goal_dag = GoalDagWidget()
        self.status = StatusWidget()
        self.findings = FindingsWidget()
        self.controls = ControlsWidget()

    def compose(self) -> ComposeResult:
        """Build the dashboard layout."""
        if self._is_narrow:
            yield ScrollableContainer(self.goal_dag, classes="panel")
            yield ScrollableContainer(
                self.status,
                self.controls,
                self.findings,
                classes="side-panel",
            )
        else:
            yield ScrollableContainer(self.goal_dag, classes="panel")
            yield ScrollableContainer(
                self.status,
                self.findings,
                self.controls,
                classes="side-panel",
            )

    def update_goals(self, goals: list[dict]) -> None:
        """Update goal display.

        Args:
            goals: List of goal info dicts.
        """
        self.goal_dag.goals = goals
        active = sum(1 for g in goals if g.get("status") == "active")
        completed = sum(1 for g in goals if g.get("status") == "completed")
        self.status.active_count = active
        self.status.completed_count = completed

    def add_finding(self, text: str) -> None:
        """Add a finding to the findings panel.

        Args:
            text: Finding text to add.
        """
        self.findings.findings = [*self.findings.findings, text]


class AutopilotApp:
    """Manages the autopilot dashboard lifecycle.

    Integrates with the existing TUI infrastructure by providing
    an alternate screen mode.
    """

    def __init__(self, soothe_home: Path | None = None) -> None:
        """Initialize autopilot manager.

        Args:
            soothe_home: Root directory for SOOTHE_HOME.
        """
        from pathlib import Path

        self._soothe_home = soothe_home or Path(SOOTHE_HOME)
        self._dashboard: AutopilotDashboard | None = None

    def get_dashboard(self, *, is_narrow: bool = False) -> AutopilotDashboard:
        """Get or create the dashboard instance.

        Args:
            is_narrow: Whether to use vertical layout.

        Returns:
            Dashboard widget instance.
        """
        if self._dashboard is None:
            self._dashboard = AutopilotDashboard(is_narrow=is_narrow)
        return self._dashboard

    def refresh_from_files(self) -> None:
        """Reload goal state from files and update dashboard."""
        if not self._dashboard:
            return

        goals = self._load_goals()
        self._dashboard.update_goals(goals)

    def _load_goals(self) -> list[dict]:
        """Parse goals from SOOTHE_HOME/autopilot/ files.

        Returns:
            List of goal info dicts.
        """
        autopilot_dir = self._soothe_home / "autopilot"
        if not autopilot_dir.exists():
            return []

        goals = []

        # Check status.json for runtime state
        state_file = autopilot_dir / "status.json"
        if state_file.exists():
            try:
                data = json.loads(state_file.read_text())
                return data.get("goals", [])
            except (json.JSONDecodeError, OSError):
                pass

        # Fallback: parse goal files
        from soothe.utils.goal_parsing import parse_autopilot_goals

        goals.extend(parse_autopilot_goals(autopilot_dir))
        return goals


def _parse_autopilot_files(autopilot_dir: Path) -> list[dict]:
    """Parse goals from GOAL.md/GOALS.md files.

    Args:
        autopilot_dir: Path to autopilot directory.

    Returns:
        List of goal info dicts.
    """
    from soothe.utils.goal_parsing import parse_autopilot_goals

    return parse_autopilot_goals(autopilot_dir)
