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

from soothe.sloop.clarification.capture import ClarificationQueue, ResumeTicket
from soothe.sloop.clarification.detector import ClarificationDetector
from soothe.sloop.clarification.origins import ORIGIN_EXECUTE, ORIGIN_TOOL_APPROVAL
from soothe.sloop.clarification.protocol import LoopStateView
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
        capture = ClarificationQueue()
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
        assert capture.head is not None
        assert capture.head.origin_node == ORIGIN_EXECUTE
        assert capture.head.questions == ("Approve design?",)
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
            clarification_capture=ClarificationQueue(),
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
        q = req.questions[0]
        assert isinstance(q, dict)
        assert "edit_file" in q["header"]
        assert "/w/x.py" in q["header"]
        assert "approve" in q["header"].lower()

    def test_detector_formats_run_command(self) -> None:
        """A destructive run_command surfaces the command in the question."""
        detector = ClarificationDetector()
        req = detector.from_tool_approval_interrupt(
            {"action_requests": [{"name": "run_command", "args": {"command": "rm -rf /"}}]},
            interrupt_id="i",
            loop_state=_view(),
        )
        assert req is not None
        q = req.questions[0]
        assert isinstance(q, dict)
        assert "rm -rf /" in q["header"]

    @pytest.mark.asyncio
    async def test_action_requests_captured_and_stream_stops(self) -> None:
        """When an action_requests interrupt is pending, the executor captures
        it (tool_approval origin) and returns early — no auto-resume."""
        core = _StubCoreAgent()
        core.queue([], state_interrupts=(_action_approval_interrupt("edit_file"),))
        capture = ClarificationQueue()
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

        assert capture.head is not None
        assert capture.head.origin_node == ORIGIN_TOOL_APPROVAL
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
        capture = ClarificationQueue()
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
        assert capture.head is not None
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
        capture = ClarificationQueue()
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
        assert capture.head is not None
        assert capture.head.origin_node == ORIGIN_TOOL_APPROVAL
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
        capture = ClarificationQueue()
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
        assert capture.head.origin_node == ORIGIN_TOOL_APPROVAL

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
        from soothe.coreagent.tools.ask_user import OptionSpec, QuestionSpec, _run_ask_user

        q = QuestionSpec(
            question="Which option: A or B?",
            header="Choose",
            options=[
                OptionSpec(label="Option A", description="First option."),
                OptionSpec(label="Option B", description="Second option."),
                OptionSpec(label="Neither", description="Decline both."),
            ],
        )

        captured: list[dict[str, Any]] = []

        def fake_interrupt(value: Any) -> Any:
            captured.append(value)
            return {"answers": ["Option B"]}

        with patch("langgraph.types.interrupt", fake_interrupt):
            result = _run_ask_user([q])

        assert len(captured) == 1
        assert captured[0]["type"] == "ask_user"
        assert captured[0]["questions"][0]["question"] == "Which option: A or B?"
        assert "Option B" in result

    def test_tool_returns_dismissed_message_on_empty_answer(self) -> None:
        from soothe.coreagent.tools.ask_user import OptionSpec, QuestionSpec, _run_ask_user

        q = QuestionSpec(
            question="Approve the plan?",
            header="Approve",
            options=[
                OptionSpec(label="Yes", description="Approve."),
                OptionSpec(label="No", description="Reject."),
                OptionSpec(label="Maybe", description="Defer."),
            ],
        )

        with patch("langgraph.types.interrupt", lambda v: None):
            result = _run_ask_user([q])
        assert "dismissed" in result.lower()

    @pytest.mark.asyncio
    async def test_tool_async_path(self) -> None:
        from soothe.coreagent.tools.ask_user import OptionSpec, QuestionSpec, build_ask_user_tool

        q = QuestionSpec(
            question="Approve the plan?",
            header="Approve",
            options=[
                OptionSpec(label="Yes", description="Approve."),
                OptionSpec(label="No", description="Reject."),
                OptionSpec(label="Maybe", description="Defer."),
            ],
        )

        with patch("langgraph.types.interrupt", lambda v: {"answers": ["yes"]}):
            tool = build_ask_user_tool()
            result = await tool.ainvoke({"questions": [q.model_dump()]})
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
        assert "edit_file" in req.questions[0]["header"]
        assert "write_file" in req.questions[1]["header"]

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


# ===========================================================================
# CASE 6: step identity capture — ResumeTicket thread_id / step_id / step_description
# ===========================================================================


