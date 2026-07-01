"""RFC-204/RFC-625: Autopilot TUI Dashboard — read-only monitoring view.

Four-panel layout (responsive):
  Wide terminal:  Goal DAG (left) | Status + Findings + Controls (right)
  Narrow terminal: Vertical stack (DAG → Status → Findings → Controls)

All panels are read-only; control actions are done via CLI commands.

Mode-aware DAG rendering:
  - Solo mode: Linear chain (simple list with → arrows)
  - Autopilot mode: Full DAG (with dependencies visualization)
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Literal

from soothe_sdk.client.protocol import preview_first
from textual.containers import Container, ScrollableContainer
from textual.reactive import reactive
from textual.widgets import Static

from soothe_cli.tui.preview_limits import (
    AUTOPILOT_FINDING_LINE_PREVIEW_CHARS,
    AUTOPILOT_FINDINGS_VISIBLE_COUNT,
    AUTOPILOT_GOAL_DESCRIPTION_PREVIEW_CHARS,
    AUTOPILOT_GRAPH_EDGE_PREVIEW_COUNT,
)

if TYPE_CHECKING:
    from textual.app import ComposeResult

DagRenderMode = Literal["solo", "autopilot"]


class GoalDagWidget(Static):
    """Displays the goal DAG as a text tree.

    Mode-aware rendering:
    - Solo mode: Linear chain (goal → goal → goal)
    - Autopilot mode: Full DAG with dependencies
    """

    goals: list[dict] = reactive([])
    mode: DagRenderMode = reactive("solo")

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
            "cancelled": "dim red",
            "suspended": "magenta",
            "blocked": "orange",
        }
        icons = {
            "pending": "○",
            "active": "◉",
            "completed": "✓",
            "failed": "✗",
            "cancelled": "⊘",
            "suspended": "⏸",
            "blocked": "⏺",
        }

        # Mode-aware header
        mode_label = "Solo" if self.mode == "solo" else "Autopilot"
        lines = [f"[bold green]Goal DAG[/] [dim]({mode_label} mode)[/]", ""]

        if self.mode == "solo":
            # Solo mode: Render as linear chain
            self._render_linear_chain(lines, status_colors, icons)
        else:
            # Autopilot mode: Render full DAG
            self._render_full_dag(lines, status_colors, icons)

        return "\n".join(lines)

    def _render_linear_chain(
        self,
        lines: list[str],
        status_colors: dict[str, str],
        icons: dict[str, str],
    ) -> None:
        """Render goals as a linear chain (solo mode)."""
        # Sort goals by created_at for linear chain
        sorted_goals = sorted(self.goals, key=lambda g: g.get("created_at", ""))

        for i, g in enumerate(sorted_goals):
            status = g.get("status", "pending")
            color = status_colors.get(status, "dim")
            icon = icons.get(status, "○")
            gid = g.get("id", "?")
            desc = preview_first(g.get("description", ""), AUTOPILOT_GOAL_DESCRIPTION_PREVIEW_CHARS)

            # Arrow for chain (except last)
            arrow = " → " if i < len(sorted_goals) - 1 else ""
            lines.append(f"  [{color}]{icon}[/] [{color}]{gid}[/] {desc}{arrow}")

    def _render_full_dag(
        self,
        lines: list[str],
        status_colors: dict[str, str],
        icons: dict[str, str],
    ) -> None:
        """Render goals as full DAG with dependencies (autopilot mode)."""
        for g in self.goals:
            status = g.get("status", "pending")
            color = status_colors.get(status, "dim")
            icon = icons.get(status, "○")
            deps = ""
            if g.get("depends_on"):
                deps = f" [dim](deps: {', '.join(g['depends_on'][:AUTOPILOT_GRAPH_EDGE_PREVIEW_COUNT])})[/]"
            informs = ""
            if g.get("informs"):
                informs = (
                    f" [dim](→ {', '.join(g['informs'][:AUTOPILOT_GRAPH_EDGE_PREVIEW_COUNT])})[/]"
                )
            gid = g.get("id", "?")
            desc = preview_first(g.get("description", ""), AUTOPILOT_GOAL_DESCRIPTION_PREVIEW_CHARS)
            lines.append(f"  [{color}]{icon}[/] [{color}]{gid}[/] {desc}{deps}{informs}")


class StatusWidget(Static):
    """Displays overall autopilot status."""

    state: str = reactive("idle")
    mode: DagRenderMode = reactive("solo")
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
        mode_label = "Solo" if self.mode == "solo" else "Autopilot"
        parts = [
            f"[bold blue]Status[/]  [{self.state}]  [dim]({mode_label})[/]",
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
        for i, f in enumerate(self.findings[-AUTOPILOT_FINDINGS_VISIBLE_COUNT:], 1):
            lines.append(f"  {i}. {preview_first(f, AUTOPILOT_FINDING_LINE_PREVIEW_CHARS)}")
        return "\n".join(lines)


class ControlsWidget(Static):
    """Displays available CLI commands (read-only)."""

    mode: DagRenderMode = reactive("solo")

    _COMMANDS: ClassVar[list[tuple[str, str]]] = [
        ("soothe autopilot submit 'task'", "Submit task"),
        ("soothe autopilot status", "Check status"),
        ("soothe autopilot list", "List goals"),
        ("soothe autopilot goal <id>", "Goal details"),
        ("soothe autopilot cancel <id>", "Cancel goal"),
        ("soothe autopilot wake", "Exit dreaming"),
        ("/autopilot <task>", "Submit autopilot job from TUI"),
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
        lines = ["[bold yellow]Available Commands[/] (use CLI or TUI slash command)", ""]
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

    def __init__(
        self, *, is_narrow: bool = False, mode: DagRenderMode = "solo", **kwargs: Any
    ) -> None:
        """Initialize dashboard.

        Args:
            is_narrow: Whether to use vertical layout.
            mode: Initial DAG render mode (solo or autopilot).
            **kwargs: Passed to parent.
        """
        super().__init__(**kwargs)
        self._is_narrow = is_narrow
        self._mode: DagRenderMode = mode
        self.goal_dag = GoalDagWidget()
        self.status = StatusWidget()
        self.findings = FindingsWidget()
        self.controls = ControlsWidget()
        # Set initial mode on widgets
        self.goal_dag.mode = mode
        self.status.mode = mode
        self.controls.mode = mode

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

    def set_mode(self, mode: DagRenderMode) -> None:
        """Set DAG render mode and propagate to widgets.

        Args:
            mode: DAG render mode (solo or autopilot).
        """
        self._mode = mode
        self.goal_dag.mode = mode
        self.status.mode = mode
        self.controls.mode = mode

    def get_mode(self) -> DagRenderMode:
        """Get current DAG render mode.

        Returns:
            Current mode (solo or autopilot).
        """
        return self._mode

    def toggle_mode(self) -> DagRenderMode:
        """Toggle between solo and autopilot mode.

        Returns:
            New mode after toggle.
        """
        new_mode = "autopilot" if self._mode == "solo" else "solo"
        self.set_mode(new_mode)
        return new_mode

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


def _parse_autopilot_files(autopilot_dir: Path) -> list[dict]:
    """Parse goals from GOAL.md/GOALS.md files.

    Args:
        autopilot_dir: Path to autopilot directory.

    Returns:
        List of goal info dicts.
    """
    from soothe_sdk.utils import parse_autopilot_goals

    return parse_autopilot_goals(autopilot_dir)
