"""Tests that step-completion LLM calls are skipped when a clarification pauses the step.

When a ``tool_approval`` or ``ask_user`` interrupt is captured mid-stream, the
step is **paused** (it resumes after the user answers). Three LLM calls that
are meant for *completed* steps must be skipped to avoid wasted cost on stale
input:

1. ``evaluate_step_deliverable`` — deliverable-gate LLM assess (in retry loop)
2. ``assess_step_close`` — structured close report for action steps
3. ``_summarize_step_completion_report`` — cognition summary (parallel path)
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from soothe.sloop.clarification.capture import ClarificationQueue, ResumeTicket
from soothe.sloop.clarification.detector import ClarificationDetector
from soothe.sloop.clarification.origins import ORIGIN_TOOL_APPROVAL
from soothe.sloop.clarification.protocol import ClarificationRequest, LoopStateView
from soothe.sloop.engine.execute.executor import Executor
from soothe.sloop.engine.execute.step_wave_types import (
    StepCompletionReport,
    _ExecuteStepResult,
    _StreamCollectChunk,
)
from soothe.sloop.plans.wired_subagent_plan import _WIRED_SUBAGENT_EXPECTED_OUTPUT
from soothe.sloop.state.schemas import StepAction, StepExecutionRecord


def _view() -> LoopStateView:
    return LoopStateView(
        goal_id="g",
        goal_description="do work",
        user_request="do work",
        iteration=0,
        intent_classification=None,
        plan_summary=None,
        recent_step_outputs=(),
        workspace_summary=None,
        active_skills=(),
        active_mcp_servers=(),
    )


def _tool_approval_request() -> ClarificationRequest:
    """A minimal tool_approval clarification request."""
    return ClarificationRequest(
        questions=("Approve run_command: rm -rf /tmp/build?",),
        origin_node=ORIGIN_TOOL_APPROVAL,
        origin_interrupt_id="iTA-1",
        loop_state=_view(),
    )


async def _empty_async_gen(*_args: Any, **_kwargs: Any) -> AsyncIterator[Any]:
    if False:  # pragma: no cover
        yield


def _make_mock_agent() -> MagicMock:
    """Mock CoreAgent that produces empty streams (real stream is not needed)."""
    agent = MagicMock()
    agent.execution_astream = MagicMock(side_effect=lambda *a, **k: _empty_async_gen())
    agent.execution_aget_state = AsyncMock(return_value=MagicMock())
    agent.aget_state = AsyncMock(return_value=MagicMock())
    agent.can_read_graph_state = False
    return agent


def _make_executor(capture: ClarificationQueue | None = None) -> Executor:
    # Mock context_engine so _record_ledger_message doesn't raise. The CE
    # ledger.record_message is a no-op MagicMock; tests here don't need real
    # ledger state.
    ce = MagicMock()
    ce.ledger = MagicMock()
    kwargs: dict[str, Any] = {"context_engine": ce}
    if capture is not None:
        kwargs.update(
            clarification_detector=ClarificationDetector(),
            clarification_capture=capture,
            clarification_loop_state_view=_view(),
        )
    return Executor(_make_mock_agent(), **kwargs)


class TestClarificationPauseSkipsCompletionLLMCalls:
    """When a clarification is captured, step-completion LLM calls are skipped."""

    @pytest.mark.asyncio
    async def test_deliverable_assess_skipped_when_clarification_captured(self) -> None:
        """evaluate_step_deliverable is not called when the step is paused."""
        capture = ClarificationQueue()
        executor = _make_executor(capture)

        async def fake_stream_and_collect(
            _stream: Any, **_kwargs: Any
        ) -> AsyncIterator[_StreamCollectChunk]:
            # Simulate the stream capturing a tool_approval interrupt: the
            # capture is enqueued before the finalized chunk is yielded.
            capture.enqueue(
                _tool_approval_request(),
                resume_ticket=ResumeTicket(thread_id="thread-1"),
                step_id="step-paused",
            )
            yield _StreamCollectChunk.finalized(
                output="",
                main_tool_count=0,
                messages=[AIMessage(content="")],
                delegate_final="",
                outcomes=[],
                has_error=False,
                subgraph_tool_count=0,
            )

        step = StepAction(
            id="step-paused",
            description="run a command",
            expected_output=_WIRED_SUBAGENT_EXPECTED_OUTPUT,
            requires_tool_use=True,
            kind="action",
        )

        with (
            patch.object(executor, "_stream_and_collect", side_effect=fake_stream_and_collect),
            patch(
                "soothe.sloop.engine.execute.executor.evaluate_step_deliverable",
                new=AsyncMock(),
            ) as mock_deliverable,
        ):
            result = await executor._execute_step_collecting_events(step, "thread-1")

        # Deliverable gate LLM call was skipped
        mock_deliverable.assert_not_called()
        # Step is marked as paused
        assert result.paused_by_clarification is True
        # Step is not failed (captured clarification → success=True)
        assert result.step_result is not None
        assert result.step_result.success is True

    @pytest.mark.asyncio
    async def test_assess_step_close_skipped_when_clarification_captured(self) -> None:
        """assess_step_close is not called when the step is paused."""
        capture = ClarificationQueue()
        executor = _make_executor(capture)

        async def fake_stream_and_collect(
            _stream: Any, **_kwargs: Any
        ) -> AsyncIterator[_StreamCollectChunk]:
            capture.enqueue(
                _tool_approval_request(),
                resume_ticket=ResumeTicket(thread_id="thread-1"),
                step_id="step-paused",
            )
            yield _StreamCollectChunk.finalized(
                output="",
                main_tool_count=0,
                messages=[AIMessage(content="")],
                delegate_final="",
                outcomes=[],
                has_error=False,
                subgraph_tool_count=0,
            )

        step = StepAction(
            id="step-paused",
            description="run a command",
            expected_output=_WIRED_SUBAGENT_EXPECTED_OUTPUT,
            requires_tool_use=True,
            kind="action",
        )

        with (
            patch.object(executor, "_stream_and_collect", side_effect=fake_stream_and_collect),
            patch(
                "soothe.sloop.eval.step_close_report.assess_step_close",
                new=AsyncMock(),
            ) as mock_close,
        ):
            result = await executor._execute_step_collecting_events(step, "thread-1")

        mock_close.assert_not_called()
        assert result.paused_by_clarification is True
        # No step_close_report in outcome
        assert result.step_result is not None
        assert "step_close_report" not in result.step_result.outcome

    @pytest.mark.asyncio
    async def test_retry_loop_breaks_early_when_clarification_captured(self) -> None:
        """The retry loop breaks immediately on clarification capture — no second pass."""
        capture = ClarificationQueue()
        executor = _make_executor(capture)

        call_count = 0

        async def fake_stream_and_collect(
            _stream: Any, **_kwargs: Any
        ) -> AsyncIterator[_StreamCollectChunk]:
            nonlocal call_count
            call_count += 1
            # First pass captures the interrupt; if the retry loop doesn't
            # break, a second pass would be needed (and call_count would hit 2).
            capture.enqueue(
                _tool_approval_request(),
                resume_ticket=ResumeTicket(thread_id="thread-1"),
                step_id="step-paused",
            )
            yield _StreamCollectChunk.finalized(
                output="",
                main_tool_count=0,
                messages=[AIMessage(content="")],
                delegate_final="",
                outcomes=[],
                has_error=False,
                subgraph_tool_count=0,
            )

        step = StepAction(
            id="step-paused",
            description="run a command",
            expected_output=_WIRED_SUBAGENT_EXPECTED_OUTPUT,
            requires_tool_use=True,
            kind="action",
        )

        with patch.object(executor, "_stream_and_collect", side_effect=fake_stream_and_collect):
            result = await executor._execute_step_collecting_events(step, "thread-1")

        # Only one stream pass — the early break prevented a retry
        assert call_count == 1
        assert result.paused_by_clarification is True

    @pytest.mark.asyncio
    async def test_completion_report_task_skipped_when_paused(self) -> None:
        """_summarize_step_completion_report is not scheduled when paused.

        Tests the _execute_parallel path: when _execute_step_collecting_events
        returns a result with paused_by_clarification=True, the completion-report
        LLM task must not be created.
        """
        executor = _make_executor()

        # Build a paused result to inject
        paused_result = _ExecuteStepResult(
            events=[],
            step_result=StepExecutionRecord(
                step_id="step-paused",
                success=True,
                duration_ms=100,
                thread_id="thread-1",
            ),
            messages=[],
            paused_by_clarification=True,
        )

        # Mock _execute_step_collecting_events to return the paused result
        async def fake_collect(*_args: Any, **_kwargs: Any) -> _ExecuteStepResult:
            return paused_result

        with (
            patch.object(executor, "_execute_step_collecting_events", side_effect=fake_collect),
            patch.object(
                executor, "_summarize_step_completion_report", new=AsyncMock()
            ) as mock_summary,
        ):
            from soothe.sloop.state.schemas import LoopState

            state = LoopState(thread_id="thread-1", goal="do work")
            state.current_decision = None  # skip thread selection

            results = []
            async for item in executor._execute_parallel(
                [StepAction(id="step-paused", description="run a command")], state
            ):
                results.append(item)

        # Completion-report LLM call was never scheduled
        mock_summary.assert_not_called()
        # No StepCompletionReport yielded
        assert not any(isinstance(r, StepCompletionReport) for r in results)
        # No StepExecutionRecord yielded — the step is paused, not complete.
        # Yielding it would fire step_completed in node_execute, causing the
        # TUI to mark the card as done and remove it before the resume
        # re-attaches.
        assert not any(isinstance(r, StepExecutionRecord) for r in results)

    @pytest.mark.asyncio
    async def test_completion_report_task_runs_when_not_paused(self) -> None:
        """Non-paused steps still schedule the completion-report LLM call."""
        executor = _make_executor()

        normal_result = _ExecuteStepResult(
            events=[],
            step_result=StepExecutionRecord(
                step_id="step-ok",
                success=True,
                duration_ms=100,
                thread_id="thread-1",
            ),
            messages=[AIMessage(content="Done.")],
            paused_by_clarification=False,
        )

        async def fake_collect(*_args: Any, **_kwargs: Any) -> _ExecuteStepResult:
            return normal_result

        with (
            patch.object(executor, "_execute_step_collecting_events", side_effect=fake_collect),
            patch.object(
                executor,
                "_summarize_step_completion_report",
                new=AsyncMock(return_value="I did it."),
            ) as mock_summary,
        ):
            from soothe.sloop.state.schemas import LoopState

            state = LoopState(thread_id="thread-1", goal="do work")
            state.current_decision = None

            results = []
            async for item in executor._execute_parallel(
                [StepAction(id="step-ok", description="run a command")], state
            ):
                results.append(item)

        mock_summary.assert_called_once()
        assert any(isinstance(r, StepCompletionReport) for r in results)