class TestStepIdentityCaptureCase:
    """The executor records the originating step id + description on the capture
    so the resume path can re-emit ``step_started`` with the same identity the
    TUI already has a card for (not the CE root node)."""

    @pytest.mark.asyncio
    async def test_ask_user_capture_records_step_identity(self) -> None:
        """A GraphInterrupt during a step's stream captures step_id + description."""
        core = _StubCoreAgent()
        core.queue([], state_interrupts=(_ask_user_interrupt(["Approve design?"]),))
        capture = ClarificationQueue()
        executor = _make_executor(
            core,
            clarification_detector=ClarificationDetector(),
            clarification_capture=capture,
            clarification_loop_state_view=_view(),
        )
        stream = executor._core_agent_astream_with_interrupt_resume(
            {"messages": []},
            {"configurable": {"thread_id": "loop-1__abc"}},
            detector=executor._clarification_detector,
            capture=executor._clarification_capture,
            loop_state_view=executor._clarification_loop_state_view,
            origin_node=ORIGIN_EXECUTE,
            step_id="step-42",
            step_description="Refactor auth module",
        )
        _ = [c async for c in stream]

        assert capture.head is not None
        assert capture.head_ticket is not None
        assert capture.head_ticket.thread_id == "loop-1__abc"
        assert capture.head_ticket.step_id == "step-42"
        assert capture.head_ticket.step_description == "Refactor auth module"

    @pytest.mark.asyncio
    async def test_tool_approval_capture_records_step_identity(self) -> None:
        """A tool_approval interrupt also captures the originating step identity."""
        core = _StubCoreAgent()
        core.queue(
            [],
            state_interrupts=(_action_approval_interrupt("edit_file", interrupt_id="iTA"),),
        )
        capture = ClarificationQueue()
        executor = _make_executor(
            core,
            clarification_detector=ClarificationDetector(),
            clarification_capture=capture,
            clarification_loop_state_view=_view(),
        )
        stream = executor._core_agent_astream_with_interrupt_resume(
            {"messages": []},
            {"configurable": {"thread_id": "loop-1__def"}},
            detector=executor._clarification_detector,
            capture=executor._clarification_capture,
            loop_state_view=executor._clarification_loop_state_view,
            origin_node=ORIGIN_EXECUTE,
            step_id="step-7",
            step_description="Write the migration script",
        )
        _ = [c async for c in stream]

        assert capture.head is not None
        assert capture.head.origin_node == ORIGIN_TOOL_APPROVAL
        assert capture.head_ticket is not None
        assert capture.head_ticket.thread_id == "loop-1__def"
        assert capture.head_ticket.step_id == "step-7"
        assert capture.head_ticket.step_description == "Write the migration script"

    @pytest.mark.asyncio
    async def test_no_step_id_leaves_resume_step_fields_none(self) -> None:
        """When step_id/step_description are not passed (legacy callers), the
        ticket keeps only thread_id — step_id/description stay None so the
        resume path falls back to the CE root."""
        core = _StubCoreAgent()
        core.queue([], state_interrupts=(_ask_user_interrupt(["q?"]),))
        capture = ClarificationQueue()
        executor = _make_executor(
            core,
            clarification_detector=ClarificationDetector(),
            clarification_capture=capture,
            clarification_loop_state_view=_view(),
        )
        stream = executor._core_agent_astream_with_interrupt_resume(
            {"messages": []},
            {"configurable": {"thread_id": "t"}},
            detector=executor._clarification_detector,
            capture=executor._clarification_capture,
            loop_state_view=executor._clarification_loop_state_view,
            origin_node=ORIGIN_EXECUTE,
        )
        _ = [c async for c in stream]

        assert capture.head_ticket is not None
        assert capture.head_ticket.thread_id == "t"
        assert capture.head_ticket.step_id is None
        assert capture.head_ticket.step_description is None


# ===========================================================================
# CASE 7: step scoring — a captured ask_user interrupt is not a step failure
# ===========================================================================


