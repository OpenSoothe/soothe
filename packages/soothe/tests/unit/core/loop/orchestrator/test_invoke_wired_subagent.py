"""IG-599 / IG-601: Pass 2 / slash wired-subagent direct route."""

from __future__ import annotations

import asyncio
import contextvars
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage
from langgraph.graph import END

from soothe.sloop.engine.thread_selection import resolve_user_requested_wire_subagent
from soothe.sloop.intention.models import (
    IntakeLabel,
    IntentClassification,
    TaskComplexity,
    build_loop_routing_classification,
)
from soothe.sloop.nodes.init_or_resume import node_init_or_resume
from soothe.sloop.nodes.invoke_wired_subagent import (
    node_invoke_wired_subagent,
)
from soothe.sloop.orchestrator.routing import route_after_wired_subagent, route_by_intent
from soothe.sloop.state.schemas import resolve_wire_subagent


async def _noop_emit(*_args, **_kwargs) -> None:  # type: ignore[no-untyped-def]
    return None


def test_allowlist_includes_academic_research_and_planner() -> None:
    assert resolve_wire_subagent(wire_subagent="explorer") is None
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
async def test_init_or_resume_wire_subagent_wins_even_with_continue_keyword_goal() -> None:
    intent = IntentClassification(
        intake_label=IntakeLabel.SIMPLE,
        wire_subagent="deep_research",
        requires_tool_use=True,
        task_complexity=TaskComplexity.SIMPLE,
    )
    loop_state = SimpleNamespace(
        intent=intent,
        routing_classification=build_loop_routing_classification(intent, None),
        goal="continue",
        goal_user_submission="continue",
    )
    ctx = SimpleNamespace(
        loop_state=loop_state,
        preferred_subagent=None,
        continue_loop_mode=True,
        recovery_valid_resume=False,
        checkpoint=None,
        ce=None,
        ce_goal_id=None,
        scratch=SimpleNamespace(plan_result=None),
        emit=_noop_emit,
    )
    result = await node_init_or_resume(ctx, {})  # type: ignore[arg-type]
    assert result["intent_route"] == "wired_subagent"
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
    assert not any(e[0].startswith("wired_subagent_") for e in emitted)


