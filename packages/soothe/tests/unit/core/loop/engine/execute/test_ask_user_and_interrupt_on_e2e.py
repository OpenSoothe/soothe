"""End-to-end case tests for ask_user tool interrupts and interrupt_on HITL surfacing.

These tests exercise the full executor → capture → resume pipeline for both
clarification origins:

1. **ask_user** — the CoreAgent calls the ``ask_user`` host tool, which emits
   ``interrupt({"type":"ask_user","questions":[...]})``. The executor captures
   it, routes to ``AWAIT_USER``, the policy answers, and the graph resumes.

2. **interrupt_on** — the deepagents ``HumanInTheLoopMiddleware`` emits
   ``interrupt({"action_requests":[...]})`` when a tool call matches an
   ``interrupt_on`` rule. The executor captures it as ``tool_approval``, the
   policy answers approve/reject, and the graph resumes with a
   ``{"decisions":[...]}`` payload.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from langgraph.types import Command, Interrupt

from soothe.sloop.clarification import (
    ORIGIN_EXECUTE,
    ORIGIN_TOOL_APPROVAL,
    ClarificationCapture,
    ClarificationDetector,
    LoopStateView,
)
from soothe.sloop.engine.execute.executor import Executor
from soothe.sloop.engine.execute.graph_interrupt import (
    build_auto_resume_payload,
    build_tool_approval_resume_payload,
    is_ask_user_interrupt,
    is_tool_approval_interrupt,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _view() -> LoopStateView:
    return LoopStateView(
        goal_id="g",
        goal_description="build feature X",
        user_request="build feature X",
        iteration=0,
        intent_classification=None,
        plan_summary=None,
        recent_step_outputs=(),
        workspace_summary=None,
        active_skills=(),
        active_mcp_servers=(),
    )


class _StubCoreAgent:
    """Minimal CoreAgent stand-in with scriptable streams + state interrupts."""

    def __init__(self) -> None:
        self.calls: list[Any] = []  # input payloads per astream() call
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

    def astream(self, input_payload: Any, config: Any = None, **kwargs: Any) -> Any:
        self.calls.append(input_payload)
        chunks = self._scripts.pop(0)

        async def _gen() -> Any:
            for c in chunks:
                yield c

        return _gen()

    async def aget_state(self, config: Any = None) -> Any:
        interrupts = self._state_interrupts.pop(0) if self._state_interrupts else ()
        return SimpleNamespace(interrupts=interrupts, tasks=(), values={})

    def execution_astream(self, *args: Any, **kwargs: Any) -> Any:
        return self.astream(*args, **kwargs)

    async def execution_aget_state(self, config: Any = None) -> Any:
        return await self.aget_state(config)

    @property
    def can_read_graph_state(self) -> bool:
        return True


def _ask_user_interrupt(questions: list[str], *, interrupt_id: str = "iAU") -> Interrupt:
    return Interrupt(
        value={"type": "ask_user", "questions": questions},
        id=interrupt_id,
    )


def _action_approval_interrupt(
    tool: str = "edit_file",
    *,
    interrupt_id: str = "iTA",
    args: dict[str, Any] | None = None,
) -> Interrupt:
    return Interrupt(
        value={
            "action_requests": [
                {"name": tool, "args": args or {"file_path": "/workspace/src/x.py"}}
            ]
        },
        id=interrupt_id,
    )


def _make_executor(core: _StubCoreAgent, **overrides: Any) -> Executor:
    return Executor(core, **overrides)  # type: ignore[arg-type]


# ===========================================================================
# CASE 1: ask_user tool interrupt — full capture → policy → resume cycle
# ===========================================================================


class TestAskUserInterruptCase:
    """Case: agent calls ask_user tool → interrupt → capture → AWAIT_USER → resume."""

    def test_ask_user_interrupt_detected(self) -> None:
        """is_ask_user_interrupt recognizes the ask_user payload shape."""
        assert is_ask_user_interrupt({"type": "ask_user", "questions": ["q"]})
        assert not is_ask_user_interrupt({"action_requests": []})
        assert not is_ask_user_interrupt("not a mapping")

    def test_detector_captures_ask_user(self) -> None:
        """ClarificationDetector.from_interrupt builds a request with ORIGIN_EXECUTE."""
        detector = ClarificationDetector()
        req = detector.from_interrupt(
            {"type": "ask_user", "questions": ["Which DB: postgres or sqlite?"]},
            interrupt_id="iAU",
            origin_node=ORIGIN_EXECUTE,
            loop_state=_view(),
        )
        assert req is not None
        assert req.origin_node == ORIGIN_EXECUTE
        assert req.questions == ("Which DB: postgres or sqlite?",)
        assert req.origin_interrupt_id == "iAU"

    @pytest.mark.asyncio
    async def test_ask_user_captured_and_stream_stops(self) -> None:
        """When an ask_user interrupt is pending, the executor captures it and
        returns early (no auto-resume) — the clarification relay owns the pause."""
        core = _StubCoreAgent()
        core.queue([], state_interrupts=(_ask_user_interrupt(["Approve design?"]),))
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
            origin_node=ORIGIN_EXECUTE,
        )
        _ = [c async for c in stream]

        # Captured → the relay has the request
        assert capture.pending_request is not None
        assert capture.pending_request.origin_node == ORIGIN_EXECUTE
        assert capture.pending_request.questions == ("Approve design?",)
        # Stream returned early — no second astream() call (no auto-resume)
        assert len(core.calls) == 1

    @pytest.mark.asyncio
    async def test_ask_user_resume_payload_shape(self) -> None:
        """On resume, the executor feeds the CoreAgent a ``Command(resume=...)``
        whose payload is shaped as ``{iid: {"answers": [...]}}``."""
        core = _StubCoreAgent()
        # Single stream: no interrupts, just observe the resume input the
        # executor forwards to the CoreAgent on re-entry.
        core.queue([])
        executor = _make_executor(
            core,
            clarification_detector=ClarificationDetector(),
            clarification_capture=ClarificationCapture(),
            clarification_loop_state_view=_view(),
        )
        resume_payload = {"i1": {"answers": ["Option C"]}}
        stream = executor._core_agent_astream_with_interrupt_resume(
            {"messages": []},
            {},
            detector=executor._clarification_detector,
            capture=executor._clarification_capture,
            loop_state_view=executor._clarification_loop_state_view,
            origin_node=ORIGIN_EXECUTE,
            resume_answer_payload=resume_payload,
        )
        _ = [c async for c in stream]

        # The executor's first (and only) CoreAgent call must be a Command
        # carrying the resume payload verbatim — that is the shape the
        # deepagents ask_user interrupt expects on Command(resume=...).
        assert len(core.calls) == 1
        first_input = core.calls[0]
        assert isinstance(first_input, Command)
        assert first_input.resume == {"i1": {"answers": ["Option C"]}}


# ===========================================================================
# CASE 2: interrupt_on (action_requests) — full capture → policy → resume
# ===========================================================================


class TestInterruptOnCase:
    """Case: HumanInTheLoopMiddleware emits action_requests → capture → AWAIT_USER → resume with decisions."""

    def test_action_requests_interrupt_detected(self) -> None:
        """is_tool_approval_interrupt recognizes the action_requests payload."""
        assert is_tool_approval_interrupt({"action_requests": [{"name": "edit_file"}]})
        assert not is_tool_approval_interrupt({"type": "ask_user", "questions": ["q"]})
        assert not is_tool_approval_interrupt({"foo": "bar"})

    def test_detector_captures_tool_approval(self) -> None:
        """from_tool_approval_interrupt builds a request with ORIGIN_TOOL_APPROVAL."""
        detector = ClarificationDetector()
        req = detector.from_tool_approval_interrupt(
            {"action_requests": [{"name": "edit_file", "args": {"file_path": "/w/x.py"}}]},
            interrupt_id="iTA",
            loop_state=_view(),
        )
        assert req is not None
        assert req.origin_node == ORIGIN_TOOL_APPROVAL
        assert "edit_file" in req.questions[0]
        assert "/w/x.py" in req.questions[0]
        assert "approve" in req.questions[0].lower()

    def test_detector_formats_run_command(self) -> None:
        """A destructive run_command surfaces the command in the question."""
        detector = ClarificationDetector()
        req = detector.from_tool_approval_interrupt(
            {"action_requests": [{"name": "run_command", "args": {"command": "rm -rf /"}}]},
            interrupt_id="i",
            loop_state=_view(),
        )
        assert req is not None
        assert "rm -rf /" in req.questions[0]

    @pytest.mark.asyncio
    async def test_action_requests_captured_and_stream_stops(self) -> None:
        """When an action_requests interrupt is pending, the executor captures
        it (tool_approval origin) and returns early — no auto-resume."""
        core = _StubCoreAgent()
        core.queue([], state_interrupts=(_action_approval_interrupt("edit_file"),))
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
            origin_node=ORIGIN_EXECUTE,
        )
        _ = [c async for c in stream]

        assert capture.pending_request is not None
        assert capture.pending_request.origin_node == ORIGIN_TOOL_APPROVAL
        # No auto-resume (only 1 astream call)
        assert len(core.calls) == 1

    def test_resume_payload_for_approve(self) -> None:
        """The resume payload for an approved tool call has the decisions shape."""
        payload = build_tool_approval_resume_payload("iTA", decisions=[{"type": "approve"}])
        assert payload == {"iTA": {"decisions": [{"type": "approve"}]}}

    def test_resume_payload_for_reject(self) -> None:
        """The resume payload for a rejected tool call."""
        payload = build_tool_approval_resume_payload("iTA", decisions=[{"type": "reject"}])
        assert payload == {"iTA": {"decisions": [{"type": "reject"}]}}

    def test_answer_to_decision_approve(self) -> None:
        """Veritas/TUI answer 'approve' → HITL decision type 'approve'."""
        from soothe.sloop.stations.execute.execute import _answer_to_decision

        assert _answer_to_decision("approve") == "approve"
        assert _answer_to_decision("yes") == "approve"
        assert _answer_to_decision("ok") == "approve"

    def test_answer_to_decision_reject(self) -> None:
        from soothe.sloop.stations.execute.execute import _answer_to_decision

        assert _answer_to_decision("reject") == "reject"
        assert _answer_to_decision("no") == "reject"
        assert _answer_to_decision("deny") == "reject"

    def test_answer_to_decision_edit(self) -> None:
        from soothe.sloop.stations.execute.execute import _answer_to_decision

        assert _answer_to_decision("edit") == "edit"
        assert _answer_to_decision("modify") == "edit"

    def test_auto_resume_skips_both_ask_user_and_action_requests(self) -> None:
        """build_auto_resume_payload must skip both interrupt shapes —
        neither is auto-approved; both are owned by the relay."""
        payload = build_auto_resume_payload(
            {
                "i1": {"type": "ask_user", "questions": ["q"]},
                "i2": {"action_requests": [{"name": "edit_file"}]},
                "i3": {"other": "interrupt"},
            }
        )
        # i1 and i2 skipped (owned by relay); i3 auto-approved
        assert "i1" not in payload
        assert "i2" not in payload
        assert "i3" in payload
        assert payload["i3"] == {"decisions": [{"type": "approve"}]}


# ===========================================================================
# CASE 3: Full round-trip — ask_user → answer → resume → completion
# ===========================================================================


class TestAskUserRoundTripCase:
    """Case: agent asks → user answers → graph resumes on same goal → completes."""

    @pytest.mark.asyncio
    async def test_ask_user_then_answer_then_resume(self) -> None:
        """Simulate: stream emits ask_user interrupt, then on resume the answer
        is injected as a Command(resume=...) and the stream completes normally."""
        core = _StubCoreAgent()
        # Wave 1: ask_user interrupt → captured
        core.queue([], state_interrupts=(_ask_user_interrupt(["Which DB?"], interrupt_id="i1"),))
        # Wave 2: resume with answer → no more interrupts → done
        core.queue([])
        capture = ClarificationCapture()
        executor = _make_executor(
            core,
            clarification_detector=ClarificationDetector(),
            clarification_capture=capture,
            clarification_loop_state_view=_view(),
        )

        # Wave 1: the interrupt is captured
        stream = executor._core_agent_astream_with_interrupt_resume(
            {"messages": []},
            {},
            detector=executor._clarification_detector,
            capture=executor._clarification_capture,
            loop_state_view=executor._clarification_loop_state_view,
            origin_node=ORIGIN_EXECUTE,
        )
        _ = [c async for c in stream]
        assert capture.pending_request is not None
        assert len(core.calls) == 1

        # Simulate the policy answering + the graph re-entering with resume
        resume_payload = {"i1": {"answers": ["postgres"]}}
        stream2 = executor._core_agent_astream_with_interrupt_resume(
            {"messages": []},
            {},
            detector=executor._clarification_detector,
            capture=executor._clarification_capture,
            loop_state_view=executor._clarification_loop_state_view,
            origin_node=ORIGIN_EXECUTE,
            resume_answer_payload=resume_payload,
        )
        _ = [c async for c in stream2]
        # Wave 2 ran (resume) and completed (no more interrupts)
        assert len(core.calls) == 2
        assert isinstance(core.calls[1], Command)


# ===========================================================================
# CASE 4: Full round-trip — interrupt_on → approve → resume → completion
# ===========================================================================


class TestInterruptOnRoundTripCase:
    """Case: HITL interrupt → user approves → graph resumes with decisions."""

    @pytest.mark.asyncio
    async def test_action_requests_then_approve_then_resume(self) -> None:
        core = _StubCoreAgent()
        # Wave 1: action_requests interrupt → captured
        core.queue(
            [], state_interrupts=(_action_approval_interrupt("edit_file", interrupt_id="i1"),)
        )
        # Wave 2: resume with approve decision → done
        core.queue([])
        capture = ClarificationCapture()
        executor = _make_executor(
            core,
            clarification_detector=ClarificationDetector(),
            clarification_capture=capture,
            clarification_loop_state_view=_view(),
        )

        # Wave 1: captured
        stream = executor._core_agent_astream_with_interrupt_resume(
            {"messages": []},
            {},
            detector=executor._clarification_detector,
            capture=executor._clarification_capture,
            loop_state_view=executor._clarification_loop_state_view,
            origin_node=ORIGIN_EXECUTE,
        )
        _ = [c async for c in stream]
        assert capture.pending_request is not None
        assert capture.pending_request.origin_node == ORIGIN_TOOL_APPROVAL
        assert len(core.calls) == 1

        # Simulate the policy approving + graph re-entering
        resume_payload = build_tool_approval_resume_payload("i1", decisions=[{"type": "approve"}])
        stream2 = executor._core_agent_astream_with_interrupt_resume(
            {"messages": []},
            {},
            detector=executor._clarification_detector,
            capture=executor._clarification_capture,
            loop_state_view=executor._clarification_loop_state_view,
            origin_node=ORIGIN_EXECUTE,
            resume_answer_payload=resume_payload,
        )
        _ = [c async for c in stream2]
        assert len(core.calls) == 2
        assert isinstance(core.calls[1], Command)

    @pytest.mark.asyncio
    async def test_action_requests_then_reject_then_resume(self) -> None:
        """Rejecting a tool call also resumes the graph (the tool is skipped)."""
        core = _StubCoreAgent()
        core.queue([], state_interrupts=(_action_approval_interrupt("delete", interrupt_id="i2"),))
        core.queue([])
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
            origin_node=ORIGIN_EXECUTE,
        )
        _ = [c async for c in stream]
        assert capture.pending_request.origin_node == ORIGIN_TOOL_APPROVAL

        # Reject resume
        resume_payload = build_tool_approval_resume_payload("i2", decisions=[{"type": "reject"}])
        stream2 = executor._core_agent_astream_with_interrupt_resume(
            {"messages": []},
            {},
            detector=executor._clarification_detector,
            capture=executor._clarification_capture,
            loop_state_view=executor._clarification_loop_state_view,
            origin_node=ORIGIN_EXECUTE,
            resume_answer_payload=resume_payload,
        )
        _ = [c async for c in stream2]
        assert len(core.calls) == 2


# ===========================================================================
# CASE 5: ask_user tool itself (the StructuredTool handler)
# ===========================================================================


class TestAskUserToolHandlerCase:
    """Case: the ask_user StructuredTool handler calls interrupt() and returns answers."""

    def test_tool_emits_ask_user_interrupt(self) -> None:
        """When the LLM calls ask_user, the handler emits interrupt({"type":"ask_user",...})."""
        from soothe.coreagent.tools.ask_user import _run_ask_user

        captured: list[dict[str, Any]] = []

        def fake_interrupt(value: Any) -> Any:
            captured.append(value)
            return {"answers": ["Option B"]}

        with patch("langgraph.types.interrupt", fake_interrupt):
            result = _run_ask_user(["Which option: A or B?"])

        assert len(captured) == 1
        assert captured[0]["type"] == "ask_user"
        assert captured[0]["questions"] == ["Which option: A or B?"]
        assert "Option B" in result

    def test_tool_returns_dismissed_message_on_empty_answer(self) -> None:
        from soothe.coreagent.tools.ask_user import _run_ask_user

        with patch("langgraph.types.interrupt", lambda v: None):
            result = _run_ask_user(["Approve?"])
        assert "dismissed" in result.lower()

    @pytest.mark.asyncio
    async def test_tool_async_path(self) -> None:
        from soothe.coreagent.tools.ask_user import build_ask_user_tool

        with patch("langgraph.types.interrupt", lambda v: {"answers": ["yes"]}):
            tool = build_ask_user_tool()
            result = await tool.ainvoke({"questions": ["Approve the plan?"]})
        assert "yes" in result


# ===========================================================================
# CASE 6: Multi-action interrupt (multiple tools in one interrupt)
# ===========================================================================


class TestMultiActionInterruptCase:
    """Case: a single interrupt carries multiple action_requests (batch approval)."""

    def test_detector_captures_multiple_actions(self) -> None:
        detector = ClarificationDetector()
        req = detector.from_tool_approval_interrupt(
            {
                "action_requests": [
                    {"name": "edit_file", "args": {"file_path": "/a.py"}},
                    {"name": "write_file", "args": {"file_path": "/b.py"}},
                ]
            },
            interrupt_id="iMulti",
            loop_state=_view(),
        )
        assert req is not None
        assert len(req.questions) == 2
        assert "edit_file" in req.questions[0]
        assert "write_file" in req.questions[1]

    def test_multi_action_resume_payload_has_one_decision_per_action(self) -> None:
        """The resume payload must carry one decision per action_request."""
        payload = build_tool_approval_resume_payload(
            "iMulti",
            decisions=[
                {"type": "approve"},
                {"type": "reject"},
            ],
        )
        assert len(payload["iMulti"]["decisions"]) == 2
        assert payload["iMulti"]["decisions"][0]["type"] == "approve"
        assert payload["iMulti"]["decisions"][1]["type"] == "reject"
