"""Tests for the plan quick-view overlay."""

from __future__ import annotations

import re
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
    bare = _plan_quick_view_header(None)
    assert bare.plain == "Plan  ·  Ctrl+t to close"

    with_loop = _plan_quick_view_header("019f17e6-1234-5678-9abc-def012346543")
    assert with_loop.plain == "Plan (019f17e6...6543)  ·  Ctrl+t to close"

    with_hint = _plan_quick_view_header(
        "019f17e6-1234-5678-9abc-def012346543",
        show_enter_hint=True,
    )
    assert (
        with_hint.plain == "Plan (019f17e6...6543)  ·  Enter runs queued goal  ·  Ctrl+t to close"
    )

    with_elapsed = _plan_quick_view_header(
        "019f17e6-1234-5678-9abc-def012346543",
        elapsed="12s",
    )
    assert with_elapsed.plain == "Plan (019f17e6...6543)  ·  12s  ·  Ctrl+t to close"

    with_both = _plan_quick_view_header(
        "019f17e6-1234-5678-9abc-def012346543",
        show_enter_hint=True,
        elapsed="12s",
    )
    assert (
        with_both.plain
        == "Plan (019f17e6...6543)  ·  12s  ·  Enter runs queued goal  ·  Ctrl+t to close"
    )


def test_plan_quick_view_goal_header_uses_target_glyph() -> None:
    """Goal header in plan quick-view renders the 🎯 prefix instead of the dot."""
    tree = CognitionGoalTreeMessage(goal="Ship feature", id="gt-glyph")
    content = tree.plan_quick_view_content()
    assert content.plain.startswith("🎯")
    assert "Ship feature" in content.plain


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
    assert "(45s)" not in content.plain
    assert "3 tools" in content.plain


def test_plan_panel_title_ticks_elapsed_while_loop_open() -> None:
    """Live elapsed belongs in the panel title, not a body status row."""
    tree = CognitionGoalTreeMessage(goal="Ship it", id="gt-running-status")
    tree.mark_loop_started(time() - 12)
    tree.sync_plan_steps([{"id": "STEP-1", "description": "Work"}])
    tree.set_step_phase("STEP-1", "running", description="Work")

    assert tree.loop_elapsed_label() == "12s"
    assert tree._footer_visible is False

    tree._loop_started_at = time() - 13
    assert tree.loop_elapsed_label() == "13s"
    header = _plan_quick_view_header("019f17e6-1234-5678-9abc-def012346543", elapsed="13s")
    assert header.plain == "Plan (019f17e6...6543)  ·  13s  ·  Ctrl+t to close"


def test_plan_panel_elapsed_ticks_between_steps_then_clears_on_done() -> None:
    """Title elapsed keeps ticking between steps; clears when the loop finishes."""
    tree = CognitionGoalTreeMessage(goal="Ship it", id="gt-between-steps")
    tree.mark_loop_started(time() - 20)
    tree.sync_plan_steps(
        [
            {"id": "STEP-1", "description": "Done work"},
            {"id": "STEP-2", "description": "Next work"},
        ]
    )
    tree.complete_step("STEP-1", True, 5_000, 2, "ok")
    # STEP-2 still pending — no step is in ``running``, but the loop is live.
    assert tree._goal_tree_status() == "running"
    assert tree._loop_executing()

    label = tree.loop_elapsed_label()
    assert label is not None
    match = re.search(r"^(\d+)s$", label)
    assert match is not None
    assert int(match.group(1)) >= 20
    assert tree._footer_visible is False

    pos_before = tree._spinner_position
    tree.tick_running_spinner()
    assert tree._spinner_position != pos_before

    tree.set_loop_finished(
        status="done",
        goal_progress="complete",
        completion_summary="All good",
        total_steps=1,
    )
    assert not tree._loop_executing()
    assert tree.loop_elapsed_label() is None
    finished = tree.plan_quick_view_content()
    assert "Done" in finished.plain


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