class TestCapturedClarificationScoringCase:
    """A step whose stream ended in a captured ask_user interrupt scores as
    awaiting-user, not failed — even when earlier tool calls errored before
    the interrupt fired (e.g. ask_user with empty questions, then a retry
    with valid questions)."""

    @staticmethod
    def _executor_with_capture(
        capture: ClarificationQueue,
    ) -> tuple[Executor, ClarificationQueue]:
        executor = _make_executor(
            _StubCoreAgent(),
            clarification_detector=ClarificationDetector(),
            clarification_capture=capture,
            clarification_loop_state_view=_view(),
        )
        return executor, capture

    @pytest.mark.asyncio
    async def test_captured_clarification_scores_step_success(self) -> None:
        """All tool outcomes errored + captured ask_user → step success."""
        from collections.abc import AsyncIterator
        from unittest.mock import MagicMock, patch

        from langchain_core.messages import AIMessage

        from soothe.sloop.clarification.protocol import ClarificationRequest
        from soothe.sloop.engine.execute.step_wave_types import _StreamCollectChunk
        from soothe.sloop.state.schemas import StepAction

        capture = ClarificationQueue()
        executor, capture = self._executor_with_capture(capture)
        executor.core_agent = MagicMock()
        executor.core_agent.can_read_graph_state = False

        async def fake_stream_and_collect(
            _stream: Any, **_kwargs: Any
        ) -> AsyncIterator[_StreamCollectChunk]:
            # Simulate the interrupt capture happening mid-stream.
            capture.enqueue(
                ClarificationRequest(
                    questions=("What next?",),
                    origin_node=ORIGIN_EXECUTE,
                    origin_interrupt_id="iAU",
                    loop_state=_view(),
                ),
                resume_ticket=ResumeTicket(),
            )
            yield _StreamCollectChunk.finalized(
                output="I attempted to ask the user a follow-up question.",
                main_tool_count=1,
                messages=[AIMessage(content="I attempted to ask the user a follow-up question.")],
                delegate_final="",
                outcomes=[
                    {
                        "type": "tool",
                        "tool_name": "ask_user",
                        "has_error": True,
                        "error_preview": "ask_user emitted a placeholder question",
                    }
                ],
                has_error=True,
                subgraph_tool_count=0,
            )

        step = StepAction(id="step-ask", description="Propose a question using ask_user")

        with patch.object(executor, "_stream_and_collect", side_effect=fake_stream_and_collect):
            result = await executor._execute_step_collecting_events(step, "thread-1")

        assert result.step_result is not None
        assert result.step_result.success is True
        assert result.step_result.error is None

    @pytest.mark.asyncio
    async def test_tool_errors_without_capture_still_fail_step(self) -> None:
        """Without a captured clarification, all-errored outcomes still fail."""
        from collections.abc import AsyncIterator
        from unittest.mock import MagicMock, patch

        from langchain_core.messages import AIMessage

        from soothe.sloop.engine.execute.step_wave_types import _StreamCollectChunk
        from soothe.sloop.state.schemas import StepAction

        executor = _make_executor(_StubCoreAgent())
        executor.core_agent = MagicMock()
        executor.core_agent.can_read_graph_state = False

        async def fake_stream_and_collect(
            _stream: Any, **_kwargs: Any
        ) -> AsyncIterator[_StreamCollectChunk]:
            yield _StreamCollectChunk.finalized(
                output="tool blew up",
                main_tool_count=1,
                messages=[AIMessage(content="tool blew up")],
                delegate_final="",
                outcomes=[
                    {
                        "type": "tool",
                        "tool_name": "run_command",
                        "has_error": True,
                        "error_preview": "boom",
                    }
                ],
                has_error=True,
                subgraph_tool_count=0,
            )

        step = StepAction(id="step-1", description="run the thing")

        with patch.object(executor, "_stream_and_collect", side_effect=fake_stream_and_collect):
            result = await executor._execute_step_collecting_events(step, "thread-1")

        assert result.step_result is not None
        assert result.step_result.success is False
        assert result.step_result.error_type == "tool"


# ===========================================================================
# CASE 8: clarification answer resume — stream config checkpoint hygiene (IG-763)
# ===========================================================================


class TestResumeStreamConfigCase:
    """Clarification answer resumes deliver ``Command(resume=...)`` on the
    interrupted thread; the stream config must not inherit the parent graph's
    checkpoint namespace (covered by test_stream_config_checkpoint_ns.py at
    the merge level). Here: the resume payload reaches the CoreAgent as the
    first stream input and is consumed one-shot."""

    @pytest.mark.asyncio
    async def test_ask_user_resume_payload_shape_forwarded(self) -> None:
        """The ask_user answer payload ({iid: {"answers": [...]}}) is forwarded
        as the first CoreAgent input (Command resume)."""
        core = _StubCoreAgent()
        core.queue([])
        executor = _make_executor(core)
        executor._clarification_resume_answer_payload = {"i1": {"answers": ["run tests"]}}

        stream = executor._core_agent_astream_with_interrupt_resume(
            {"messages": ["EXECUTION TASK envelope"]},
            {},
            resume_answer_payload=executor._clarification_resume_answer_payload,
        )
        _ = [c async for c in stream]

        assert len(core.calls) == 1
        first_input = core.calls[0]
        assert isinstance(first_input, Command)
        assert first_input.resume == {"i1": {"answers": ["run tests"]}}
        # One-shot: consumed, not reused by later steps sharing the Executor.
        assert executor._clarification_resume_answer_payload is None


