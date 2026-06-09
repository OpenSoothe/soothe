"""Stream-wrapper clarification relay path (RFC-622)."""

from __future__ import annotations

from typing import Any

import pytest
from langgraph.types import Command, Interrupt

from soothe.foundation.loop.clarification import (
    ClarificationCapture,
    ClarificationDetector,
    LoopStateView,
)
from soothe.foundation.loop.engine.executor import Executor


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
    """Minimal stand-in for ``CoreAgent`` exposing only ``astream``."""

    def __init__(self) -> None:
        self.calls: list[Any] = []
        self._scripts: list[list[Any]] = []

    def queue(self, chunks: list[Any]) -> None:
        self._scripts.append(chunks)

    def astream(
        self,
        input_payload: Any,
        config: Any = None,  # noqa: ARG002
        stream_mode: Any = None,  # noqa: ARG002
        subgraphs: bool = False,  # noqa: ARG002
    ) -> Any:
        self.calls.append(input_payload)
        chunks = self._scripts.pop(0)

        async def _gen() -> Any:
            for c in chunks:
                yield c

        return _gen()


def _make_executor(core: _StubCoreAgent, **overrides: Any) -> Executor:
    return Executor(core, **overrides)  # type: ignore[arg-type]


def _ask_user_chunk(interrupt_id: str = "i1") -> tuple[tuple, str, dict]:
    interrupt = Interrupt(
        value={"type": "ask_user", "questions": ["What aspect?"]},
        id=interrupt_id,
    )
    return (("ns",), "updates", {"__interrupt__": [interrupt]})


def _action_approval_chunk(interrupt_id: str = "i2") -> tuple[tuple, str, dict]:
    interrupt = Interrupt(
        value={"action_requests": [{"name": "write", "args": {}}]},
        id=interrupt_id,
    )
    return (("ns",), "updates", {"__interrupt__": [interrupt]})


@pytest.mark.asyncio
async def test_ask_user_interrupt_captured_and_stream_stops() -> None:
    core = _StubCoreAgent()
    core.queue([_ask_user_chunk("iX")])
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

    assert len(chunks) == 1
    assert capture.pending_request is not None
    assert capture.pending_request.origin_interrupt_id == "iX"
    assert capture.pending_request.questions == ("What aspect?",)
    # No follow-up CoreAgent call (we don't auto-resume)
    assert len(core.calls) == 1


@pytest.mark.asyncio
async def test_action_approval_still_auto_resumed_when_relay_active() -> None:
    core = _StubCoreAgent()
    core.queue([_action_approval_chunk("iA")])  # first call: interrupt
    core.queue([])  # second call: resume yields nothing then finishes
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
    assert len(core.calls) == 2
    # Second call should be Command(resume=...)
    assert isinstance(core.calls[1], Command)


@pytest.mark.asyncio
async def test_resume_answer_payload_is_used_for_first_call() -> None:
    core = _StubCoreAgent()
    core.queue([])  # stream finishes immediately after resume
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
    core.queue([_ask_user_chunk("iX")])
    core.queue(
        []
    )  # legacy code would call resume; with new skip the payload is empty -> still calls

    executor = _make_executor(core)
    stream = executor._core_agent_astream_with_interrupt_resume({"messages": []}, {})
    _ = [c async for c in stream]

    # Without detector wiring, the wrapper treats the ask_user as a regular
    # interrupt: build_auto_resume_payload now skips ask_user, so the resume
    # payload is empty {}. The stream still attempts to resume once.
    assert len(core.calls) == 2
