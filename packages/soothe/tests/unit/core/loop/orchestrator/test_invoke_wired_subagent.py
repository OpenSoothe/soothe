"""/ slash wired-subagent direct route."""

from __future__ import annotations

import asyncio
import contextvars
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage
from langgraph.graph import END

from soothe.sloop.engine.execute.thread_selection import resolve_user_requested_wire_subagent
from soothe.sloop.intention.models import (
    IntakeLabel,
    IntentClassification,
    TaskComplexity,
    build_loop_routing_classification,
)
from soothe.sloop.orchestrator.routing import route_after_preprocess, route_after_wired_subagent
from soothe.sloop.state.schemas import resolve_wire_subagent
from soothe.sloop.stations.preprocess.enter_loop import node_init_or_resume
from soothe.sloop.stations.sidecars.delegate import (
    node_invoke_wired_subagent,
)


async def _noop_emit(*_args, **_kwargs) -> None:  # type: ignore[no-untyped-def]
    return None


def test_allowlist_includes_academic_research() -> None:
    assert resolve_wire_subagent(wire_subagent="explorer") is None
    assert resolve_wire_subagent(wire_subagent="academic_research") == "academic_research"
    assert resolve_wire_subagent(wire_subagent="planner") is None  # removed
    assert resolve_wire_subagent(wire_subagent="plan") is None
    assert resolve_wire_subagent(wire_subagent="not_a_subagent") is None


def test_build_loop_routing_classification_uses_slash_preferred() -> None:
    intent = IntentClassification(
        intake_label=IntakeLabel.SIMPLE,
        task_complexity=TaskComplexity.SIMPLE,
    )
    routing = build_loop_routing_classification(intent, preferred_subagent="deep_research")
    assert routing is not None
    assert routing.preferred_subagent == "deep_research"
    assert routing.routing_hint == "subagent"


def test_build_loop_routing_classification_ignores_non_allowlisted_preferred() -> None:
    intent = IntentClassification(
        intake_label=IntakeLabel.SIMPLE,
        task_complexity=TaskComplexity.SIMPLE,
    )
    routing = build_loop_routing_classification(intent, preferred_subagent="plugin_agent")
    assert routing is not None
    assert routing.preferred_subagent is None
    assert routing.routing_hint == "intent_based"


def test_intake_never_infers_a_specialist() -> None:
    """Intake carries no specialist field; only slash routing can request one."""
    assert "wire_subagent" not in IntentClassification.model_fields
    intent = IntentClassification(
        intake_label=IntakeLabel.SIMPLE,
        task_complexity=TaskComplexity.SIMPLE,
    )
    routing = build_loop_routing_classification(intent, preferred_subagent=None)
    assert routing is not None
    assert routing.preferred_subagent is None
    assert (
        resolve_user_requested_wire_subagent(
            routing_classification=routing,
            preferred_subagent="academic_research",
        )
        == "academic_research"
    )


def test_route_after_preprocess_wired_subagent() -> None:
    state = {
        "intent_route": "wired_subagent",
        "intake_label": IntakeLabel.COMPLEX,
        "is_continuation": True,
    }
    assert route_after_preprocess(state) == "delegate"


def test_route_after_preprocess_chitchat_still_wins_over_wired() -> None:
    state = {
        "intent_route": "fast_path",
        "intake_label": IntakeLabel.CHITCHAT,
        "is_continuation": False,
    }
    assert route_after_preprocess(state) == END


