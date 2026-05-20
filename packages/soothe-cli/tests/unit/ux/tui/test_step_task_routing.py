"""Tests for per-turn step / tool / task namespace routing."""

from __future__ import annotations

from unittest.mock import MagicMock

from soothe_cli.runtime.state.step_router import StepTaskRouter


def test_register_task_spawn_rejects_inner_subgraph_task_id() -> None:
    router = StepTaskRouter()
    assert router.register_task_spawn("MLG_02:t0:task:0", "explore", step_id="MLG-02") is False
    assert router._spawns_by_step_id.get("MLG-02") is None


def test_register_task_spawn_normalizes_unified_task_id() -> None:
    router = StepTaskRouter()
    assert router.register_task_spawn("functions.task:0", "explore", step_id="YKF-02") is True
    assert router._spawns_by_step_id["YKF-02"][0] == "YKF_02:s:task:0"


def test_parallel_namespace_bind_one_at_a_time() -> None:
    router = StepTaskRouter()
    router.on_subgraph_namespace(("tools:aaa",))
    router.register_task_spawn("functions.task:0", "explore", step_id="YKF-01")
    router.on_subgraph_namespace(("tools:bbb",))
    router.register_task_spawn("functions.task:0", "explore", step_id="YKF-02")
    assert router.resolve_task_scope(("tools:aaa",)) == ("YKF_01:s:task:0", "explore", "YKF-01")
    assert router.resolve_task_scope(("tools:bbb",)) == ("YKF_02:s:task:0", "explore", "YKF-02")


def test_route_pending_main_tools_requires_unified_tool_call_id() -> None:
    router = StepTaskRouter()
    step = MagicMock()
    step.has_tool_call_row.return_value = False
    cards = {"S-RIGHT": step}
    tool_to_step: dict[str, object] = {}
    display: dict[str, object] = {}

    router.buffer_main_tool("grep:0", "grep", {"pattern": "x"})
    assert router.route_pending_main_tools(cards, tool_to_step, display) == 0

    router.buffer_main_tool("S_RIGHT:s:grep:0", "grep", {"pattern": "x"})
    assert router.route_pending_main_tools(cards, tool_to_step, display) == 1
    step.add_tool_call.assert_called_once()
    assert tool_to_step["S_RIGHT:s:grep:0"] is step


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
    assert router.register_task_spawn("S1:s:task:0", "explore", step_id="S1") is True
    assert router.register_task_spawn("S1:s:task:0", "explore", step_id="S1") is False


def test_step_id_for_tool_parses_unified_format() -> None:
    """Unified tool_call_id format encodes step_id directly."""
    router = StepTaskRouter()
    assert router.step_id_for_tool("ABC_01:s:grep:0") == "ABC-01"
    assert router.step_id_for_tool("XYZ_99:s:bash:1") == "XYZ-99"
    assert router.step_id_for_tool("GHT_01:t0:read_file:0") == "GHT-01"
    assert router.step_id_for_tool("legacy_tool_call_id") == ""
    assert router.step_id_for_tool("functions.grep:0") == ""


def test_buffered_subgraph_tools_coalesce_per_namespace_and_lookup() -> None:
    """Repeated BUFFERED chunks for one logical tool must not grow memory without bound."""

    router = StepTaskRouter()
    ns = ("tools:parallel-a",)
    cards: dict[str, object] = {}
    tool_to_step: dict[str, object] = {}
    display: dict[str, object] = {}

    for _ in range(5000):
        assert (
            router.try_route_subgraph_tool(
                ns_key=ns,
                lookup_id="task:0",
                display_key="tools:parallel-a\x1etask:0",
                tool_name="task",
                args={"description": "explore pkg"},
                step_cards=cards,
                tool_to_step=tool_to_step,
                tool_display_by_call_id=display,
            )
            is False
        )

    assert len(router._pending_subgraph_tools) == 1
    only = next(iter(router._pending_subgraph_tools.values()))
    assert only.ns_key == ns
    assert only.lookup_id == "task:0"


def test_buffered_main_tools_coalesce_per_tool_call_id() -> None:
    router = StepTaskRouter()
    for i in range(1000):
        router.buffer_main_tool("grep:0", "grep", {"pattern": f"x{i}"})
    assert len(router._pending_main_tools) == 1
    assert router._pending_main_tools["grep:0"].args["pattern"] == "x999"