def test_extract_subagent_report_prefers_answer_field() -> None:
    """deep_research / academic_research put the report in state ``answer``."""
    from soothe.sloop.nodes.invoke_wired_subagent import (
        _extract_subagent_report,
    )

    body = "## Summary\n\nBrief.\n\nFull report saved to: `/tmp/r.md`"
    assert _extract_subagent_report({"answer": body, "messages": []}) == body
    assert _extract_subagent_report({"messages": [AIMessage(content="from msg")]}) == "from msg"
    assert (
        _extract_subagent_report(
            {
                "messages": [AIMessage(content="## Explore results\n\n- item")],
                "structured_response": {"target": "x", "matches": [], "summary": "raw json"},
            }
        )
        == "## Explore results\n\n- item"
    )


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
    emitted: list[tuple[str, object]] = []

    async def _emit(event_type: str, payload: object) -> None:
        emitted.append((event_type, payload))

    ctx = SimpleNamespace(
        loop_state=loop_state,
        preferred_subagent=None,
        scratch=SimpleNamespace(plan_result=None),
        emit=_emit,
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
    types = [e[0] for e in emitted]
    assert "plan_phase_status" in types
    assert "wired_subagent_started" in types
    assert "wired_subagent_completed" in types
    started = next(p for t, p in emitted if t == "wired_subagent_started")
    assert isinstance(started, dict)
    assert started["subagent"] == "deep_research"
    assert started["invocation_id"]


@pytest.mark.asyncio
async def test_invoke_wired_intake_only_ledgers_answer_field() -> None:
    intent = IntentClassification(
        intake_label=IntakeLabel.SIMPLE,
        wire_subagent="deep_research",
        requires_tool_use=True,
        task_complexity=TaskComplexity.SIMPLE,
    )
    body = "## Summary\n\nUS macro brief.\n\nFull report saved to: `/tmp/us.md`"
    runnable = SimpleNamespace(ainvoke=AsyncMock(return_value={"answer": body, "messages": []}))
    loop_state = SimpleNamespace(
        intent=intent,
        routing_classification=build_loop_routing_classification(intent, None),
        goal="research US economy",
        goal_user_submission="research US economy",
        total_tokens_used=0,
        thread_id="t1",
        workspace=None,
        iteration=0,
        _loop_messages_cache=[],
    )
    emitted: list[tuple[str, object]] = []

    async def _emit(event_type: str, payload: object) -> None:
        emitted.append((event_type, payload))

    ctx = SimpleNamespace(
        loop_state=loop_state,
        preferred_subagent=None,
        scratch=SimpleNamespace(plan_result=None),
        emit=_emit,
        ce=None,
        core_agent=SimpleNamespace(
            lookup_intake_only_subagent=lambda name: (
                {"name": "deep_research", "runnable": runnable} if name == "deep_research" else None
            )
        ),
    )
    out = await node_invoke_wired_subagent(ctx, {})  # type: ignore[arg-type]
    assert out == {"wired_route_next": "goal_completion"}
    assert any(getattr(m, "content", None) == body for m in loop_state._loop_messages_cache)
    completed = next(p for t, p in emitted if t == "wired_subagent_completed")
    assert isinstance(completed, dict)
    assert completed["summary"].startswith("## Summary")


@pytest.mark.asyncio
async def test_invoke_wired_intake_only_forwards_via_bridge_during_astream() -> None:
    """astream values + bridge: wire customs come from emit_progress, not custom mode."""
    intent = IntentClassification(
        intake_label=IntakeLabel.SIMPLE,
        wire_subagent="deep_research",
        requires_tool_use=True,
        task_complexity=TaskComplexity.SIMPLE,
    )

    async def _astream(_input, stream_mode=None):  # type: ignore[no-untyped-def]
        from soothe_nano.utils.progress import emit_progress

        emit_progress(
            {
                "type": "soothe.subagent.deep_research.progress",
                "phase": "plan",
                "message": "go",
            },
            logging.getLogger("test.wired_bridge_astream"),
        )
        yield ("values", {"messages": [AIMessage(content="streamed report")]})

    runnable = SimpleNamespace(astream=_astream, ainvoke=AsyncMock())
    emitted: list[tuple[str, object]] = []

    async def _emit(event_type: str, payload: object) -> None:
        emitted.append((event_type, payload))
        await asyncio.sleep(0)

    loop_state = SimpleNamespace(
        intent=intent,
        routing_classification=build_loop_routing_classification(intent, None),
        goal="research",
        goal_user_submission="research",
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
        emit=_emit,
        ce=None,
        core_agent=SimpleNamespace(
            lookup_intake_only_subagent=lambda name: (
                {"name": "deep_research", "runnable": runnable} if name == "deep_research" else None
            )
        ),
    )
    out = await node_invoke_wired_subagent(ctx, {})  # type: ignore[arg-type]
    assert out == {"wired_route_next": "goal_completion"}
    runnable.ainvoke.assert_not_called()
    stream_customs = [p for t, p in emitted if t == "stream_event"]
    assert stream_customs
    _ns, mode, data = stream_customs[0]  # type: ignore[misc]
    assert mode == "custom"
    assert data["type"] == "soothe.subagent.deep_research.progress"
    assert data["invocation_id"]


@pytest.mark.asyncio
async def test_invoke_wired_intake_only_astream_two_tuple_prefers_answer_field() -> None:
    """Two-item ``(mode, data)`` astream chunks should unwrap to dict state."""
    intent = IntentClassification(
        intake_label=IntakeLabel.SIMPLE,
        wire_subagent="browser_use",
        requires_tool_use=True,
        task_complexity=TaskComplexity.SIMPLE,
    )
    synthesized = "Weather summary: clear sky, 26C."

    async def _astream(_input, stream_mode=None):  # type: ignore[no-untyped-def]
        yield (
            "values",
            {
                "answer": synthesized,
                "messages": [AIMessage(content=synthesized)],
            },
        )

    runnable = SimpleNamespace(astream=_astream, ainvoke=AsyncMock())
    emitted: list[tuple[str, object]] = []

    async def _emit(event_type: str, payload: object) -> None:
        emitted.append((event_type, payload))
        await asyncio.sleep(0)

    loop_state = SimpleNamespace(
        intent=intent,
        routing_classification=build_loop_routing_classification(intent, None),
        goal="west coast weather",
        goal_user_submission="west coast weather",
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
        emit=_emit,
        ce=None,
        core_agent=SimpleNamespace(
            lookup_intake_only_subagent=lambda name: (
                {"name": "browser_use", "runnable": runnable} if name == "browser_use" else None
            )
        ),
    )

    out = await node_invoke_wired_subagent(ctx, {})  # type: ignore[arg-type]
    assert out == {"wired_route_next": "goal_completion"}
    runnable.ainvoke.assert_not_called()
    assert any(getattr(m, "content", None) == synthesized for m in loop_state._loop_messages_cache)

    completed = next(p for t, p in emitted if t == "wired_subagent_completed")
    assert isinstance(completed, dict)
    assert completed["summary"].startswith("Weather summary")
    assert "values" not in completed["summary"]


@pytest.mark.asyncio
async def test_invoke_wired_intake_only_forwards_custom_wire() -> None:
    """Bridge captures emit_progress during ainvoke when stream writer is absent."""
    intent = IntentClassification(
        intake_label=IntakeLabel.SIMPLE,
        wire_subagent="deep_research",
        requires_tool_use=True,
        task_complexity=TaskComplexity.SIMPLE,
    )

    async def _ainvoke(_input):  # type: ignore[no-untyped-def]
        from soothe_nano.utils.progress import emit_progress

        emit_progress(
            {
                "type": "soothe.subagent.deep_research.progress",
                "phase": "plan",
                "message": "go",
            },
            logging.getLogger("test.wired_bridge"),
        )
        return {"messages": [AIMessage(content="streamed report")]}

    runnable = SimpleNamespace(ainvoke=_ainvoke)
    emitted: list[tuple[str, object]] = []

    async def _emit(event_type: str, payload: object) -> None:
        emitted.append((event_type, payload))
        # Let the bridge drain task run.
        await asyncio.sleep(0)

    loop_state = SimpleNamespace(
        intent=intent,
        routing_classification=build_loop_routing_classification(intent, None),
        goal="research",
        goal_user_submission="research",
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
        emit=_emit,
        ce=None,
        core_agent=SimpleNamespace(
            lookup_intake_only_subagent=lambda name: (
                {"name": "deep_research", "runnable": runnable} if name == "deep_research" else None
            )
        ),
    )
    out = await node_invoke_wired_subagent(ctx, {})  # type: ignore[arg-type]
    assert out == {"wired_route_next": "goal_completion"}
    stream_customs = [p for t, p in emitted if t == "stream_event"]
    assert stream_customs
    ns, mode, data = stream_customs[0]  # type: ignore[misc]
    assert mode == "custom"
    assert data["type"] == "soothe.subagent.deep_research.progress"
    assert data["invocation_id"]
    assert any(t == "wired_subagent_completed" for t, _ in emitted)


@pytest.mark.asyncio
async def test_invoke_wired_intake_only_forwards_wire_when_context_lost() -> None:
    """Loop-level bridge fallback still forwards events without ContextVar propagation."""
    intent = IntentClassification(
        intake_label=IntakeLabel.SIMPLE,
        wire_subagent="deep_research",
        requires_tool_use=True,
        task_complexity=TaskComplexity.SIMPLE,
    )

    async def _ainvoke(_input):  # type: ignore[no-untyped-def]
        from soothe_nano.utils.progress import emit_progress

        fresh_context = contextvars.Context()

        async def _emit_inside_fresh_context() -> None:
            emit_progress(
                {
                    "type": "soothe.subagent.deep_research.progress",
                    "phase": "gather",
                    "message": "context lost",
                },
                logging.getLogger("test.wired_bridge.context-loss"),
            )

        await asyncio.create_task(_emit_inside_fresh_context(), context=fresh_context)
        return {"messages": [AIMessage(content="streamed report")]}

    runnable = SimpleNamespace(ainvoke=_ainvoke)
    emitted: list[tuple[str, object]] = []

    async def _emit(event_type: str, payload: object) -> None:
        emitted.append((event_type, payload))
        await asyncio.sleep(0)

    loop_state = SimpleNamespace(
        intent=intent,
        routing_classification=build_loop_routing_classification(intent, None),
        goal="research",
        goal_user_submission="research",
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
        emit=_emit,
        ce=None,
        core_agent=SimpleNamespace(
            lookup_intake_only_subagent=lambda name: (
                {"name": "deep_research", "runnable": runnable} if name == "deep_research" else None
            )
        ),
    )
    out = await node_invoke_wired_subagent(ctx, {})  # type: ignore[arg-type]
    assert out == {"wired_route_next": "goal_completion"}
    stream_customs = [p for t, p in emitted if t == "stream_event"]
    assert stream_customs
    _ns, mode, data = stream_customs[0]  # type: ignore[misc]
    assert mode == "custom"
    assert data["type"] == "soothe.subagent.deep_research.progress"
    assert data["invocation_id"]


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
