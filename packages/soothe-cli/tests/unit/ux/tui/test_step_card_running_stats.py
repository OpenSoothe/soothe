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
    """Server fallback is ignored once local tool rows exist."""
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
    # Footer total includes subgraph tools under the task.
    assert suffix == " · 2 tools, 1 task"


def test_running_task_line_shows_subgraph_tool_count() -> None:
    card = CognitionStepMessage("ABC-01", "Scan", id="stp-task-count")
    card._status = "running"
    card.add_tool_call(
        "ABC_01:s:task:0",
        "task",
        {"subagent_type": "deep_research", "description": "scan"},
        is_task_row=True,
    )
    card.add_tool_call("ABC_01:t0:glob:1", "glob", {"pattern": "**/*"})
    card.add_tool_call("ABC_01:t0:grep:2", "grep", {"pattern": "x"})
    text = str(card._step_task_activity_content())
    assert "Deep Research(scan) · 2 tools" in text
    assert "Glob(" not in text
    assert "Grep(" not in text


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


def test_running_animation_includes_tool_stats_in_title() -> None:
    """Compact tool/task counts appear on the step title during animation (IG-664)."""
    card = CognitionStepMessage("RUN-01", "Deep Research workspace", id="step-run")

    card.add_tool_call("RUN_01:s:grep:0", "grep", {"pattern": "TODO"})
    card.add_tool_call("RUN_01:s:grep:1", "grep", {"pattern": "FIXME"})
    card.add_tool_call("RUN_01:s:glob:0", "glob", {"pattern": "**/*.py"})

    assert card._stats_title_suffix() == " · 3 tools"

    card._status = "running"
    card._start_time = 0.0
    mock_header = MagicMock()
    mock_status = MagicMock()
    card._header_widget = mock_header
    card._status_widget = mock_status

    with (
        patch(
            "soothe_cli.tui.widgets.messages.cognition_step._is_widget_animation_visible",
            return_value=True,
        ),
        patch.object(theme, "get_theme_colors", return_value=_mock_theme_colors()),
    ):
        card._update_running_animation()

    assert mock_header.update.called
    text = _extract_content_text(mock_header.update.call_args[0][0])
    assert "Deep Research workspace" in text
    assert "3/0" in text
    assert "Running..." not in text
    assert mock_status.display is False


def test_running_animation_updates_title_stats_dynamically() -> None:
    """Title meta updates when new tools are added during running state."""
    card = CognitionStepMessage("DYN-01", "Dynamic stats", id="step-dyn")

    card.add_tool_call("DYN_01:s:read_file:0", "read_file", {"path": "a.py"})

    card._status = "running"
    card._start_time = 0.0
    mock_header = MagicMock()
    card._header_widget = mock_header
    card._status_widget = MagicMock()

    with (
        patch(
            "soothe_cli.tui.widgets.messages.cognition_step._is_widget_animation_visible",
            return_value=True,
        ),
        patch.object(theme, "get_theme_colors", return_value=_mock_theme_colors()),
    ):
        card._update_running_animation()
        first_text = _extract_content_text(mock_header.update.call_args[0][0])
        assert "1/0" in first_text

        card.add_tool_call("DYN_01:s:read_file:1", "read_file", {"path": "b.py"})
        card.add_tool_call("DYN_01:s:grep:0", "grep", {"pattern": "class"})

        mock_header.update.reset_mock()
        card._update_running_animation()
        second_text = _extract_content_text(mock_header.update.call_args[0][0])
        assert "3/0" in second_text, f"Stats should reflect 3 tools, got: {second_text!r}"


def test_running_animation_shows_elapsed_without_tool_counts() -> None:
    """Title shows elapsed when running with zero tool calls."""
    card = CognitionStepMessage("EMPTY-01", "No tools step", id="step-empty")

    assert card._stats_title_suffix() == ""

    card._status = "running"
    card._start_time = 0.0
    mock_header = MagicMock()
    card._header_widget = mock_header
    card._status_widget = MagicMock()

    with (
        patch(
            "soothe_cli.tui.widgets.messages.cognition_step._is_widget_animation_visible",
            return_value=True,
        ),
        patch.object(theme, "get_theme_colors", return_value=_mock_theme_colors()),
    ):
        card._update_running_animation()
        text = _extract_content_text(mock_header.update.call_args[0][0])

    assert "No tools step" in text
    assert "Running..." not in text
    assert "0/" not in text


