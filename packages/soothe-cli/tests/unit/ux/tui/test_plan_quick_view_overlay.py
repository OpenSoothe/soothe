"""Tests for the plan quick-view overlay."""

from __future__ import annotations

from unittest.mock import MagicMock

from soothe_cli.tui.widgets.messages.cognition_goal_tree import CognitionGoalTreeMessage
from soothe_cli.tui.widgets.plan_quick_view_overlay import (
    PlanQuickViewOverlay,
    get_live_goal_tree,
)


def test_get_live_goal_tree_reads_adapter() -> None:
    """Overlay resolves the active goal tree from the UI adapter."""
    tree = CognitionGoalTreeMessage(goal="Ship it", id="gt-1")
    adapter = MagicMock()
    adapter._goal_tree_message = tree
    app = MagicMock()
    app._ui_adapter = adapter

    assert get_live_goal_tree(app) is tree


def test_plan_quick_view_content_shows_pending_and_running() -> None:
    """Goal tree snapshot includes planned steps and execution mode."""
    tree = CognitionGoalTreeMessage(goal="Refactor module", max_iterations=3, id="gt-2")
    tree.sync_plan_steps(
        [
            {"id": "STEP-1", "description": "Read files"},
            {"id": "STEP-2", "description": "Apply edits"},
        ]
    )
    tree.set_execution_mode("dependency")
    tree.set_step_phase("STEP-1", "running", description="Read files")

    content = tree.plan_quick_view_content()

    assert "Refactor module" in content.plain
    assert "dependency" in content.plain
    assert "STEP-1" in content.plain
    assert "STEP-2" in content.plain


def test_overlay_toggle_expands_and_collapses() -> None:
    """Ctrl+t target toggles expanded state and refresh timer."""
    overlay = PlanQuickViewOverlay()
    overlay.display = True
    overlay._content = MagicMock()
    overlay.refresh_content = MagicMock()
    overlay.set_interval = MagicMock(return_value=MagicMock())

    overlay.expand()
    assert overlay.is_expanded
    overlay.set_interval.assert_called_once()
    overlay.refresh_content.assert_called_once()

    timer = overlay.set_interval.return_value
    overlay.collapse()
    assert not overlay.is_expanded
    timer.stop.assert_called_once()

    overlay.toggle()
    assert overlay.is_expanded
    overlay.toggle()
    assert not overlay.is_expanded
