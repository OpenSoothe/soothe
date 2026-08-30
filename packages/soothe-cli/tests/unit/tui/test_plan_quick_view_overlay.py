"""Tests for the plan quick-view overlay."""

from __future__ import annotations

import re
from time import time
from unittest.mock import MagicMock, PropertyMock, patch

from soothe_cli.settings import get_glyphs
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
    assert bare.plain == "Orchestrating  ·  Ctrl+t to close"

    with_loop = _plan_quick_view_header("019f17e6-1234-5678-9abc-def012346543")
    assert with_loop.plain == "Orchestrating [6543]  ·  Ctrl+t to close"

    with_hint = _plan_quick_view_header(
        "019f17e6-1234-5678-9abc-def012346543",
        show_enter_hint=True,
    )
    assert with_hint.plain == "Orchestrating [6543]  ·  Enter runs queued goal  ·  Ctrl+t to close"

    with_elapsed = _plan_quick_view_header(
        "019f17e6-1234-5678-9abc-def012346543",
        elapsed="12s",
    )
    assert with_elapsed.plain == "Orchestrating [6543] · 12s  ·  Ctrl+t to close"

    with_both = _plan_quick_view_header(
        "019f17e6-1234-5678-9abc-def012346543",
        show_enter_hint=True,
        elapsed="12s",
    )
    assert (
        with_both.plain
        == "Orchestrating [6543] · 12s  ·  Enter runs queued goal  ·  Ctrl+t to close"
    )


def test_plan_quick_view_header_carries_glyph_and_intake() -> None:
    """Title row is one line: glyph, short loop id, intake, elapsed, hint."""
    tree = CognitionGoalTreeMessage(goal="Ship feature", id="gt-glyph")
    tree.set_intake_label("complex")

    header = _plan_quick_view_header(
        "019ff5a0-1234-5678-9abc-def012348d26",
        prefix=tree.plan_panel_prefix_content(),
        intake=tree.intake_label(),
        elapsed="37s",
    )

    assert header.plain == "◆ Orchestrating [8d26] · complex · 37s  ·  Ctrl+t to close"


def test_plan_quick_view_body_omits_goal_text() -> None:
    """Panel body holds step rows only; the goal lives in the title row above."""
    tree = CognitionGoalTreeMessage(goal="Ship feature", id="gt-body")
    tree.set_intake_label("complex")
    tree.sync_plan_steps([{"id": "STEP-1", "description": "Read files"}])

    plain = tree.plan_quick_view_content().plain

    assert "Ship feature" not in plain
    assert "complex" not in plain
    assert plain.startswith(get_glyphs().output_prefix)
    assert "1: Read files" in plain


def test_plan_quick_view_content_shows_pending_and_running() -> None:
    """Goal tree snapshot includes planned steps."""
    tree = CognitionGoalTreeMessage(goal="Refactor module", max_iterations=3, id="gt-2")
    tree.sync_plan_steps(
        [
            {"id": "STEP-1", "description": "Read files"},
            {"id": "STEP-2", "description": "Apply edits"},
        ]
    )
    tree.set_intake_label("complex")
    tree.set_step_phase("STEP-1", "running", description="Read files")

    content = tree.plan_quick_view_content()

    assert "dependency" not in content.plain
    assert "parallel" not in content.plain
    assert "1:" in content.plain
    assert "2:" in content.plain


def test_plan_quick_view_ignores_invalid_intake_label() -> None:
    """Only minimal/simple/complex reach the panel title."""
    tree = CognitionGoalTreeMessage(goal="Ship feature", id="gt-intake")
    tree.set_intake_label("chitchat")
    tree.set_intake_label("dependency")
    assert tree.intake_label() == ""

    tree.set_intake_label("simple")
    assert tree.intake_label() == "simple"
    assert "simple" in _plan_quick_view_header(None, intake=tree.intake_label()).plain


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

    assert "1:" in content.plain
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

    assert "(→ 1)" in content.plain
    assert "2:" in content.plain


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
    assert header.plain == "Orchestrating [6543] · 13s  ·  Ctrl+t to close"


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