def test_goal_tree_done_footer_includes_total_duration() -> None:
    """Done status line shows wall-clock or summed step duration."""
    tree = CognitionGoalTreeMessage(goal="Ship", id="gt-dur")
    tree.complete_step("STEP-1", True, 1_200, 2, "ok")
    tree.complete_step("STEP-2", True, 3_400, 1, "ok")

    tree.set_loop_finished(
        status="done",
        goal_progress="complete",
        completion_summary="All good",
        total_steps=2,
    )
    assert "Done · 100% · 2 step(s) · 4.6s · All good" in tree._footer_plain

    tree.set_loop_finished(
        status="done",
        goal_progress="complete",
        completion_summary="All good",
        total_steps=2,
        duration_ms=125_000,
    )
    assert "Done · 100% · 2 step(s) · 2m 5s · All good" in tree._footer_plain

    content = tree.plan_quick_view_content()
    assert "2m 5s" in content.plain


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


def test_overlay_shown_expanded_by_default_on_mount() -> None:
    """Plan panel is visible (expanded) on launch, not collapsed."""
    overlay = PlanQuickViewOverlay()
    overlay._content = MagicMock()
    overlay._header = MagicMock()
    overlay.query_one = MagicMock(return_value=MagicMock())
    overlay.refresh_content = MagicMock()
    overlay.set_interval = MagicMock(return_value=MagicMock())

    overlay.on_mount()

    assert overlay.display is True
    assert overlay.is_expanded
    overlay.refresh_content.assert_called_once()
    overlay.set_interval.assert_called_once()


def test_overlay_hidden_by_default_when_config_disabled() -> None:
    """Plan panel starts collapsed when config sets default_visible=False."""
    overlay = PlanQuickViewOverlay(default_visible=False)
    overlay._content = MagicMock()
    overlay._header = MagicMock()
    overlay.query_one = MagicMock(return_value=MagicMock())
    overlay.refresh_content = MagicMock()
    overlay.set_interval = MagicMock(return_value=MagicMock())

    overlay.on_mount()

    assert not overlay.is_expanded
    overlay.refresh_content.assert_not_called()
    overlay.set_interval.assert_not_called()


def test_plan_panel_css_is_in_flow_not_layered() -> None:
    """Ctrl+t panel must take layout space above thinking/input, not float on a layer."""
    css = PlanQuickViewOverlay.DEFAULT_CSS
    assert "layer:" not in css
    assert "overlay: screen" not in css
    assert "PlanQuickViewOverlay.-expanded" in css
    assert "max-height: 14" in css
    assert "border-left: tall $cognition" in css
    assert "background: transparent" in css
    # No bottom margin — sits flush above the thinking row.
    expanded = css.split("PlanQuickViewOverlay.-expanded")[1].split("}")[0]
    assert "margin: 0 1;" in expanded or "margin: 0 1" in expanded
    assert "margin: 0 1 1" not in expanded


def test_on_mount_source_expands_by_default() -> None:
    """on_mount calls expand() when default_visible is True."""
    import inspect

    source = inspect.getsource(PlanQuickViewOverlay.on_mount)
    assert "self.expand()" in source
    assert "self._default_visible" in source


def test_on_mount_source_respects_config_disabled() -> None:
    """on_mount guards expand() behind _default_visible flag."""
    import inspect

    source = inspect.getsource(PlanQuickViewOverlay.on_mount)
    assert "if self._default_visible:" in source


def test_soothe_app_compose_places_plan_panel_above_bottom_chrome() -> None:
    """Plan panel is a Screen sibling above #bottom-app-container, not nested in it."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[4] / "src/soothe_cli/tui/app/_app.py").read_text(
        encoding="utf-8"
    )
    plan_yield = source.index("PlanQuickViewOverlay(")
    bottom_open = source.index('Container(id="bottom-app-container")')
    thinking = source.index('Container(id="thinking-status")')
    assert plan_yield < bottom_open < thinking
    # Thinking row lives inside bottom chrome, not beside the plan panel.
    assert 'with Container(id="bottom-app-container"):' in source
    bottom_block = source[bottom_open : source.index("yield StatusBar", bottom_open)]
    assert "PlanQuickViewOverlay" not in bottom_block
    assert "thinking-status" in bottom_block


def test_soothe_app_compose_passes_config_default_visible() -> None:
    """compose() passes plan_panel_default_visible from daemon config to overlay."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[4] / "src/soothe_cli/tui/app/_app.py").read_text(
        encoding="utf-8"
    )
    assert "plan_panel_default_visible" in source
    assert "default_visible=plan_visible" in source