def test_running_animation_includes_elapsed_time_on_title() -> None:
    """Title meta shows elapsed time when start_time is set."""
    from time import time

    card = CognitionStepMessage("TIME-01", "Time step", id="step-time")

    card.add_tool_call("TIME_01:s:read_file:0", "read_file", {"path": "test.py"})

    card._status = "running"
    card._start_time = time() - 45.0

    mock_header = MagicMock()
    card._header_widget = mock_header
    card._status_widget = MagicMock()

    with (
        patch(
            "soothe_cli.tui.widgets.messages.cognition_step._is_widget_animation_visible",
            return_value=True,
        ),
        patch.object(theme, "get_theme_colors", return_value=_mock_theme_colors()),
    ):
        card._update_running_animation()
        text = _extract_content_text(mock_header.update.call_args[0][0])

    assert "Running..." not in text
    assert " · 45s" in text, f"Elapsed time should use middots with unit, got: {text!r}"
    assert "(45s)" not in text, f"Elapsed must not use parentheses, got: {text!r}"
    assert "45s" in text
    assert "1/0" in text


def test_running_animation_returns_early_when_not_running_status() -> None:
    """_update_running_animation does nothing when status is not 'running'."""
    card = CognitionStepMessage("SKIP-01", "Skip step", id="step-skip")
    card.add_tool_call("SKIP_01:s:grep:0", "grep", {"pattern": "x"})

    card._status = "pending"
    mock_header = MagicMock()
    card._header_widget = mock_header
    card._status_widget = MagicMock()

    card._update_running_animation()
    assert not mock_header.update.called


def test_running_animation_works_without_status_widget() -> None:
    """Running animation refreshes the title even when _status_widget is None."""
    card = CognitionStepMessage("NO-WIDGET-01", "No widget step", id="step-no-widget")
    card.add_tool_call("NO_WIDGET_01:s:grep:0", "grep", {"pattern": "x"})

    card._status = "running"
    card._start_time = 0.0
    card._status_widget = None
    mock_header = MagicMock()
    card._header_widget = mock_header

    with (
        patch(
            "soothe_cli.tui.widgets.messages.cognition_step._is_widget_animation_visible",
            return_value=True,
        ),
        patch.object(theme, "get_theme_colors", return_value=_mock_theme_colors()),
    ):
        card._update_running_animation()

    assert mock_header.update.called
    text = _extract_content_text(mock_header.update.call_args[0][0])
    assert "1/0" in text


def test_no_duplicate_tool_rows_in_activity_preview() -> None:
    """Tool rows appear once in activity preview (not duplicated under task markers)."""
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

    # Task marker shown; subgraph tools stay on the step card for counts only.


def test_no_duplicate_subgraph_tools_in_main_preview() -> None:
    """Subgraph tools (type_code 't') never appear in main_preview stats."""
    card = CognitionStepMessage("MAIN-01", "Test main preview", id="step-main")

    card.add_tool_call("MAIN_01:s:grep:0", "grep", {"pattern": "x"})
    card.add_tool_call("MAIN_01:t0:glob:1", "glob", {"pattern": "**/*"})

    main_preview = card._main_agent_tool_rows_for_preview()
    assert len(main_preview) == 1
    assert main_preview[0].tool_call_id == "MAIN_01:s:grep:0"


def test_tool_stats_show_immediately_on_title_when_widget_not_visible() -> None:
    """Tool count appears on the title immediately even when animation is not visible."""
    card = CognitionStepMessage("INVIS-01", "Invisible widget step", id="step-invis")

    card._status = "running"
    card._start_time = 0.0
    mock_header = MagicMock()
    mock_status = MagicMock()
    card._header_widget = mock_header
    card._status_widget = mock_status

    with (
        patch(
            "soothe_cli.tui.widgets.messages.cognition_step._is_widget_animation_visible",
            return_value=False,
        ),
        patch.object(theme, "get_theme_colors", return_value=_mock_theme_colors()),
    ):
        card.add_tool_call("INVIS_01:s:grep:0", "grep", {"pattern": "test"})
        card.add_tool_call("INVIS_01:s:glob:1", "glob", {"pattern": "*.py"})

        assert mock_header.update.called
        text = _extract_content_text(mock_header.update.call_args[0][0])
        assert "2/0" in text, f"Title should show '2/0' immediately, got: {text!r}"
        assert "Running..." not in text
        assert mock_status.display is False

    mock_header.update.reset_mock()
    card._update_running_animation()
    assert not mock_header.update.called, "Animation should skip when not visible"


