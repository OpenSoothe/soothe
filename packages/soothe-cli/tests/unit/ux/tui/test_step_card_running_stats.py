"""Running status line shows per-tool counts from unified tool_call_id per step."""

from __future__ import annotations

from unittest.mock import MagicMock

from soothe_cli.runtime.state.step_router import StepTaskRouter
from soothe_cli.tui.widgets.messages import CognitionStepMessage


def test_stats_title_suffix_counts_distinct_unified_ids() -> None:
    card = CognitionStepMessage("ABC-01", "Scan workspace", id="stp-stats")
    card.add_tool_call("ABC_01:s:grep:0", "grep", {"pattern": "x"})
    card.add_tool_call("ABC_01:s:grep:1", "grep", {"pattern": "x"})
    card.add_tool_call("ABC_01:s:grep:2", "grep", {"pattern": "y"})
    card.add_tool_call("ABC_01:s:glob:0", "glob", {"pattern": "**/*"})
    suffix = card._stats_title_suffix()
    assert "Grep(3)" in suffix
    assert "Glob(1)" in suffix


def test_stats_ignore_unified_ids_for_other_steps() -> None:
    card = CognitionStepMessage("ABC-01", "Scan workspace", id="stp-stats")
    card.add_tool_call("XYZ_99:s:glob:0", "glob", {"pattern": "**/*"})
    assert card._stats_title_suffix() == ""


def test_status_tool_stats_suffix_prefers_per_tool_over_fallback_total() -> None:
    card = CognitionStepMessage("ABC-01", "Scan", id="stp-done")
    card.add_tool_call("ABC_01:s:grep:0", "grep", {})
    card.add_tool_call("ABC_01:s:grep:1", "grep", {})
    card.add_tool_call("ABC_01:s:glob:0", "glob", {})
    suffix = card._status_tool_stats_suffix(fallback_count=99)
    assert "Grep(2)" in suffix
    assert "Glob(1)" in suffix
    assert "99 tools" not in suffix


def test_status_tool_stats_suffix_falls_back_to_total_when_untracked() -> None:
    card = CognitionStepMessage("ABC-01", "Scan", id="stp-fallback")
    assert card._status_tool_stats_suffix(fallback_count=3) == " · 3 tools"


def test_stats_same_unified_id_not_double_counted() -> None:
    card = CognitionStepMessage("ABC-01", "Scan", id="stp-stream")
    card.add_tool_call("ABC_01:s:glob:0", "glob", {})
    card.update_tool_args("ABC_01:s:glob:0", {"pattern": "a"})
    assert "Glob(1)" in card._stats_title_suffix()
    card.add_tool_call("ABC_01:s:glob:1", "glob", {"pattern": "b"})
    assert "Glob(2)" in card._stats_title_suffix()


def test_route_pending_subgraph_tools_attaches_to_step_card() -> None:
    router = StepTaskRouter()
    router.on_step_started("YKF-01")
    router.register_task_spawn("YKF_01:s:task:0", "explore", step_id="YKF-01")
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


def test_stats_exclude_nested_subgraph_and_task_tools() -> None:
    card = CognitionStepMessage("ABC-01", "Scan", id="stp-nested")
    card.add_tool_call("ABC_01:s:grep:0", "grep", {})
    card.add_tool_call(
        "ABC_01:s:task:0",
        "task",
        {"subagent_type": "explore", "description": "scan"},
        is_task_row=True,
    )
    card.add_tool_call(
        "ABC_01:t0:glob:1",
        "glob",
        {"pattern": "**/*"},
        parent_tool_call_id="ABC_01:s:task:0",
    )
    suffix = card._stats_title_suffix()
    assert "Grep(1)" in suffix
    assert "Glob" not in suffix
    assert "Task" not in suffix


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
