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


def test_parallel_namespace_bind_via_unified_tool_ids() -> None:
    """Namespace binding requires unified tool call IDs, not FIFO order."""
    router = StepTaskRouter()
    router.register_task_spawn("YKF_01:s:task:0", "explore", step_id="YKF-01")
    router.register_task_spawn("YKF_02:s:task:0", "explore", step_id="YKF-02")
    router.on_subgraph_namespace(("tools:aaa",))
    router.on_subgraph_namespace(("tools:bbb",))
    # Namespaces not bound yet without tool calls
    assert router.resolve_task_scope(("tools:aaa",)) is None
    assert router.resolve_task_scope(("tools:bbb",)) is None
    # Bind via unified tool call IDs with embedded step ids
    router.try_route_subgraph_tool(
        ns_key=("tools:aaa",),
        lookup_id="YKF_01:t0:grep:0",
        display_key="YKF_01:t0:grep:0",
        tool_name="grep",
        args={"pattern": "x"},
        step_cards={},
        tool_to_step={},
        tool_display_by_call_id={},
    )
    router.try_route_subgraph_tool(
        ns_key=("tools:bbb",),
        lookup_id="YKF_02:t0:grep:0",
        display_key="YKF_02:t0:grep:0",
        tool_name="grep",
        args={"pattern": "y"},
        step_cards={},
        tool_to_step={},
        tool_display_by_call_id={},
    )
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
    """Inner subgraph task tools are swallowed, not ingested as tool rows."""
    router = StepTaskRouter()
    step = MagicMock()
    step.has_tool_call_row.return_value = False
    step_cards = {"FHG-01": step}
    display = {"FHG_01:s:task:0": step}

    router.register_task_spawn("FHG_01:s:task:0", "explore", step_id="FHG-01")
    router.on_subgraph_namespace(("tools:sub",))
    # Bind namespace via a non-task tool first
    router.try_route_subgraph_tool(
        ns_key=("tools:sub",),
        lookup_id="FHG_01:t0:grep:0",
        display_key="FHG_01:t0:grep:0",
        tool_name="grep",
        args={"pattern": "x"},
        step_cards=step_cards,
        tool_to_step={},
        tool_display_by_call_id=display,
    )
    # Verify grep tool was added
    step.add_tool_call.assert_called_once()
    # Reset mock to check inner task tool behavior
    step.reset_mock()
    # Now inner task tool is ingested (returns True) but add_tool_call is not called
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
    # Inner task tools don't create tool rows (they're not user-facing)
    step.add_tool_call.assert_not_called()


def test_parallel_subgraph_tools_route_under_explore_row() -> None:
    """Subgraph tools route to parent step card using unified tool call IDs."""
    router = StepTaskRouter()
    step = MagicMock()
    step.has_tool_call_row.return_value = False
    step_cards = {"XFJ-01": step}
    tool_to_step: dict[str, object] = {}
    display = {"XFJ_01:s:task:0": step}

    router.register_task_spawn("XFJ_01:s:task:0", "explore", step_id="XFJ-01")
    router.on_subgraph_namespace(("tools:sub",))

    # Use unified tool call ID to bind namespace and route tool
    router.try_route_subgraph_tool(
        ns_key=("tools:sub",),
        lookup_id="XFJ_01:t0:grep:0",
        display_key="XFJ_01:t0:grep:0",
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


def test_late_subgraph_namespace_binds_via_unified_tool_call_id() -> None:
    """Namespace binds via unified tool call ID, not automatic spawn linking."""
    router = StepTaskRouter()
    router.register_task_spawn("FJS_02:s:task:0", "explore", step_id="FJS-02")
    ns = ("tools:late-arrival",)
    router.on_subgraph_namespace(ns)
    # Namespace not bound yet without unified tool call ID
    assert router.resolve_task_scope(ns) is None
    # Bind via unified tool call ID with embedded step_id
    router.try_route_subgraph_tool(
        ns_key=ns,
        lookup_id="FJS_02:t0:grep:0",
        display_key="FJS_02:t0:grep:0",
        tool_name="grep",
        args={"pattern": "x"},
        step_cards={},
        tool_to_step={},
        tool_display_by_call_id={},
    )
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
