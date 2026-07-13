"""Tests for the plan quick-view overlay."""

from __future__ import annotations

from time import time
from unittest.mock import MagicMock

from soothe_cli.tui.widgets.messages.cognition_goal_tree import CognitionGoalTreeMessage
from soothe_cli.tui.widgets.plan_quick_view_overlay import (
    PlanQuickViewOverlay,
    _plan_quick_view_header,
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


def test_plan_quick_view_header_includes_loop_id_when_available() -> None:
    assert _plan_quick_view_header(None) == "Plan  ·  Ctrl+t to close"
    assert _plan_quick_view_header("loop-123") == "Plan (loop-123)  ·  Ctrl+t to close"


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


def test_plan_quick_view_hides_tool_error_summary_on_successful_step() -> None:
    tree = CognitionGoalTreeMessage(goal="Analyze logs", id="gt-3")
    tree.complete_step(
        "ELR-01",
        True,
        120_000,
        61,
        "Error: Command timed out after 60s. The process group was terminated.",
    )

    content = tree.plan_quick_view_content()

    assert "ELR-01" in content.plain
    assert "61 tools" in content.plain
    assert "timed out" not in content.plain


def test_plan_quick_view_shows_step_dependencies() -> None:
    tree = CognitionGoalTreeMessage(goal="Ship feature", id="gt-deps")
    tree.sync_plan_steps(
        [
            {"id": "STEP-1", "description": "Read files"},
            {"id": "STEP-2", "description": "Apply edits", "dependencies": ["STEP-1"]},
        ]
    )

    content = tree.plan_quick_view_content()

    assert "(→ STEP-1)" in content.plain
    assert "STEP-2" in content.plain


def test_plan_quick_view_running_shows_duration_and_tools() -> None:
    tree = CognitionGoalTreeMessage(goal="Run tools", id="gt-live")
    tree.sync_plan_steps([{"id": "STEP-1", "description": "Execute"}])
    tree.set_step_phase("STEP-1", "running", description="Execute")
    st = tree._steps["STEP-1"]
    st.started_at = time() - 45
    st.tool_call_count = 3

    content = tree.plan_quick_view_content()

    assert "45s" in content.plain
    assert "3 tools" in content.plain


def test_plan_quick_view_dedupes_done_tools_summary() -> None:
    tree = CognitionGoalTreeMessage(goal="Finish", id="gt-dedupe")
    tree.complete_step("STEP-1", True, 72_000, 15, "Done [15 tools]")

    content = tree.plan_quick_view_content()

    assert content.plain.count("15 tools") == 1
    assert "Done [15 tools]" not in content.plain


def test_plan_quick_view_keeps_meaningful_summary() -> None:
    tree = CognitionGoalTreeMessage(goal="Report", id="gt-summary")
    tree.complete_step("STEP-1", True, 2_300, 5, "wrote report to /tmp/out.md")

    content = tree.plan_quick_view_content()

    assert "5 tools" in content.plain
    assert "wrote report" in content.plain


def test_plan_quick_view_clips_long_description_to_line_width() -> None:
    from soothe_cli.tui.config import get_glyphs

    tree = CognitionGoalTreeMessage(goal="Clip", id="gt-clip")
    long_desc = "Inspect and refactor the authentication middleware thoroughly"
    tree.sync_plan_steps([{"id": "STEP-1", "description": long_desc}])
    tree.set_step_phase("STEP-1", "running", description=long_desc)
    st = tree._steps["STEP-1"]
    st.started_at = time() - 10
    st.tool_call_count = 5

    max_width = 60
    content = tree.plan_quick_view_content(max_line_width=max_width)
    gutter = f"{get_glyphs().output_prefix} "
    step_line = next(line for line in content.plain.split("\n") if "STEP-1:" in line)
    body = step_line[len(gutter) :] if step_line.startswith(gutter) else step_line

    assert len(body) <= max_width
    assert "…" in body


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