@pytest.mark.asyncio
async def test_init_or_resume_sets_wired_subagent_route() -> None:
    intent = IntentClassification(
        intake_label=IntakeLabel.SIMPLE,
        requires_tool_use=True,
        task_complexity=TaskComplexity.SIMPLE,
    )
    loop_state = SimpleNamespace(
        intent=intent,
        routing_classification=build_loop_routing_classification(intent, "browser_use"),
        goal="use browser_use for weather",
        goal_user_submission="use browser_use for weather",
    )
    ctx = SimpleNamespace(
        loop_state=loop_state,
        preferred_subagent="browser_use",
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
    assert route_after_preprocess(result) == "delegate"


@pytest.mark.asyncio
async def test_init_or_resume_slash_specialist_wins_over_continue_keyword_goal() -> None:
    intent = IntentClassification(
        intake_label=IntakeLabel.SIMPLE,
        requires_tool_use=True,
        task_complexity=TaskComplexity.SIMPLE,
    )
    loop_state = SimpleNamespace(
        intent=intent,
        routing_classification=build_loop_routing_classification(intent, "deep_research"),
        goal="continue",
        goal_user_submission="continue",
    )
    ctx = SimpleNamespace(
        loop_state=loop_state,
        preferred_subagent="deep_research",
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
    assert route_after_preprocess(result) == "delegate"


def test_extract_subagent_report_prefers_answer_field() -> None:
    """deep_research / academic_research put the report in state ``answer``."""
    from soothe.sloop.stations.sidecars.delegate import (
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
        requires_tool_use=True,
        task_complexity=TaskComplexity.SIMPLE,
    )
    runnable = SimpleNamespace(
        ainvoke=AsyncMock(return_value={"messages": [AIMessage(content="research report body")]})
    )
    loop_state = SimpleNamespace(
        intent=intent,
        routing_classification=build_loop_routing_classification(intent, "deep_research"),
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
        preferred_subagent="deep_research",
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
    assert out == {}
    assert route_after_wired_subagent(out) == "finalize"
    runnable.ainvoke.assert_awaited_once()
    assert ctx.scratch.plan_result is not None
    assert ctx.scratch.plan_result.decision.steps[0].subagent == "deep_research"
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
        requires_tool_use=True,
        task_complexity=TaskComplexity.SIMPLE,
    )
    body = "## Summary\n\nUS macro brief.\n\nFull report saved to: `/tmp/us.md`"
    runnable = SimpleNamespace(ainvoke=AsyncMock(return_value={"answer": body, "messages": []}))
    loop_state = SimpleNamespace(
        intent=intent,
        routing_classification=build_loop_routing_classification(intent, "deep_research"),
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
        preferred_subagent="deep_research",
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
    assert out == {}
    assert route_after_wired_subagent(out) == "finalize"
    assert any(getattr(m, "content", None) == body for m in loop_state._loop_messages_cache)
    completed = next(p for t, p in emitted if t == "wired_subagent_completed")
    assert isinstance(completed, dict)
    assert completed["summary"].startswith("## Summary")


@pytest.mark.asyncio
async def test_invoke_wired_intake_only_forwards_via_bridge_during_astream() -> None:
    """astream values + bridge: wire customs come from emit_progress, not custom mode."""
    intent = IntentClassification(
        intake_label=IntakeLabel.SIMPLE,
        requires_tool_use=True,
        task_complexity=TaskComplexity.SIMPLE,
    )

    async def _astream(_input, stream_mode=None, config=None, **_kwargs):  # type: ignore[no-untyped-def]
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
        routing_classification=build_loop_routing_classification(intent, "deep_research"),
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
        preferred_subagent="deep_research",
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
    assert out == {}
    assert route_after_wired_subagent(out) == "finalize"
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
        requires_tool_use=True,
        task_complexity=TaskComplexity.SIMPLE,
    )
    synthesized = "Weather summary: clear sky, 26C."

    async def _astream(_input, stream_mode=None, config=None, **_kwargs):  # type: ignore[no-untyped-def]
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
        routing_classification=build_loop_routing_classification(intent, "browser_use"),
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
        preferred_subagent="browser_use",
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
    assert out == {}
    assert route_after_wired_subagent(out) == "finalize"
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
        requires_tool_use=True,
        task_complexity=TaskComplexity.SIMPLE,
    )

    async def _ainvoke(_input, config=None, **_kwargs):  # type: ignore[no-untyped-def]
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
        routing_classification=build_loop_routing_classification(intent, "deep_research"),
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
        preferred_subagent="deep_research",
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
    assert out == {}
    assert route_after_wired_subagent(out) == "finalize"
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
        requires_tool_use=True,
        task_complexity=TaskComplexity.SIMPLE,
    )

    async def _ainvoke(_input, config=None, **_kwargs):  # type: ignore[no-untyped-def]
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
        routing_classification=build_loop_routing_classification(intent, "deep_research"),
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
        preferred_subagent="deep_research",
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
    assert out == {}
    assert route_after_wired_subagent(out) == "finalize"
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
