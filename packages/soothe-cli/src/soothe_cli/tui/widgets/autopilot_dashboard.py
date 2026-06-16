"""RFC-204/RFC-625: Autopilot TUI Dashboard — read-only monitoring view.

Four-panel layout (responsive):
  Wide terminal:  Goal DAG (left) | Status + Findings + Controls (right)
  Narrow terminal: Vertical stack (DAG → Status → Findings → Controls)

All panels are read-only; control actions are done via CLI commands.

Mode-aware DAG rendering:
  - Solo mode: Linear chain (simple list with → arrows)
  - Autopilot mode: Full DAG (with dependencies visualization)

RFC-625 §9: GoalDagUpdatesCard provides delta view with event subscription.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Literal

from soothe_sdk.client.config import SOOTHE_HOME
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

logger = logging.getLogger(__name__)

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
        ("/autopilot-toggle", "Toggle solo/autopilot mode"),
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
        mode_hint = "Switch to Autopilot" if self.mode == "solo" else "Switch to Solo"
        lines = ["[bold yellow]Available Commands[/] (use CLI)", ""]
        for cmd, desc in self._COMMANDS:
            # Highlight mode toggle based on current state
            if cmd == "/autopilot-toggle":
                lines.append(f"  [bold cyan]{cmd}[/]  [dim]— {mode_hint}[/]")
            else:
                lines.append(f"  [bold]{cmd}[/]  [dim]— {desc}[/]")
        return "\n".join(lines)


# ── RFC-625 §9: GoalDagUpdatesCard (delta view with events) ───────────────────────


class DagUpdateEntry:
    """One DAG update event entry."""

    def __init__(
        self,
        goal_id: str,
        event_type: str,
        description: str = "",
        timestamp: datetime | None = None,
    ) -> None:
        self.goal_id = goal_id
        self.event_type = event_type  # created, completed, failed, removed, decomposed
        self.description = description
        self.timestamp = timestamp or datetime.now(UTC)

    def format_age(self) -> str:
        """Format age as human-readable string."""
        now = datetime.now(UTC)
        delta = now - self.timestamp
        seconds = int(delta.total_seconds())
        if seconds < 10:
            return "now"
        if seconds < 60:
            return f"{seconds}s ago"
        if seconds < 3600:
            return f"{seconds // 60}m ago"
        return f"{seconds // 3600}h ago"


class GoalDagUpdatesCard(Static):
    """TUI card displaying DAG updates (delta view, RFC-625 §9).

    Shows recent goal lifecycle events in a compact format.
    Toggle between compact (recent updates) and expanded (mini-DAG tree) views.

    Subscribe to InternalEventBus events:
    - goal_created
    - goal_completed
    - goal_failed
    - goal_removed
    - goal_decomposed
    """

    MAX_UPDATES: ClassVar[int] = 10  # Maximum updates to display in compact view
    updates: list[DagUpdateEntry] = reactive([])
    expanded: bool = reactive(False)
    goals: list[dict] = reactive([])  # Full goal list for expanded view

    DEFAULT_CSS = """
    GoalDagUpdatesCard {
        width: 1fr;
        height: auto;
        border: solid green;
        padding: 0 1;
        margin-bottom: 1;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        """Initialize updates card."""
        super().__init__(**kwargs)
        self._updates: list[DagUpdateEntry] = []

    def render(self) -> str:
        """Render the updates card."""
        if self.expanded:
            return self._render_expanded()
        return self._render_compact()

    def _render_compact(self) -> str:
        """Render recent updates list (compact view)."""
        header = "[bold green]Goal DAG Updates[/] [dim][Toggle: E][/]"
        if not self.updates:
            return f"{header}\n[dim]  No updates yet[/]"

        lines = [header, ""]
        # Show most recent updates
        for entry in self.updates[-self.MAX_UPDATES :]:
            icon = self._event_icon(entry.event_type)
            color = self._event_color(entry.event_type)
            desc_preview = preview_first(entry.description, 40)
            lines.append(
                f"  [{color}]{icon}[/] [{color}]{entry.goal_id}[/] {entry.event_type} {desc_preview} [dim]{entry.format_age()}[/]"
            )
        return "\n".join(lines)

    def _render_expanded(self) -> str:
        """Render mini-DAG tree (expanded view)."""
        header = "[bold green]Goal DAG[/] [dim][Toggle: E][/]"
        if not self.goals:
            return f"{header}\n[dim]  No goals loaded[/]"

        lines = [header, ""]
        # Build tree from goals
        roots = [g for g in self.goals if not g.get("depends_on")]
        self._render_tree(roots, lines, indent=0)
        return "\n".join(lines)

    def _render_tree(
        self,
        goals: list[dict],
        lines: list[str],
        indent: int,
    ) -> None:
        """Render goal tree recursively."""
        indent_str = "  " * indent
        for g in goals:
            status = g.get("status", "pending")
            icon = self._status_icon(status)
            color = self._status_color(status)
            desc_preview = preview_first(g.get("description", ""), 40)
            lines.append(
                f"{indent_str}[{color}]{icon}[/] [{color}]{g.get('id', '?')}[/] {desc_preview}"
            )
            # Render children
            children = [cg for cg in self.goals if g.get("id") in cg.get("depends_on", [])]
            if children:
                self._render_tree(children, lines, indent + 1)

    def _event_icon(self, event_type: str) -> str:
        """Get icon for event type."""
        return {
            "created": "+",
            "completed": "✓",
            "failed": "✗",
            "removed": "−",
            "decomposed": "↗",
            "activated": "→",
        }.get(event_type, "○")

    def _event_color(self, event_type: str) -> str:
        """Get color for event type."""
        return {
            "created": "cyan",
            "completed": "green",
            "failed": "red",
            "removed": "dim red",
            "decomposed": "blue",
            "activated": "yellow",
        }.get(event_type, "dim")

    def _status_icon(self, status: str) -> str:
        """Get icon for goal status."""
        return {
            "pending": "○",
            "active": "◉",
            "completed": "✓",
            "failed": "✗",
            "cancelled": "⊘",
        }.get(status, "○")

    def _status_color(self, status: str) -> str:
        """Get color for goal status."""
        return {
            "pending": "dim",
            "active": "yellow",
            "completed": "green",
            "failed": "red",
            "cancelled": "dim red",
        }.get(status, "dim")

    def toggle_expand(self) -> None:
        """Toggle between compact and expanded view."""
        self.expanded = not self.expanded

    def add_update(
        self,
        goal_id: str,
        event_type: str,
        description: str = "",
    ) -> None:
        """Add a new DAG update entry.

        Args:
            goal_id: Goal ID involved.
            event_type: Event type (created, completed, failed, etc).
            description: Optional description preview.
        """
        entry = DagUpdateEntry(goal_id, event_type, description)
        self._updates.append(entry)
        # Trim to MAX_UPDATES * 2 to keep some history
        if len(self._updates) > self.MAX_UPDATES * 2:
            self._updates = self._updates[-self.MAX_UPDATES :]
        self.updates = self._updates.copy()

    def update_goals(self, goals: list[dict]) -> None:
        """Update full goal list for expanded view."""
        self.goals = goals


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
        from soothe_sdk.utils import parse_autopilot_goals

        goals.extend(parse_autopilot_goals(autopilot_dir))
        return goals


def _parse_autopilot_files(autopilot_dir: Path) -> list[dict]:
    """Parse goals from GOAL.md/GOALS.md files.

    Args:
        autopilot_dir: Path to autopilot directory.

    Returns:
        List of goal info dicts.
    """
    from soothe_sdk.utils import parse_autopilot_goals

    return parse_autopilot_goals(autopilot_dir)
