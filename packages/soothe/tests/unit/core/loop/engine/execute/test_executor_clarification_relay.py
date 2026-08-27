"""Stream-wrapper clarification relay path (RFC-622)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from langgraph.types import Command, Interrupt

from soothe.sloop.clarification.capture import ClarificationCapture
from soothe.sloop.clarification.detector import ClarificationDetector
from soothe.sloop.clarification.protocol import LoopStateView
from soothe.sloop.engine.execute.executor import Executor


def _view() -> LoopStateView:
    return LoopStateView(
        goal_id="g",
        goal_description="",
        user_request="",
        iteration=0,
        intent_classification=None,
        plan_summary=None,
        recent_step_outputs=(),
        workspace_summary=None,
        active_skills=(),
        active_mcp_servers=(),
    )


class _StubCoreAgent:
    """Minimal stand-in for ``CoreAgent`` exposing execution stream APIs."""

    def __init__(self) -> None:
        self.calls: list[Any] = []
        self._scripts: list[list[Any]] = []
        self._state_interrupts: list[tuple[Interrupt, ...]] = []

    def queue(
        self,
        chunks: list[Any],
        *,
        state_interrupts: tuple[Interrupt, ...] = (),
    ) -> None:
        self._scripts.append(chunks)
        self._state_interrupts.append(state_interrupts)

    def astream(
        self,
        input_payload: Any,
        config: Any = None,  # noqa: ARG002
        stream_mode: Any = None,  # noqa: ARG002
        subgraphs: bool = False,  # noqa: ARG002
        durability: str | None = None,  # noqa: ARG002
    ) -> Any:
        self.calls.append(input_payload)
        chunks = self._scripts.pop(0)

        async def _gen() -> Any:
            for c in chunks:
                yield c

        return _gen()

    async def aget_state(self, config: Any = None) -> Any:  # noqa: ARG002
        interrupts = self._state_interrupts.pop(0) if self._state_interrupts else ()
        return SimpleNamespace(interrupts=interrupts, tasks=(), values={})

    def execution_astream(self, *args: Any, **kwargs: Any) -> Any:
        return self.astream(*args, **kwargs)

    async def execution_aget_state(self, config: Any = None) -> Any:
        return await self.aget_state(config)


def _make_executor(core: _StubCoreAgent, **overrides: Any) -> Executor:
    return Executor(core, **overrides)  # type: ignore[arg-type]


def _ask_user_interrupt(interrupt_id: str = "i1") -> Interrupt:
    return Interrupt(
        value={"type": "ask_user", "questions": ["What aspect?"]},
        id=interrupt_id,
    )


def _action_approval_interrupt(interrupt_id: str = "i2") -> Interrupt:
    return Interrupt(
        value={"action_requests": [{"name": "write", "args": {}}]},
        id=interrupt_id,
    )


@pytest.mark.asyncio
async def test_ask_user_interrupt_captured_and_stream_stops() -> None:
    core = _StubCoreAgent()
    core.queue([], state_interrupts=(_ask_user_interrupt("iX"),))
    capture = ClarificationCapture()

    executor = _make_executor(
        core,
        clarification_detector=ClarificationDetector(),
        clarification_capture=capture,
        clarification_loop_state_view=_view(),
    )
    stream = executor._core_agent_astream_with_interrupt_resume(
        {"messages": []},
        {},
        detector=executor._clarification_detector,
        capture=executor._clarification_capture,
        loop_state_view=executor._clarification_loop_state_view,
        origin_node="execute",
    )
    chunks = [c async for c in stream]

    assert len(chunks) == 0
    assert capture.pending_request is not None
    assert capture.pending_request.origin_interrupt_id == "iX"
    assert capture.pending_request.questions == ("What aspect?",)
    assert len(core.calls) == 1


@pytest.mark.asyncio
async def test_empty_ask_user_does_not_auto_resume_spin() -> None:
    """Malformed ask_user must stop without empty Command(resume) iterations."""
    core = _StubCoreAgent()
    empty_ask = Interrupt(
        value={"type": "ask_user", "questions": ["  ", ""]},
        id="i-empty",
    )
    # Only one scripted stream turn — a spin would try to call astream again
    # and raise IndexError on _scripts.pop(0).
    core.queue([], state_interrupts=(empty_ask,))
    capture = ClarificationCapture()

    executor = _make_executor(
        core,
        clarification_detector=ClarificationDetector(),
        clarification_capture=capture,
        clarification_loop_state_view=_view(),
    )
    stream = executor._core_agent_astream_with_interrupt_resume(
        {"messages": []},
        {},
        detector=executor._clarification_detector,
        capture=executor._clarification_capture,
        loop_state_view=executor._clarification_loop_state_view,
        origin_node="execute",
    )
    _ = [c async for c in stream]

    assert capture.pending_request is None
    assert len(core.calls) == 1


@pytest.mark.asyncio
async def test_resume_answer_payload_cleared_after_use() -> None:
    core = _StubCoreAgent()
    core.queue([])
    capture = ClarificationCapture()
    payload = {"iX": {"answers": ["auth flows"]}}
    executor = _make_executor(
        core,
        clarification_detector=ClarificationDetector(),
        clarification_capture=capture,
        clarification_loop_state_view=_view(),
        clarification_resume_answer_payload=payload,
    )

    stream = executor._core_agent_astream_with_interrupt_resume(
        {"messages": []},
        {},
        detector=executor._clarification_detector,
        capture=executor._clarification_capture,
        loop_state_view=executor._clarification_loop_state_view,
        origin_node="execute",
        resume_answer_payload=payload,
    )
    _ = [c async for c in stream]

    assert executor._clarification_resume_answer_payload is None


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_action_requests_captured_as_tool_approval_when_relay_active() -> None:
    """action_requests interrupts are captured into the relay (tool_approval),
    not auto-resumed. The relay owns the pause."""
    core = _StubCoreAgent()
    core.queue([], state_interrupts=(_action_approval_interrupt("iA"),))
    capture = ClarificationCapture()

    executor = _make_executor(
        core,
        clarification_detector=ClarificationDetector(),
        clarification_capture=capture,
        clarification_loop_state_view=_view(),
    )
    stream = executor._core_agent_astream_with_interrupt_resume(
        {"messages": []},
        {},
        detector=executor._clarification_detector,
        capture=executor._clarification_capture,
        loop_state_view=executor._clarification_loop_state_view,
        origin_node="execute",
    )
    _ = [c async for c in stream]

    assert capture.pending_request is not None
    assert capture.pending_request.origin_node == "tool_approval"
    assert len(core.calls) == 1  # no auto-resume


@pytest.mark.asyncio
async def test_resume_answer_payload_is_used_for_first_call() -> None:
    core = _StubCoreAgent()
    core.queue([])
    capture = ClarificationCapture()

    payload = {"iX": {"answers": ["auth flows"]}}
    executor = _make_executor(
        core,
        clarification_detector=ClarificationDetector(),
        clarification_capture=capture,
        clarification_loop_state_view=_view(),
        clarification_resume_answer_payload=payload,
    )

    stream = executor._core_agent_astream_with_interrupt_resume(
        {"messages": []},
        {},
        detector=executor._clarification_detector,
        capture=executor._clarification_capture,
        loop_state_view=executor._clarification_loop_state_view,
        origin_node="execute",
        resume_answer_payload=payload,
    )
    _ = [c async for c in stream]

    assert len(core.calls) == 1
    call = core.calls[0]
    assert isinstance(call, Command)
    assert call.resume == payload


@pytest.mark.asyncio
async def test_relay_disabled_when_detector_absent_keeps_legacy_behavior() -> None:
    """Without detector+capture, ``ask_user`` flows back into auto-resume (which now skips it)."""
    core = _StubCoreAgent()
    core.queue([], state_interrupts=(_ask_user_interrupt("iX"),))
    core.queue([])

    executor = _make_executor(core)
    stream = executor._core_agent_astream_with_interrupt_resume({"messages": []}, {})
    _ = [c async for c in stream]

    assert len(core.calls) == 2