def test_plan_quick_view_header_has_no_tree_gutter() -> None:
    """Panel title carries the goal glyph, never the ``⎿`` body gutter.

    Step/body rows keep the tree glyph; the title row starts flush at column 0
    with the goal status glyph so it reads as a card header.
    """
    header = _plan_quick_view_header(
        "019f17e6-1234-5678-9abc-def012346543",
    )

    assert not header.plain.startswith(get_glyphs().output_prefix)
    assert not header.plain.startswith(" ")
    assert header.plain.startswith("Orchestrating")

    tree = CognitionGoalTreeMessage(goal="Ship it", id="gt-gutter")
    with_glyph = _plan_quick_view_header(
        "019f17e6-1234-5678-9abc-def012346543",
        prefix=tree.plan_panel_prefix_content(),
    )
    assert with_glyph.plain.startswith(f"{get_glyphs().subagent_prefix} Orchestrating")


def test_plan_quick_view_clips_long_description_to_line_width() -> None:
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
    step_line = next(line for line in content.plain.split("\n") if "1:" in line)
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


def test_goal_tree_done_footer_includes_token_suffix() -> None:
    """Done footer appends ``in:`` / ``out:`` totals when tokens were recorded."""
    tree = CognitionGoalTreeMessage(goal="Ship", id="gt-dur-tok")
    tree.complete_step(
        "STEP-1",
        True,
        1_200,
        2,
        "ok",
        input_tokens=1500,
        output_tokens=300,
    )

    tree.set_loop_finished(
        status="done",
        goal_progress="complete",
        completion_summary="All good",
        total_steps=1,
    )
    assert "↑1.5K" in tree._footer_plain
    assert "↓300" in tree._footer_plain
    # Token suffix sits after the summary, joined by the middot separator.
    assert "All good · ↑1.5K ↓300" in tree._footer_plain

    content = tree.plan_quick_view_content()
    assert "↑1.5K" in content.plain
    assert "↓300" in content.plain


def test_goal_tree_done_footer_omits_tokens_when_zero() -> None:
    """Done footer omits the token suffix when no tokens were recorded."""
    tree = CognitionGoalTreeMessage(goal="Ship", id="gt-dur-notok")
    tree.complete_step("STEP-1", True, 1_200, 2, "ok")

    tree.set_loop_finished(
        status="done",
        goal_progress="complete",
        completion_summary="All good",
        total_steps=1,
    )
    assert "↑" not in tree._footer_plain
    assert "↓" not in tree._footer_plain


def test_goal_tree_done_footer_includes_goal_level_orphan_tokens() -> None:
    """Orphan usage routed to the goal accumulator surfaces in the done footer."""
    tree = CognitionGoalTreeMessage(goal="Ship", id="gt-dur-orphan")
    # No step card bound — simulates a parallel-wave usage chunk that arrived
    # before any tool call bound the namespace.
    tree.record_goal_token_usage(2200, 450)

    tree.set_loop_finished(
        status="done",
        goal_progress="complete",
        completion_summary="All good",
        total_steps=0,
    )
    assert "↑2.2K" in tree._footer_plain
    assert "↓450" in tree._footer_plain


def test_overlay_toggle_expands_and_collapses() -> None:
    """Ctrl+t target toggles expanded state and refresh timer."""
    tree = CognitionGoalTreeMessage(goal="Ship it", id="gt-toggle")
    adapter = MagicMock()
    adapter._goal_tree_message = tree
    app = MagicMock()
    app._ui_adapter = adapter

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
    overlay.collapse(forget_preference=True)
    assert not overlay.is_expanded
    assert overlay._preferred_visible is False
    timer.stop.assert_called_once()

    with patch.object(PlanQuickViewOverlay, "app", new_callable=PropertyMock) as mock_app:
        mock_app.return_value = app
        overlay.toggle()
        assert overlay.is_expanded
        assert overlay._preferred_visible is True
        assert overlay._user_pinned is True
        overlay.toggle()
        assert not overlay.is_expanded
        assert overlay._preferred_visible is False
        assert overlay._user_pinned is False


def test_overlay_toggle_without_plan_keeps_preference_collapsed() -> None:
    """Ctrl+t with no active plan stays collapsed but remembers preference."""
    app = MagicMock()
    app._ui_adapter = MagicMock(_goal_tree_message=None)

    overlay = PlanQuickViewOverlay(default_visible=False)
    overlay._content = MagicMock()
    overlay.set_interval = MagicMock(return_value=MagicMock())

    with patch.object(PlanQuickViewOverlay, "app", new_callable=PropertyMock) as mock_app:
        mock_app.return_value = app
        overlay.toggle()

    assert overlay._preferred_visible is True
    assert overlay._user_pinned is True
    assert not overlay.is_expanded
    overlay.set_interval.assert_called_once()


