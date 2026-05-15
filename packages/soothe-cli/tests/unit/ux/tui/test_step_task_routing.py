"""Tests for per-turn step / tool / task namespace routing."""

from __future__ import annotations

from unittest.mock import MagicMock

from soothe_cli.tui.step_task_routing import StepTaskRouter


def test_parallel_namespace_bind_order_via_unscoped_fifo() -> None:
    router = StepTaskRouter()
    router.on_subgraph_namespace(("tools:aaa",))
    router.on_subgraph_namespace(("tools:bbb",))
    router.register_task_spawn("functions.task:0", "explore", step_id="YKF-01")
    router.register_task_spawn("functions.task:0", "explore", step_id="YKF-02")
    assert router.resolve_task_scope(("tools:aaa",)) == ("functions.task:0", "explore", "YKF-01")
    assert router.resolve_task_scope(("tools:bbb",)) == ("functions.task:0", "explore", "YKF-02")


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