def test_parallel_explore_namespaces_bind_from_unified_tool_ids() -> None:
    """Parallel explore: namespaces correlate via embedded step ids, not spawn FIFO."""
    router = StepTaskRouter()
    router.register_task_spawn("XFJ_02:s:task:0", "explore", step_id="XFJ-02")
    router.register_task_spawn("XFJ_01:s:task:0", "explore", step_id="XFJ-01")
    router.on_subgraph_namespace(("tools:explore-a",))
    router.on_subgraph_namespace(("tools:explore-b",))
    assert router.resolve_task_scope(("tools:explore-a",)) is None
    assert router.resolve_task_scope(("tools:explore-b",)) is None
    router.try_route_subgraph_tool(
        ns_key=("tools:explore-a",),
        lookup_id="XFJ_02:t0:glob:0",
        display_key="XFJ_02:t0:glob:0",
        tool_name="glob",
        args={"pattern": "**/*"},
        step_cards={},
        tool_to_step={},
        tool_display_by_call_id={},
    )
    router.try_route_subgraph_tool(
        ns_key=("tools:explore-b",),
        lookup_id="XFJ_01:t0:grep:1",
        display_key="XFJ_01:t0:grep:1",
        tool_name="grep",
        args={"pattern": "x"},
        step_cards={},
        tool_to_step={},
        tool_display_by_call_id={},
    )
    assert router.resolve_task_scope(("tools:explore-a",)) == (
        "XFJ_02:s:task:0",
        "explore",
        "XFJ-02",
    )
    assert router.resolve_task_scope(("tools:explore-b",)) == (
        "XFJ_01:s:task:0",
        "explore",
        "XFJ-01",
    )


def test_subgraph_inner_task_tool_is_not_ingested_on_step_card() -> None:
    router = StepTaskRouter()
    step = MagicMock()
    step.has_tool_call_row.return_value = False
    step_cards = {"FHG-01": step}
    display = {"FHG_01:s:task:0": step}

    router.register_task_spawn("FHG_01:s:task:0", "explore", step_id="FHG-01")
    router.on_subgraph_namespace(("tools:sub",))

    assert (
        router.try_route_subgraph_tool(
            ns_key=("tools:sub",),
            lookup_id="task:0",
            display_key="FHG_01:t0:task:0",
            tool_name="task",
            args={"description": "wrong", "subagent_type": "explore"},
            step_cards=step_cards,
            tool_to_step={},
            tool_display_by_call_id=display,
        )
        is True
    )
    step.add_tool_call.assert_not_called()


def test_parallel_subgraph_tools_route_under_explore_row() -> None:
    router = StepTaskRouter()
    step = MagicMock()
    step.has_tool_call_row.return_value = False
    step_cards = {"XFJ-01": step}
    tool_to_step: dict[str, object] = {}
    display = {"XFJ_01:s:task:0": step}

    router.register_task_spawn("XFJ_01:s:task:0", "explore", step_id="XFJ-01")
    router.on_subgraph_namespace(("tools:sub",))

    router.try_route_subgraph_tool(
        ns_key=("tools:sub",),
        lookup_id="functions.grep:0",
        display_key="tools:sub\x1egrep:0",
        tool_name="grep",
        args={"pattern": "x"},
        step_cards=step_cards,
        tool_to_step=tool_to_step,
        tool_display_by_call_id=display,
    )
    step.add_tool_call.assert_called_once()
    _args, kwargs = step.add_tool_call.call_args
    assert _args[0] == "XFJ_01:t0:grep:0"
    assert kwargs.get("parent_tool_call_id") == "XFJ_01:s:task:0"


def test_late_subgraph_namespace_binds_to_unlinked_spawn() -> None:
    """Namespace after register_task_spawn attaches via unlinked-spawn fallback."""
    router = StepTaskRouter()
    router.register_task_spawn("FJS_02:s:task:0", "explore", step_id="FJS-02")
    ns = ("tools:late-arrival",)
    router.on_subgraph_namespace(ns)
    scope = router.resolve_task_scope(ns)
    assert scope is not None
    assert scope[2] == "FJS-02"
    assert scope[1] == "explore"
    assert scope[0].startswith("FJS_02:s:task")


def test_route_pending_main_tools_uses_unified_id_parsing() -> None:
    """route_pending_main_tools extracts step_id from unified IDs."""
    router = StepTaskRouter()
    step_card = MagicMock()
    step_card.has_tool_call_row.return_value = False
    step_cards = {"GHT-01": step_card}
    tool_to_step: dict[str, object] = {}
    display: dict[str, object] = {}

    # Buffer tool with unified ID format (no explicit binding)
    router.buffer_main_tool("GHT_01:s:grep:0", "grep", {"pattern": "test"})
    # route_pending_main_tools should parse the unified ID and find the step card
    routed = router.route_pending_main_tools(step_cards, tool_to_step, display)
    assert routed == 1
    step_card.add_tool_call.assert_called_once_with(
        "GHT_01:s:grep:0", "grep", {"pattern": "test"}, raw_args=""
    )
    assert tool_to_step["GHT_01:s:grep:0"] is step_card