def test_overlay_hides_when_no_active_plan() -> None:
    """Expanded panel collapses instead of showing an empty placeholder."""
    app = MagicMock()
    app._ui_adapter = MagicMock(_goal_tree_message=None)

    overlay = PlanQuickViewOverlay()
    overlay._content = MagicMock()
    overlay._header = MagicMock()
    overlay.add_class("-expanded")
    overlay.display = True
    overlay.set_interval = MagicMock(return_value=MagicMock())

    with patch.object(PlanQuickViewOverlay, "app", new_callable=PropertyMock) as mock_app:
        mock_app.return_value = app
        overlay.refresh_content()

    assert not overlay.is_expanded
    assert overlay.display is False
    overlay._content.update.assert_not_called()


def test_overlay_auto_expands_when_plan_appears() -> None:
    """Preferred-visible panel expands as soon as an executing goal appears."""
    from time import time as _time

    tree = CognitionGoalTreeMessage(goal="Ship it", id="gt-auto")
    # Executing goal: loop started, no terminal footer yet.
    tree.mark_loop_started(_time() - 5)
    assert tree._loop_executing()
    adapter = MagicMock()
    adapter._goal_tree_message = tree
    adapter._current_step_messages = {}
    app = MagicMock()
    app._ui_adapter = adapter
    app._lc_loop_id = None

    overlay = PlanQuickViewOverlay(default_visible=True)
    overlay._content = MagicMock()
    overlay._header = MagicMock()
    overlay.set_interval = MagicMock(return_value=MagicMock())

    with patch.object(PlanQuickViewOverlay, "app", new_callable=PropertyMock) as mock_app:
        mock_app.return_value = app
        overlay.refresh_content()

    assert overlay.is_expanded
    assert overlay.display is True
    overlay._content.update.assert_called()


def test_overlay_collapsed_on_mount_until_plan() -> None:
    """Plan panel starts collapsed on launch; watches for an active plan."""
    overlay = PlanQuickViewOverlay(default_visible=True)
    overlay._content = MagicMock()
    overlay._header = MagicMock()
    overlay.query_one = MagicMock(return_value=MagicMock())
    overlay.refresh_content = MagicMock()
    overlay.set_interval = MagicMock(return_value=MagicMock())

    overlay.on_mount()

    assert overlay.display is False
    assert not overlay.is_expanded
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


def test_overlay_collapse_without_forget_keeps_preference() -> None:
    """Auto-hide when no plan keeps preferred visibility for the next plan."""
    overlay = PlanQuickViewOverlay(default_visible=True)
    overlay.add_class("-expanded")
    overlay.display = True
    overlay.set_interval = MagicMock(return_value=MagicMock())

    overlay.collapse()

    assert not overlay.is_expanded
    assert overlay._preferred_visible is True
    overlay.set_interval.assert_called_once()


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


