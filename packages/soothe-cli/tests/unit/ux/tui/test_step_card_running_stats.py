"""Running status line shows total tool/task counts per step and task branch."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from soothe_cli.runtime.state.step_router import StepTaskRouter
from soothe_cli.tui import theme
from soothe_cli.tui.widgets.messages import CognitionStepMessage


def _mock_theme_colors() -> MagicMock:
    """Create a mock theme colors object for tests."""
    colors = MagicMock()
    colors.warning = "#ff0000"
    colors.cognition = "#00ff00"
    colors.foreground = "#000000"
    colors.muted = "#888888"
    colors.error = "#ff0000"
    colors.primary = "#0000ff"
    colors.success = "#00ff00"
    return colors


def _extract_content_text(content: object) -> str:
    """Extract plain text from a Textual Content object."""
    if hasattr(content, "plain"):
        return content.plain
    return str(content)


def test_stats_title_suffix_counts_main_agent_tools() -> None:
    card = CognitionStepMessage("ABC-01", "Scan workspace", id="stp-stats")
    card.add_tool_call("ABC_01:s:grep:0", "grep", {"pattern": "x"})
    card.add_tool_call("ABC_01:s:grep:1", "grep", {"pattern": "x"})
    card.add_tool_call("ABC_01:s:grep:2", "grep", {"pattern": "y"})
    card.add_tool_call("ABC_01:s:glob:0", "glob", {"pattern": "**/*"})
    assert card._stats_title_suffix() == " · 4 tools"


def test_stats_ignore_unified_ids_for_other_steps() -> None:
    card = CognitionStepMessage("ABC-01", "Scan workspace", id="stp-stats")
    card.add_tool_call("XYZ_99:s:glob:0", "glob", {"pattern": "**/*"})
    assert card._stats_title_suffix() == ""


def test_status_tool_stats_suffix_prefers_tracked_when_server_count_lower() -> None:
    card = CognitionStepMessage("ABC-01", "Scan", id="stp-done")
    card.add_tool_call("ABC_01:s:grep:0", "grep", {})
    card.add_tool_call("ABC_01:s:grep:1", "grep", {})
    card.add_tool_call("ABC_01:s:glob:0", "glob", {})
    suffix = card._status_tool_stats_suffix(fallback_count=1)
    assert suffix == " · 3 tools"
    assert "1 tool" not in suffix


def test_status_tool_stats_suffix_ignores_inflated_server_count_when_tracked() -> None:
    """Server fallback may include subgraph tools; tracked main-only rows win."""
    card = CognitionStepMessage("ABC-01", "Scan", id="stp-server")
    card.add_tool_call("ABC_01:s:grep:0", "grep", {})
    suffix = card._status_tool_stats_suffix(fallback_count=5)
    assert suffix == " · 1 tool"


def test_status_tool_stats_suffix_ignores_server_count_for_task_delegated_step() -> None:
    card = CognitionStepMessage("ABC-01", "Scan", id="stp-delegated")
    card.add_tool_call(
        "ABC_01:s:task:0",
        "task",
        {"subagent_type": "deep_research", "description": "scan"},
        is_task_row=True,
    )
    suffix = card._status_tool_stats_suffix(fallback_count=8)
    assert suffix == " · 1 task"
    assert "8 tools" not in suffix


def test_status_tool_stats_suffix_falls_back_to_total_when_untracked() -> None:
    card = CognitionStepMessage("ABC-01", "Scan", id="stp-fallback")
    assert card._status_tool_stats_suffix(fallback_count=3) == " · 3 tools"


def test_stats_same_unified_id_not_double_counted() -> None:
    card = CognitionStepMessage("ABC-01", "Scan", id="stp-stream")
    card.add_tool_call("ABC_01:s:glob:0", "glob", {})
    card.update_tool_args("ABC_01:s:glob:0", {"pattern": "a"})
    assert card._stats_title_suffix() == " · 1 tool"
    card.add_tool_call("ABC_01:s:glob:1", "glob", {"pattern": "b"})
    assert card._stats_title_suffix() == " · 2 tools"


def test_route_pending_subgraph_tools_attaches_to_step_card() -> None:
    router = StepTaskRouter()
    router.on_step_started("YKF-01")
    router.register_task_spawn("YKF_01:s:task:0", "deep_research", step_id="YKF-01")
    router.on_subgraph_namespace(("tools:sub",))

    step = MagicMock()
    step.has_tool_call_row.return_value = False
    step_cards = {"YKF-01": step}
    tool_to_step: dict[str, object] = {}
    display: dict[str, object] = {}

    router.buffer_subgraph_tool(
        ns_key=("tools:sub",),
        lookup_id="raw-glob-1",
        display_key="YKF_01:t0:glob:1",
        tool_name="glob",
        args={"pattern": "**/*"},
    )
    routed = router.route_pending_subgraph_tools(step_cards, tool_to_step, display)
    assert routed == 1
    step.add_tool_call.assert_called_once()
    assert tool_to_step["YKF_01:t0:glob:1"] is step


def test_stats_include_main_tools_and_task_delegations() -> None:
    card = CognitionStepMessage("ABC-01", "Scan", id="stp-nested")
    card.add_tool_call("ABC_01:s:grep:0", "grep", {})
    card.add_tool_call(
        "ABC_01:s:task:0",
        "task",
        {"subagent_type": "deep_research", "description": "scan"},
        is_task_row=True,
    )
    card.add_tool_call(
        "ABC_01:t0:glob:1",
        "glob",
        {"pattern": "**/*"},
    )
    suffix = card._stats_title_suffix()
    assert suffix == " · 1 tool, 1 task"


def test_route_pending_main_tools_single_active_step_without_unified_id() -> None:
    router = StepTaskRouter()
    router.on_step_started("ONLY-01")
    step = MagicMock()
    step.has_tool_call_row.return_value = False
    cards = {"ONLY-01": step}
    tool_to_step: dict[str, object] = {}
    display: dict[str, object] = {}

    router.buffer_main_tool("legacy-call-1", "grep", {"pattern": "a"})
    assert router.route_pending_main_tools(cards, tool_to_step, display) == 1
    step.add_tool_call.assert_called_once()


def test_running_animation_includes_tool_stats_in_status_line() -> None:
    """Stats appear in the running status line during animation, not just in _stats_title_suffix()."""
    card = CognitionStepMessage("RUN-01", "Deep Research workspace", id="step-run")

    card.add_tool_call("RUN_01:s:grep:0", "grep", {"pattern": "TODO"})
    card.add_tool_call("RUN_01:s:grep:1", "grep", {"pattern": "FIXME"})
    card.add_tool_call("RUN_01:s:glob:0", "glob", {"pattern": "**/*.py"})

    assert card._stats_title_suffix() == " · 3 tools"

    card._status = "running"
    card._start_time = 0.0

    mock_status_widget = MagicMock()
    card._status_widget = mock_status_widget

    with (
        patch(
            "soothe_cli.tui.widgets.messages.cognition_step._is_widget_animation_visible",
            return_value=True,
        ),
        patch.object(theme, "get_theme_colors", return_value=_mock_theme_colors()),
    ):
        card._update_running_animation()

    assert mock_status_widget.update.called
    update_call_arg = mock_status_widget.update.call_args[0][0]
    text = _extract_content_text(update_call_arg)

    assert "3 tools" in text, f"Running status line should include 3 tools, got: {text!r}"
    assert "Running..." in text, f"Running status line should show 'Running...', got: {text!r}"


def test_running_animation_updates_stats_dynamically() -> None:
    """Stats in running status line update when new tools are added during running state."""
    card = CognitionStepMessage("DYN-01", "Dynamic stats", id="step-dyn")

    card.add_tool_call("DYN_01:s:read_file:0", "read_file", {"path": "a.py"})

    card._status = "running"
    card._start_time = 0.0
    mock_status_widget = MagicMock()
    card._status_widget = mock_status_widget

    with (
        patch(
            "soothe_cli.tui.widgets.messages.cognition_step._is_widget_animation_visible",
            return_value=True,
        ),
        patch.object(theme, "get_theme_colors", return_value=_mock_theme_colors()),
    ):
        card._update_running_animation()
        first_call_arg = mock_status_widget.update.call_args[0][0]
        first_text = _extract_content_text(first_call_arg)
        assert "1 tool" in first_text

        card.add_tool_call("DYN_01:s:read_file:1", "read_file", {"path": "b.py"})
        card.add_tool_call("DYN_01:s:grep:0", "grep", {"pattern": "class"})

        mock_status_widget.update.reset_mock()
        card._update_running_animation()
        second_call_arg = mock_status_widget.update.call_args[0][0]
        second_text = _extract_content_text(second_call_arg)

        assert "3 tools" in second_text, f"Stats should reflect 3 tools, got: {second_text!r}"


def test_running_animation_shows_no_stats_when_no_tools() -> None:
    """Running status line works correctly even with zero tool calls."""
    card = CognitionStepMessage("EMPTY-01", "No tools step", id="step-empty")

    assert card._stats_title_suffix() == ""

    card._status = "running"
    card._start_time = 0.0
    mock_status_widget = MagicMock()
    card._status_widget = mock_status_widget

    with (
        patch(
            "soothe_cli.tui.widgets.messages.cognition_step._is_widget_animation_visible",
            return_value=True,
        ),
        patch.object(theme, "get_theme_colors", return_value=_mock_theme_colors()),
    ):
        card._update_running_animation()
        call_arg = mock_status_widget.update.call_args[0][0]
        text = _extract_content_text(call_arg)

    assert "Running..." in text
    assert "tool" not in text
    assert " · " not in text


def test_running_animation_includes_elapsed_time() -> None:
    """Running status line shows elapsed time when start_time is set."""
    from time import time

    card = CognitionStepMessage("TIME-01", "Time step", id="step-time")

    card.add_tool_call("TIME_01:s:read_file:0", "read_file", {"path": "test.py"})

    card._status = "running"
    card._start_time = time() - 45.0

    mock_status_widget = MagicMock()
    card._status_widget = mock_status_widget

    with (
        patch(
            "soothe_cli.tui.widgets.messages.cognition_step._is_widget_animation_visible",
            return_value=True,
        ),
        patch.object(theme, "get_theme_colors", return_value=_mock_theme_colors()),
    ):
        card._update_running_animation()
        call_arg = mock_status_widget.update.call_args[0][0]
        text = _extract_content_text(call_arg)

    assert "Running..." in text
    assert "(" in text and ")" in text, f"Elapsed time should be shown, got: {text!r}"
    assert "1 tool" in text


def test_running_animation_returns_early_when_not_running_status() -> None:
    """_update_running_animation does nothing when status is not 'running'."""
    card = CognitionStepMessage("SKIP-01", "Skip step", id="step-skip")
    card.add_tool_call("SKIP_01:s:grep:0", "grep", {"pattern": "x"})

    card._status = "pending"
    mock_status_widget = MagicMock()
    card._status_widget = mock_status_widget

    card._update_running_animation()
    assert not mock_status_widget.update.called


def test_running_animation_returns_early_when_status_widget_is_none() -> None:
    """_update_running_animation does nothing when _status_widget is None."""
    card = CognitionStepMessage("NO-WIDGET-01", "No widget step", id="step-no-widget")
    card.add_tool_call("NO_WIDGET_01:s:grep:0", "grep", {"pattern": "x"})

    card._status = "running"
    card._status_widget = None

    card._update_running_animation()


def test_no_duplicate_tool_rows_in_activity_preview() -> None:
    """Tool rows appear once in activity preview, not duplicated across child_rows and orphan_preview."""
    card = CognitionStepMessage("DUP-01", "Test duplicates", id="step-dup")

    card.add_tool_call(
        "DUP_01:s:task:0",
        "task",
        {"subagent_type": "deep_research", "description": "scan"},
        is_task_row=True,
    )

    card.add_tool_call(
        "DUP_01:t0:glob:1",
        "glob",
        {"pattern": "**/*"},
    )

    task_rows = card._iter_task_delegation_rows()
    assert len(task_rows) == 1

    # IG-513: No more children_by_task - subgraph tools route to SubAgent cards


def test_no_duplicate_subgraph_tools_in_main_preview() -> None:
    """IG-513: Subgraph tools (type_code 't') never appear in main_preview stats."""
    card = CognitionStepMessage("MAIN-01", "Test main preview", id="step-main")

    card.add_tool_call("MAIN_01:s:grep:0", "grep", {"pattern": "x"})
    card.add_tool_call("MAIN_01:t0:glob:1", "glob", {"pattern": "**/*"})

    main_preview = card._main_agent_tool_rows_for_preview()
    assert len(main_preview) == 1
    assert main_preview[0].tool_call_id == "MAIN_01:s:grep:0"

    # IG-513: Subgraph tools route to SubAgent cards, not step main_preview


def test_tool_stats_show_immediately_when_widget_not_visible() -> None:
    """Tool count shows in status line immediately even when widget is not yet visible.

    This tests the fix for real-time tool count display: when tool calls arrive
    during a running step, `_sync_step_card_surface` should update the status
    line immediately (bypassing the visibility check) so users see the count
    in real-time, not only when the step finishes.
    """
    card = CognitionStepMessage("INVIS-01", "Invisible widget step", id="step-invis")

    # Set up running state BEFORE any visibility check would pass
    card._status = "running"
    card._start_time = 0.0
    mock_status_widget = MagicMock()
    card._status_widget = mock_status_widget

    # Add tool calls while widget is NOT visible (visibility returns False)
    with (
        patch(
            "soothe_cli.tui.widgets.messages.cognition_step._is_widget_animation_visible",
            return_value=False,
        ),
        patch.object(theme, "get_theme_colors", return_value=_mock_theme_colors()),
    ):
        # Adding tool calls should trigger immediate status update via _sync_step_card_surface
        card.add_tool_call("INVIS_01:s:grep:0", "grep", {"pattern": "test"})
        card.add_tool_call("INVIS_01:s:glob:1", "glob", {"pattern": "*.py"})

        # Verify the status widget was updated (showing real-time stats)
        assert mock_status_widget.update.called
        call_arg = mock_status_widget.update.call_args[0][0]
        text = _extract_content_text(call_arg)

        # Should show 2 tools immediately, even though widget is "not visible"
        assert "2 tools" in text, f"Status line should show '2 tools' immediately, got: {text!r}"
        assert "Running..." in text

    # The animation timer callback should NOT update when not visible
    mock_status_widget.update.reset_mock()
    card._update_running_animation()
    # Should NOT have called update because visibility check returned False
    assert not mock_status_widget.update.called, "Animation should skip when not visible"


def test_sync_running_status_text_bypasses_visibility_check() -> None:
    """_sync_running_status_text updates status immediately regardless of visibility."""
    card = CognitionStepMessage("BYPASS-01", "Bypass visibility", id="step-bypass")

    card._status = "running"
    card._start_time = 0.0
    mock_status_widget = MagicMock()
    card._status_widget = mock_status_widget

    card.add_tool_call("BYPASS_01:s:read_file:0", "read_file", {"path": "a.py"})
    card.add_tool_call("BYPASS_01:s:read_file:1", "read_file", {"path": "b.py"})

    # Directly call _sync_running_status_text - should always update
    with (
        patch(
            "soothe_cli.tui.widgets.messages.cognition_step._is_widget_animation_visible",
            return_value=False,
        ),
        patch.object(theme, "get_theme_colors", return_value=_mock_theme_colors()),
    ):
        card._sync_running_status_text()

    assert mock_status_widget.update.called
    text = _extract_content_text(mock_status_widget.update.call_args[0][0])
    assert "2 tools" in text, f"Should show 2 tools even with visibility=False, got: {text!r}"


def test_refresh_tools_display_syncs_status_when_animation_not_visible() -> None:
    """Surface sync must refresh running status even off-screen."""
    card = CognitionStepMessage("REFRESH-01", "Tools refresh", id="step-refresh")

    card._status = "running"
    card._start_time = 0.0
    mock_status_widget = MagicMock()
    card._status_widget = mock_status_widget
    card._tools_widget = MagicMock()
    card._activity_widget = MagicMock()

    card.add_tool_call("REFRESH_01:s:grep:0", "grep", {"pattern": "foo"})
    mock_status_widget.update.reset_mock()

    with (
        patch(
            "soothe_cli.tui.widgets.messages.cognition_step._is_widget_animation_visible",
            return_value=False,
        ),
        patch.object(theme, "get_theme_colors", return_value=_mock_theme_colors()),
    ):
        card._sync_step_card_surface()

    assert mock_status_widget.update.called
    text = _extract_content_text(mock_status_widget.update.call_args[0][0])
    assert "1 tool" in text, f"Footer status should show 1 tool after surface sync, got: {text!r}"
    assert "Running..." in text


def test_main_only_step_activity_has_no_running_line() -> None:
    """Main-agent-only steps show Running on footer only, not duplicated in activity tree."""
    card = CognitionStepMessage("MAIN-01", "Direct tools", id="step-main-branch")
    card.add_tool_call("MAIN_01:s:grep:0", "grep", {"pattern": "foo"})
    card.add_tool_call("MAIN_01:s:glob:1", "glob", {"pattern": "**/*"})
    card._status = "running"
    card._start_time = 0.0
    content = str(card._step_task_activity_content())
    # Preview shows the latest tools (up to 2); both fit without overflow.
    assert "Glob" in content
    assert "Grep" in content
    assert "+1 more tool" not in content
    assert "Running..." not in content
    assert card._stats_title_suffix() == " · 2 tools"


def test_deferred_running_set_running_refreshes_task_activity_panel() -> None:
    """Tools added before mount must paint branch status + footer on set_running()."""
    from soothe_cli.runtime.state.step_router import StepTaskRouter

    card = CognitionStepMessage("DEF-01", "Deferred mount", id="step-deferred")
    router = StepTaskRouter()
    card.add_tool_call("DEF_01:s:grep:0", "grep", {"pattern": "x"})
    router.maybe_promote_step_to_running(
        card,
        "DEF_01:s:grep:0",
        step_cards={"DEF-01": card},
    )
    assert card._deferred_running is True
    assert card._status == "running"

    mock_status = MagicMock()
    mock_notes = MagicMock()
    card._status_widget = mock_status
    card._start_time = 0.0

    def fake_query(sel: str, _cls: type) -> MagicMock:
        if "subagent-notes" in sel:
            return mock_notes
        if "status" in sel:
            return mock_status
        return MagicMock()

    card.query_one = fake_query  # type: ignore[method-assign]

    with patch.object(theme, "get_theme_colors", return_value=_mock_theme_colors()):
        card.set_running()

    assert mock_notes.update.called, "Task activity panel should refresh after deferred mount"
    notes_text = _extract_content_text(mock_notes.update.call_args[0][0])
    assert "Grep" in notes_text or "grep" in notes_text.lower()
    assert "Running..." not in notes_text, (
        "Main-only activity tree must not duplicate footer Running"
    )
    assert mock_status.update.called
    status_text = _extract_content_text(mock_status.update.call_args[0][0])
    assert "1 tool" in status_text, f"Footer should show tool count, got: {status_text!r}"
