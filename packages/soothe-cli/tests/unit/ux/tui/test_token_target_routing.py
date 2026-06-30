"""Token usage routing to step vs SubAgent cards."""

from __future__ import annotations

from soothe_cli.runtime.state.step_router import StepTaskRouter
from soothe_cli.tui.textual_adapter import TextualUIAdapter, _resolve_token_target_card
from soothe_cli.tui.widgets.messages import CognitionStepMessage
from soothe_cli.tui.widgets.messages.cognition_subagent import create_subagent_card


def _make_adapter() -> TextualUIAdapter:
    return TextualUIAdapter(
        mount_message=lambda _w: None,
        update_status=lambda _s: None,
    )


def test_resolve_token_target_card_routes_execute_namespace_to_step() -> None:
    adapter = _make_adapter()
    router = StepTaskRouter()
    step = CognitionStepMessage("ABC-01", "Main step", id="step-main")
    ns_key = ("execute:run-1",)
    adapter._step_by_namespace[ns_key] = step
    router.on_step_started("ABC-01")

    assert _resolve_token_target_card(adapter, router, ns_key) is step


def test_resolve_token_target_card_routes_subgraph_to_subagent_only() -> None:
    adapter = _make_adapter()
    router = StepTaskRouter()
    step = CognitionStepMessage("YKF-01", "Parent step", id="step-parent")
    ns_key = ("tools:explore",)
    adapter._step_by_namespace[ns_key] = step
    router.on_step_started("YKF-01")
    router.register_task_spawn("YKF_01:s:task:0", "explore", step_id="YKF-01")
    router.on_subgraph_namespace(ns_key)
    router.try_route_subgraph_tool(
        ns_key=ns_key,
        lookup_id="YKF_01:t0:grep:0",
        display_key="YKF_01:t0:grep:0",
        tool_name="grep",
        args={"pattern": "x"},
        step_cards={"YKF-01": step},
        tool_to_step={},
        tool_display_by_call_id={},
    )
    subagent = create_subagent_card(
        step_id="YKF-01",
        description="scan",
        subagent_type="explore",
        parent_step_id="YKF-01",
        parent_task_key="YKF_01:s:task:0",
        task_idx=0,
        id="subagent-route",
    )
    adapter._subagent_cards_by_key["YKF-01:t0"] = subagent

    target = _resolve_token_target_card(adapter, router, ns_key)
    assert target is subagent
    assert target is not step


def test_step_card_excludes_subgraph_token_stream() -> None:
    """Subgraph namespaces must not accumulate tokens on the parent step card."""
    adapter = _make_adapter()
    router = StepTaskRouter()
    step = CognitionStepMessage("YKF-01", "Parent step", id="step-parent")
    ns_key = ("tools:explore",)
    adapter._step_by_namespace[ns_key] = step
    router.on_step_started("YKF-01")
    router.register_task_spawn("YKF_01:s:task:0", "explore", step_id="YKF-01")
    router.on_subgraph_namespace(ns_key)
    router.try_route_subgraph_tool(
        ns_key=ns_key,
        lookup_id="YKF_01:t0:grep:0",
        display_key="YKF_01:t0:grep:0",
        tool_name="grep",
        args={"pattern": "x"},
        step_cards={"YKF-01": step},
        tool_to_step={},
        tool_display_by_call_id={},
    )

    target = _resolve_token_target_card(adapter, router, ns_key)
    assert target is None
    assert step._input_tokens == 0
    assert step._output_tokens == 0