def test_soothe_app_compose_places_plan_panel_above_bottom_chrome() -> None:
    """Plan panel is a Screen sibling above #bottom-app-container, not nested in it."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[3] / "src/soothe_cli/tui/app/_app.py").read_text(
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
    assert "plan_panel_default_visible" in source
    assert "default_visible=plan_visible" in source


def _executing_tree(*, goal: str = "Ship it", id: str = "gt-exec") -> CognitionGoalTreeMessage:
    """Build a goal tree whose loop is open (executing) with one running step."""
    from time import time as _time

    tree = CognitionGoalTreeMessage(goal=goal, id=id)
    tree.mark_loop_started(_time() - 5)
    tree.sync_plan_steps([{"id": "STEP-1", "description": "Work"}])
    tree.set_step_phase("STEP-1", "running", description="Work")
    assert tree._loop_executing()
    return tree


def _finished_tree(*, goal: str = "Ship it", id: str = "gt-done") -> CognitionGoalTreeMessage:
    """Build a goal tree whose loop has reached a terminal footer."""
    tree = _executing_tree(goal=goal, id=id)
    tree.set_loop_finished(
        status="done",
        goal_progress="complete",
        completion_summary="All good",
        total_steps=1,
    )
    assert not tree._loop_executing()
    return tree


def test_overlay_auto_shows_while_goal_executing() -> None:
    """Default-visible panel expands as soon as a goal is executing."""
    tree = _executing_tree(id="gt-show")
    adapter = MagicMock()
    adapter._goal_tree_message = tree
    adapter._current_step_messages = {}
    app = MagicMock()
    app._ui_adapter = adapter
    app._lc_loop_id = None

    overlay = PlanQuickViewOverlay(default_visible=True)
    overlay._content = MagicMock()
    overlay._header = MagicMock()
    overlay.set_interval = MagicMock(return_value=MagicMock())

    with patch.object(PlanQuickViewOverlay, "app", new_callable=PropertyMock) as mock_app:
        mock_app.return_value = app
        overlay.refresh_content()

    assert overlay.is_expanded
    assert overlay.display is True


def test_overlay_auto_hides_when_goal_completes() -> None:
    """Panel collapses once the goal reaches a terminal footer."""
    tree = _finished_tree(id="gt-hide")
    adapter = MagicMock()
    adapter._goal_tree_message = tree
    adapter._current_step_messages = {}
    app = MagicMock()
    app._ui_adapter = adapter
    app._lc_loop_id = None

    overlay = PlanQuickViewOverlay(default_visible=True)
    overlay._content = MagicMock()
    overlay._header = MagicMock()
    overlay.set_interval = MagicMock(return_value=MagicMock())
    overlay.add_class("-expanded")
    overlay.display = True
    assert overlay.is_expanded

    with patch.object(PlanQuickViewOverlay, "app", new_callable=PropertyMock) as mock_app:
        mock_app.return_value = app
        overlay.refresh_content()

    assert not overlay.is_expanded
    assert overlay.display is False


def test_overlay_auto_hides_when_goal_interrupted() -> None:
    """Panel collapses when the goal is interrupted (error footer)."""
    tree = _executing_tree(id="gt-interrupt")
    tree.set_interrupted("Stream cancelled")
    assert not tree._loop_executing()

    adapter = MagicMock()
    adapter._goal_tree_message = tree
    adapter._current_step_messages = {}
    app = MagicMock()
    app._ui_adapter = adapter
    app._lc_loop_id = None

    overlay = PlanQuickViewOverlay(default_visible=True)
    overlay._content = MagicMock()
    overlay._header = MagicMock()
    overlay.set_interval = MagicMock(return_value=MagicMock())
    overlay.add_class("-expanded")
    overlay.display = True

    with patch.object(PlanQuickViewOverlay, "app", new_callable=PropertyMock) as mock_app:
        mock_app.return_value = app
        overlay.refresh_content()

    assert not overlay.is_expanded
    assert overlay.display is False


def test_overlay_user_pin_keeps_completed_plan_visible() -> None:
    """Ctrl+t open after completion stays until the user closes it."""
    tree = _finished_tree(id="gt-pin")
    adapter = MagicMock()
    adapter._goal_tree_message = tree
    adapter._current_step_messages = {}
    app = MagicMock()
    app._ui_adapter = adapter
    app._lc_loop_id = None

    overlay = PlanQuickViewOverlay(default_visible=True)
    overlay._content = MagicMock()
    overlay._header = MagicMock()
    overlay.set_interval = MagicMock(return_value=MagicMock())
    # Simulate the user opening the panel via Ctrl+t on a finished plan.
    overlay._user_pinned = True
    overlay._preferred_visible = True
    overlay.add_class("-expanded")
    overlay.display = True
    assert overlay.is_expanded

    with patch.object(PlanQuickViewOverlay, "app", new_callable=PropertyMock) as mock_app:
        mock_app.return_value = app
        overlay.refresh_content()

    assert overlay.is_expanded
    assert overlay.display is True
    overlay._content.update.assert_called()


def test_overlay_new_executing_goal_clears_stale_user_pin() -> None:
    """A fresh executing goal cancels a pin left over from a prior plan."""
    tree = _executing_tree(id="gt-fresh")
    adapter = MagicMock()
    adapter._goal_tree_message = tree
    adapter._current_step_messages = {}
    app = MagicMock()
    app._ui_adapter = adapter
    app._lc_loop_id = None

    overlay = PlanQuickViewOverlay(default_visible=True)
    overlay._content = MagicMock()
    overlay._header = MagicMock()
    overlay.set_interval = MagicMock(return_value=MagicMock())
    # Stale pin from a prior completed plan.
    overlay._user_pinned = True
    overlay._preferred_visible = True

    with patch.object(PlanQuickViewOverlay, "app", new_callable=PropertyMock) as mock_app:
        mock_app.return_value = app
        overlay.refresh_content()

    assert overlay.is_expanded
    assert overlay._user_pinned is False


def test_overlay_disabled_config_does_not_auto_show() -> None:
    """When default_visible is False the panel never auto-shows on execution."""
    tree = _executing_tree(id="gt-noshow")
    adapter = MagicMock()
    adapter._goal_tree_message = tree
    adapter._current_step_messages = {}
    app = MagicMock()
    app._ui_adapter = adapter
    app._lc_loop_id = None

    overlay = PlanQuickViewOverlay(default_visible=False)
    overlay._content = MagicMock()
    overlay._header = MagicMock()
    overlay.set_interval = MagicMock(return_value=MagicMock())

    with patch.object(PlanQuickViewOverlay, "app", new_callable=PropertyMock) as mock_app:
        mock_app.return_value = app
        overlay.refresh_content()

    assert not overlay.is_expanded


# ---------------------------------------------------------------------------
# Token display in plan panel
# ---------------------------------------------------------------------------


def test_plan_quick_view_completed_step_shows_in_out_tokens() -> None:
    """Completed step rows display ``in:`` and ``out:`` token counts."""
    tree = CognitionGoalTreeMessage(goal="Ship", id="gt-tok-done")
    tree.complete_step(
        "STEP-1",
        True,
        5_000,
        3,
        "ok",
        input_tokens=1500,
        output_tokens=300,
    )

    content = tree.plan_quick_view_content()

    assert "↑1.5K" in content.plain
    assert "↓300" in content.plain


def test_plan_quick_view_running_step_shows_in_out_tokens() -> None:
    """Running step rows display live token counts synced from step cards."""
    tree = CognitionGoalTreeMessage(goal="Ship", id="gt-tok-run")
    tree.sync_plan_steps([{"id": "STEP-1", "description": "Work"}])
    tree.set_step_phase("STEP-1", "running", description="Work")

    tree.sync_running_live_stats({"STEP-1": (3, None, 800, 120)})

    content = tree.plan_quick_view_content()

    assert "↑800" in content.plain
    assert "↓120" in content.plain


def test_plan_quick_view_step_hides_tokens_when_zero() -> None:
    """Step rows omit token suffix when no tokens have been recorded."""
    tree = CognitionGoalTreeMessage(goal="Ship", id="gt-tok-zero")
    tree.complete_step("STEP-1", True, 5_000, 3, "ok")

    content = tree.plan_quick_view_content()

    assert "↑" not in content.plain
    assert "↓" not in content.plain


def test_plan_panel_header_includes_goal_token_totals() -> None:
    """Panel title shows cumulative ``in:`` / ``out:`` across all steps."""
    tree = CognitionGoalTreeMessage(goal="Ship", id="gt-tok-header")
    tree.complete_step(
        "STEP-1",
        True,
        5_000,
        2,
        "ok",
        input_tokens=1000,
        output_tokens=200,
    )
    tree.complete_step(
        "STEP-2",
        True,
        3_000,
        1,
        "ok",
        input_tokens=500,
        output_tokens=100,
    )

    suffix = tree.goal_token_suffix()
    assert "↑1.5K" in suffix
    assert "↓300" in suffix

    header = _plan_quick_view_header(
        "019f17e6-1234-5678-9abc-def012346543",
        tokens=suffix,
    )
    assert "↑1.5K" in header.plain
    assert "↓300" in header.plain


def test_plan_panel_header_omits_tokens_when_empty() -> None:
    """Panel title has no token suffix when no steps have recorded tokens."""
    tree = CognitionGoalTreeMessage(goal="Ship", id="gt-tok-empty")
    assert tree.goal_token_suffix() == ""

    header = _plan_quick_view_header(
        "019f17e6-1234-5678-9abc-def012346543",
        tokens=tree.goal_token_suffix(),
    )
    assert "↑" not in header.plain
    assert "↓" not in header.plain


def test_goal_tree_snapshot_round_trips_token_fields() -> None:
    """Snapshot and restore preserve per-step token counts."""
    tree = CognitionGoalTreeMessage(goal="Ship", id="gt-tok-snap")
    tree.complete_step(
        "STEP-1",
        True,
        5_000,
        2,
        "ok",
        input_tokens=1200,
        output_tokens=340,
    )

    snap = tree.snapshot_dict()
    assert snap["steps"][0]["input_tokens"] == 1200
    assert snap["steps"][0]["output_tokens"] == 340

    restored = CognitionGoalTreeMessage(goal="Restore", id="gt-tok-restore")
    restored._apply_snapshot(snap)

    st = restored._steps["STEP-1"]
    assert st.input_tokens == 1200
    assert st.output_tokens == 340
    assert restored.goal_token_suffix() == tree.goal_token_suffix()
