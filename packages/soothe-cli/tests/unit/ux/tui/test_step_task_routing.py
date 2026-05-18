"""Tests for per-turn step / tool / task namespace routing."""

from __future__ import annotations

from unittest.mock import MagicMock

from soothe_cli.tui.step_task_routing import StepTaskRouter


def test_register_task_spawn_normalizes_unified_task_id() -> None:
    router = StepTaskRouter()
    assert router.register_task_spawn("functions.task:0", "explore", step_id="YKF-02") is True
    assert router._spawns_by_step_id["YKF-02"][0] == "YKF-02:s:task.0"


def test_parallel_namespace_bind_one_at_a_time() -> None:
    router = StepTaskRouter()
    router.on_subgraph_namespace(("tools:aaa",))
    router.register_task_spawn("functions.task:0", "explore", step_id="YKF-01")
    router.on_subgraph_namespace(("tools:bbb",))
    router.register_task_spawn("functions.task:0", "explore", step_id="YKF-02")
    assert router.resolve_task_scope(("tools:aaa",)) == ("YKF-01:s:task.0", "explore", "YKF-01")
    assert router.resolve_task_scope(("tools:bbb",)) == ("YKF-02:s:task.0", "explore", "YKF-02")


def test_bind_tool_to_step_routes_pending_main_tools() -> None:
    router = StepTaskRouter()
    step = MagicMock()
    step.has_tool_call_row.return_value = False
    cards = {"s-right": step}
    tool_to_step: dict[str, object] = {}
    display: dict[str, object] = {}

    router.buffer_main_tool("grep:0", "grep", {"pattern": "x"})
    assert router.route_pending_main_tools(cards, tool_to_step, display) == 0

    router.bind_tool_to_step("grep:0", "s-right")
    assert router.route_pending_main_tools(cards, tool_to_step, display) == 1
    step.add_tool_call.assert_called_once()
    assert tool_to_step["grep:0"] is step


def test_multiple_active_steps_tracked_independently() -> None:
    router = StepTaskRouter()
    router.on_step_started("A")
    router.on_step_started("B")
    assert router.active_step_ids == {"A", "B"}
    router.on_step_completed("A")
    assert router.active_step_ids == {"B"}
    router.on_step_completed("B")
    assert not router.active_step_ids


def test_register_task_spawn_is_idempotent_per_step_and_tool() -> None:
    router = StepTaskRouter()
    assert router.register_task_spawn("tc-1", "explore", step_id="S1") is True
    assert router.register_task_spawn("tc-1", "explore", step_id="S1") is False


def test_step_id_for_tool_parses_unified_format() -> None:
    """Unified tool_call_id format encodes step_id directly."""
    router = StepTaskRouter()
    # Unified format: {step_id}:s:{tool}.{idx}
    assert router.step_id_for_tool("ABC-01:s:grep.0") == "ABC-01"
    assert router.step_id_for_tool("XYZ-99:s:bash.1") == "XYZ-99"
    # Task-level format: {step_id}:t{task_idx}:{tool}.{idx}
    assert router.step_id_for_tool("GHT-01:t0:read_file.0") == "GHT-01"
    # Non-unified ID returns empty string (no binding)
    assert router.step_id_for_tool("legacy_tool_call_id") == ""
    # Explicit binding takes precedence
    router.bind_tool_to_step("ABC-01:s:grep.0", "override-step")
    assert router.step_id_for_tool("ABC-01:s:grep.0") == "override-step"


def test_late_subgraph_namespace_binds_to_unlinked_spawn() -> None:
    """Namespace after register_task_spawn attaches via unlinked-spawn fallback."""
    router = StepTaskRouter()
    router.register_task_spawn("FJS-02:s:task:0", "explore", step_id="FJS-02")
    ns = ("tools:late-arrival",)
    router.on_subgraph_namespace(ns)
    scope = router.resolve_task_scope(ns)
    assert scope is not None
    assert scope[2] == "FJS-02"
    assert scope[1] == "explore"
    assert scope[0].startswith("FJS-02:s:task")


def test_route_pending_main_tools_uses_unified_id_parsing() -> None:
    """route_pending_main_tools extracts step_id from unified IDs."""
    router = StepTaskRouter()
    step_card = MagicMock()
    step_card.has_tool_call_row.return_value = False
    step_cards = {"GHT-01": step_card}
    tool_to_step: dict[str, object] = {}
    display: dict[str, object] = {}

    # Buffer tool with unified ID format (no explicit binding)
    router.buffer_main_tool("GHT-01:s:grep.0", "grep", {"pattern": "test"})
    # route_pending_main_tools should parse the unified ID and find the step card
    routed = router.route_pending_main_tools(step_cards, tool_to_step, display)
    assert routed == 1
    step_card.add_tool_call.assert_called_once_with(
        "GHT-01:s:grep.0", "grep", {"pattern": "test"}, raw_args=""
    )
    assert tool_to_step["GHT-01:s:grep.0"] is step_card