# ---------------------------------------------------------------------------
# Structured ask_user wire round-trip (RFC-622 §9c)
# ---------------------------------------------------------------------------


class TestStructuredAskUserWireRoundTrip:
    """Verify that structured ``QuestionSpec`` payloads survive the full
    interrupt → capture → resume → ``_format_answers`` cycle and produce
    model-readable Q&A text with title extraction."""

    @pytest.mark.asyncio
    async def test_structured_interrupt_detected(self) -> None:
        """A structured ask_user interrupt (QuestionSpec dicts) is detected
        by the detector and questions survive as structured dicts."""
        from soothe.coreagent.tools.ask_user import OptionSpec, QuestionSpec
        from soothe.sloop.clarification.detector import ClarificationDetector

        q = QuestionSpec(
            question="How should the API authenticate requests?",
            header="Auth method",
            options=[
                OptionSpec(label="OAuth", description="OAuth 2.0 with PKCE."),
                OptionSpec(label="API key", description="Static API key in a header."),
                OptionSpec(label="Session", description="Server-side session with cookies."),
            ],
        )
        interrupt_value = {"type": "ask_user", "questions": [q.model_dump()]}

        # Detector should recognize this as an ask_user interrupt.
        assert is_ask_user_interrupt(interrupt_value)

        # Detect via the detector.
        detector = ClarificationDetector()
        capture = detector.from_interrupt(
            interrupt_value,
            interrupt_id="struct-i1",
            origin_node=ORIGIN_EXECUTE,
            loop_state=_view(),
        )
        assert capture is not None
        assert capture.origin_node == ORIGIN_EXECUTE
        # Questions survive as structured dicts (not flattened to strings).
        assert isinstance(capture.questions[0], dict)
        assert capture.questions[0]["header"] == "Auth method"
        assert len(capture.questions[0]["options"]) == 3

    def test_structured_format_answers_uses_question(self) -> None:
        """``_format_answers`` extracts the question text from QuestionSpec dicts
        when rendering the resume payload for the model."""
        from soothe.coreagent.tools.ask_user import _format_answers

        questions = [
            {
                "question": "How to authenticate?",
                "header": "Auth method",
                "options": [
                    {"label": "OAuth", "description": "..."},
                    {"label": "API key", "description": "..."},
                    {"label": "Session", "description": "..."},
                ],
            }
        ]
        out = _format_answers(questions, {"answers": ["OAuth"]})
        assert "Q: How to authenticate?" in out
        assert "A: OAuth" in out

    def test_structured_format_answers_multiple_questions(self) -> None:
        """Multiple structured questions render as separate Q/A pairs with
        question text extracted from each QuestionSpec dict."""
        from soothe.coreagent.tools.ask_user import _format_answers

        questions = [
            {
                "question": "How to authenticate?",
                "header": "Auth",
                "options": [{"label": "A", "description": "la"}] * 3,
            },
            {
                "question": "Where to store tokens?",
                "header": "Token",
                "options": [{"label": "B", "description": "lb"}] * 3,
            },
        ]
        out = _format_answers(questions, {"answers": ["OAuth", "Redis"]})
        assert "Q: How to authenticate?" in out
        assert "A: OAuth" in out
        assert "Q: Where to store tokens?" in out
        assert "A: Redis" in out

    def test_structured_format_answers_dismissed(self) -> None:
        """Empty answers produce the dismissal message."""
        from soothe.coreagent.tools.ask_user import _format_answers

        questions = [
            {
                "question": "Approve?",
                "header": "Auth",
                "options": [{"label": "A", "description": "la"}] * 3,
            }
        ]
        out = _format_answers(questions, None)
        assert "dismissed" in out.lower()

    def test_plain_string_questions_still_work_in_format_answers(self) -> None:
        """Degraded plain-string questions still render via str() fallback."""
        from soothe.coreagent.tools.ask_user import _format_answers

        out = _format_answers(["Which option?"], {"answers": ["Option C"]})
        assert "Q: Which option?" in out
        assert "A: Option C" in out
