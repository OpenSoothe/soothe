"""IG-599 / IG-601: Pass 2 / slash wired-subagent direct route."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage
from langgraph.graph import END

from soothe.foundation.sloop.engine.thread_selection import resolve_user_requested_wire_subagent
from soothe.foundation.sloop.intention.models import (
    IntakeLabel,
    IntentClassification,
    TaskComplexity,
    build_loop_routing_classification,
)
from soothe.foundation.sloop.orchestrator.nodes.init_or_resume import node_init_or_resume
from soothe.foundation.sloop.orchestrator.nodes.invoke_wired_subagent import (
    node_invoke_wired_subagent,
)
from soothe.foundation.sloop.orchestrator.routing import route_after_wired_subagent, route_by_intent
from soothe.foundation.sloop.state.schemas import resolve_wire_subagent


async def _noop_emit(*_args, **_kwargs) -> None:  # type: ignore[no-untyped-def]
    return None


def test_allowlist_includes_academic_research_and_planner() -> None:
    assert resolve_wire_subagent(wire_subagent="academic_research") == "academic_research"
    assert resolve_wire_subagent(wire_subagent="planner") == "planner"
    assert resolve_wire_subagent(wire_subagent="plan") is None
    assert resolve_wire_subagent(wire_subagent="not_a_subagent") is None


def test_build_loop_routing_classification_merges_pass2_wire() -> None:
    intent = IntentClassification(
        intake_label=IntakeLabel.SIMPLE,
        wire_subagent="deep_research",
        task_complexity=TaskComplexity.SIMPLE,
    )
    routing = build_loop_routing_classification(intent, preferred_subagent=None)
    assert routing is not None
    assert routing.preferred_subagent == "deep_research"
    assert routing.routing_hint == "subagent"


def test_build_loop_routing_classification_slash_wins_over_pass2() -> None:
    intent = IntentClassification(
        intake_label=IntakeLabel.SIMPLE,
        wire_subagent="browser_use",
        task_complexity=TaskComplexity.SIMPLE,
    )
    routing = build_loop_routing_classification(intent, preferred_subagent="planner")
    assert routing is not None
    assert routing.preferred_subagent == "planner"


def test_resolve_preferred_subagent_kwarg_wins() -> None:
    intent = IntentClassification(
        intake_label=IntakeLabel.SIMPLE,
        wire_subagent="browser_use",
        task_complexity=TaskComplexity.SIMPLE,
    )
    assert (
        resolve_user_requested_wire_subagent(
            intent=intent,
            preferred_subagent="academic_research",
        )
        == "academic_research"
    )


def test_route_by_intent_wired_subagent() -> None:
    state = {
        "intent_route": "wired_subagent",
        "intake_label": IntakeLabel.COMPLEX,
        "is_continuation": True,
    }
    assert route_by_intent(state) == "invoke_wired_subagent"


def test_route_by_intent_chitchat_still_wins_over_wired() -> None:
    state = {
        "intent_route": "fast_path",
        "intake_label": IntakeLabel.CHITCHAT,
        "is_continuation": False,
    }
    assert route_by_intent(state) == END


@pytest.mark.asyncio
async def test_init_or_resume_sets_wired_subagent_route() -> None:
    intent = IntentClassification(
        intake_label=IntakeLabel.SIMPLE,
        wire_subagent="browser_use",
        requires_tool_use=True,
        task_complexity=TaskComplexity.SIMPLE,
    )
    loop_state = SimpleNamespace(
        intent=intent,
        routing_classification=build_loop_routing_classification(intent, None),
        goal="use browser_use for weather",
        goal_user_submission="use browser_use for weather",
    )
    ctx = SimpleNamespace(
        loop_state=loop_state,
        preferred_subagent=None,
        continue_loop_mode=False,
        recovery_valid_resume=False,
        checkpoint=None,
        ce=None,
        ce_goal_id=None,
        scratch=SimpleNamespace(plan_result=None),
        emit=_noop_emit,
    )
    result = await node_init_or_resume(ctx, {})  # type: ignore[arg-type]
    assert result["intent_route"] == "wired_subagent"
    assert ctx.scratch.plan_result is None  # plan owned by invoke_wired_subagent
    assert route_by_intent(result) == "invoke_wired_subagent"


@pytest.mark.asyncio
async def test_invoke_wired_planner_builds_plan_for_resolve() -> None:
    intent = IntentClassification(
        intake_label=IntakeLabel.SIMPLE,
        wire_subagent="planner",
        requires_tool_use=True,
        task_complexity=TaskComplexity.SIMPLE,
    )
    emitted: list[tuple[str, object]] = []

    async def _emit(event_type: str, payload: object) -> None:
        emitted.append((event_type, payload))

    ctx = SimpleNamespace(
        loop_state=SimpleNamespace(
            intent=intent,
            routing_classification=build_loop_routing_classification(intent, None),
            goal="plan the migration",
            goal_user_submission="plan the migration",
            total_tokens_used=0,
        ),
        preferred_subagent=None,
        scratch=SimpleNamespace(plan_result=None),
        emit=_emit,
        core_agent=SimpleNamespace(lookup_intake_only_subagent=lambda _n: None),
    )
    out = await node_invoke_wired_subagent(ctx, {})  # type: ignore[arg-type]
    assert out == {}
    assert route_after_wired_subagent(out) == "resolve_decision"
    assert ctx.scratch.plan_result is not None
    step = ctx.scratch.plan_result.decision.steps[0]
    assert step.wire_subagent == "planner"
    assert ctx.scratch.plan_result.terminal_after_execute is True
    assert any(e[0] == "plan_phase_status" for e in emitted)


@pytest.mark.asyncio
async def test_invoke_wired_intake_only_direct_ainvoke() -> None:
    intent = IntentClassification(
        intake_label=IntakeLabel.SIMPLE,
        wire_subagent="deep_research",
        requires_tool_use=True,
        task_complexity=TaskComplexity.SIMPLE,
    )
    runnable = SimpleNamespace(
        ainvoke=AsyncMock(return_value={"messages": [AIMessage(content="research report body")]})
    )
    loop_state = SimpleNamespace(
        intent=intent,
        routing_classification=build_loop_routing_classification(intent, None),
        goal="research AI agents",
        goal_user_submission="research AI agents",
        total_tokens_used=0,
        thread_id="t1",
        workspace=None,
        iteration=0,
        _loop_messages_cache=[],
    )
    ctx = SimpleNamespace(
        loop_state=loop_state,
        preferred_subagent=None,
        scratch=SimpleNamespace(plan_result=None),
        emit=_noop_emit,
        ce=None,
        core_agent=SimpleNamespace(
            lookup_intake_only_subagent=lambda name: (
                {"name": "deep_research", "runnable": runnable} if name == "deep_research" else None
            )
        ),
    )
    out = await node_invoke_wired_subagent(ctx, {})  # type: ignore[arg-type]
    assert out == {"wired_route_next": "goal_completion"}
    assert route_after_wired_subagent(out) == "goal_completion"
    runnable.ainvoke.assert_awaited_once()
    assert ctx.scratch.plan_result is not None
    assert ctx.scratch.plan_result.decision.steps[0].wire_subagent == "deep_research"
    assert any(
        getattr(m, "content", None) == "research report body"
        for m in loop_state._loop_messages_cache
    )


def test_route_after_wired_subagent_fatal() -> None:
    assert route_after_wired_subagent({"last_outcome": "fatal"}) == END


@pytest.mark.asyncio
async def test_invoke_wired_subagent_fatal_without_wire() -> None:
    emit = AsyncMock()
    ctx = SimpleNamespace(
        loop_state=SimpleNamespace(
            intent=IntentClassification(
                intake_label=IntakeLabel.SIMPLE,
                wire_subagent=None,
                task_complexity=TaskComplexity.SIMPLE,
            ),
            routing_classification=None,
            goal="do something",
            goal_user_submission="do something",
            total_tokens_used=0,
        ),
        preferred_subagent=None,
        scratch=SimpleNamespace(plan_result=None),
        emit=emit,
    )
    out = await node_invoke_wired_subagent(ctx, {})  # type: ignore[arg-type]
    assert out["last_outcome"] == "fatal"
    emit.assert_awaited()