def test_sync_running_status_text_hides_footer_and_refreshes_title() -> None:
    """_sync_running_status_text hides Running footer and refreshes title meta."""
    card = CognitionStepMessage("BYPASS-01", "Bypass visibility", id="step-bypass")

    card._status = "running"
    card._start_time = 0.0
    mock_header = MagicMock()
    mock_status = MagicMock()
    card._header_widget = mock_header
    card._status_widget = mock_status

    card.add_tool_call("BYPASS_01:s:read_file:0", "read_file", {"path": "a.py"})
    card.add_tool_call("BYPASS_01:s:read_file:1", "read_file", {"path": "b.py"})

    with (
        patch(
            "soothe_cli.tui.widgets.messages.cognition_step._is_widget_animation_visible",
            return_value=False,
        ),
        patch.object(theme, "get_theme_colors", return_value=_mock_theme_colors()),
    ):
        card._sync_running_status_text()

    assert mock_status.display is False
    assert mock_header.update.called
    text = _extract_content_text(mock_header.update.call_args[0][0])
    assert "2/0" in text, f"Should show 2/0 even with visibility=False, got: {text!r}"


def test_refresh_tools_display_syncs_title_when_animation_not_visible() -> None:
    """Surface sync must refresh title meta even off-screen."""
    card = CognitionStepMessage("REFRESH-01", "Tools refresh", id="step-refresh")

    card._status = "running"
    card._start_time = 0.0
    mock_header = MagicMock()
    mock_status = MagicMock()
    card._header_widget = mock_header
    card._status_widget = mock_status
    card._tools_widget = MagicMock()
    card._activity_widget = MagicMock()

    card.add_tool_call("REFRESH_01:s:grep:0", "grep", {"pattern": "foo"})
    mock_header.update.reset_mock()

    with (
        patch(
            "soothe_cli.tui.widgets.messages.cognition_step._is_widget_animation_visible",
            return_value=False,
        ),
        patch.object(theme, "get_theme_colors", return_value=_mock_theme_colors()),
    ):
        card._sync_step_card_surface()

    assert mock_header.update.called
    text = _extract_content_text(mock_header.update.call_args[0][0])
    assert "1/0" in text, f"Title should show 1/0 after surface sync, got: {text!r}"
    assert "Running..." not in text
    assert mock_status.display is False


def test_main_only_step_activity_has_tools_section_no_running_line() -> None:
    """Main-agent-only steps wrap tools under Tool-use; no Running line in activity."""
    card = CognitionStepMessage("MAIN-01", "Direct tools", id="step-main-branch")
    card.add_tool_call("MAIN_01:s:grep:0", "grep", {"pattern": "foo"})
    card.add_tool_call("MAIN_01:s:glob:1", "glob", {"pattern": "**/*"})
    card._status = "running"
    card._start_time = 0.0
    content = str(card._step_task_activity_content())
    assert "Tool-use" in content
    assert "Glob" in content
    assert "Grep" in content
    assert "+1 more tool" not in content
    assert "Running..." not in content
    assert card._stats_title_suffix() == " · 2 tools"


def test_deferred_running_set_running_refreshes_task_activity_panel() -> None:
    """Tools added before mount must paint activity panel on set_running()."""
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
    mock_header = MagicMock()
    card._status_widget = mock_status
    card._header_widget = mock_header
    card._start_time = 0.0

    def fake_query(sel: str, _cls: type) -> MagicMock:
        if "subagent-notes" in sel:
            return mock_notes
        if "status" in sel:
            return mock_status
        if "header" in sel:
            return mock_header
        return MagicMock()

    card.query_one = fake_query  # type: ignore[method-assign]

    with patch.object(theme, "get_theme_colors", return_value=_mock_theme_colors()):
        card.set_running()

    assert mock_notes.update.called, "Task activity panel should refresh after deferred mount"
    notes_text = _extract_content_text(mock_notes.update.call_args[0][0])
    assert "Tool-use" in notes_text
    assert "Grep" in notes_text or "grep" in notes_text.lower()
    assert "Running..." not in notes_text
    assert mock_status.display is False
    assert mock_header.update.called
