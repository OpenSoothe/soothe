"""Tool-approval relay tests: action_requests interrupts surface to the user.

When ``tool_approval_enabled`` is True, deepagents ``HumanInTheLoopMiddleware``
interrupts (``{"action_requests": [...]}``) are captured into the clarification
relay instead of being auto-approved. When False (default), the historical
auto-approve behavior is preserved.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from langgraph.types import Interrupt

from soothe.sloop.clarification.capture import ClarificationQueue
from soothe.sloop.clarification.detector import ClarificationDetector
from soothe.sloop.clarification.origins import ORIGIN_TOOL_APPROVAL
from soothe.sloop.clarification.protocol import LoopStateView
from soothe.sloop.engine.execute.executor import Executor
from soothe.sloop.engine.execute.graph_interrupt import (
    build_auto_resume_payload,
    build_tool_approval_resume_payload,
    is_tool_approval_interrupt,
)


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


def _tool_approval_interrupt(
    tool: str = "edit_file",
    *,
    interrupt_id: str = "iTA",
    args: dict[str, Any] | None = None,
) -> Interrupt:
    return Interrupt(
        value={"action_requests": [{"name": tool, "args": args or {"file_path": "/tmp/x.py"}}]},
        id=interrupt_id,
    )


def _make_executor(core: _StubCoreAgent, **overrides: Any) -> Executor:
    return Executor(core, **overrides)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# is_tool_approval_interrupt
# ---------------------------------------------------------------------------


def test_is_tool_approval_interrupt_recognizes_action_requests() -> None:
    assert is_tool_approval_interrupt({"action_requests": [{"name": "edit_file"}]})
    assert not is_tool_approval_interrupt({"type": "ask_user", "questions": ["q"]})
    assert not is_tool_approval_interrupt({"foo": "bar"})
    assert not is_tool_approval_interrupt("not a mapping")


# ---------------------------------------------------------------------------
# build_auto_resume_payload skips tool_approval interrupts
# ---------------------------------------------------------------------------


def test_build_auto_resume_skips_tool_approval_interrupts() -> None:
    """action_requests interrupts must NOT be auto-approved when surfaced.

    The auto-resume path only handles non-ask_user, non-action_requests
    interrupts. Tool-approval interrupts are handled by the clarification
    relay (or auto-approved only when mode="off" and they land here
    uncaptured)."""
    payload = build_auto_resume_payload(
        {
            "i1": {"action_requests": [{"name": "edit_file"}]},
            "i2": {"some_other": "interrupt"},
        }
    )
    # i1 (action_requests) is skipped; i2 is auto-approved
    assert "i1" not in payload
    assert "i2" in payload


def test_build_tool_approval_resume_payload_shape() -> None:
    """The resume payload must match the middleware's expected decisions shape."""
    resume = build_tool_approval_resume_payload(
        "iTA",
        decisions=[{"type": "approve"}],
    )
    assert resume == {"iTA": {"decisions": [{"type": "approve"}]}}


# ---------------------------------------------------------------------------
# Detector: from_tool_approval_interrupt
# ---------------------------------------------------------------------------


def test_detector_captures_tool_approval_interrupt() -> None:
    detector = ClarificationDetector()
    req = detector.from_tool_approval_interrupt(
        {"action_requests": [{"name": "edit_file", "args": {"file_path": "/a.py"}}]},
        interrupt_id="iTA",
        loop_state=_view(),
    )
    assert req is not None
    assert req.origin_node == ORIGIN_TOOL_APPROVAL
    assert req.origin_interrupt_id == "iTA"
    assert len(req.questions) == 1
    q = req.questions[0]
    assert isinstance(q, dict)
    assert "edit_file" in q["header"]
    assert "/a.py" in q["header"]
    assert "approve" in q["header"].lower()
    assert len(q["options"]) == 3
    labels = [opt["label"] for opt in q["options"]]
    assert "Approve" in labels
    assert "Edit" in labels
    assert "Reject" in labels


def test_detector_rejects_non_action_requests() -> None:
    detector = ClarificationDetector()
    assert (
        detector.from_tool_approval_interrupt(
            {"type": "ask_user"}, interrupt_id="i", loop_state=_view()
        )
        is None
    )
    assert (
        detector.from_tool_approval_interrupt("not a mapping", interrupt_id="i", loop_state=_view())
        is None
    )
    assert (
        detector.from_tool_approval_interrupt(
            {"action_requests": []}, interrupt_id="i", loop_state=_view()
        )
        is None
    )


def test_detector_formats_run_command_with_command_arg() -> None:
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


def test_detector_truncates_long_command_arg() -> None:
    """Long command args are truncated with ellipsis for readability."""
    detector = ClarificationDetector()
    long_cmd = "python3 -c 'import sys; print(" + "x" * 200 + ")'"
    req = detector.from_tool_approval_interrupt(
        {"action_requests": [{"name": "run_command", "args": {"command": long_cmd}}]},
        interrupt_id="i",
        loop_state=_view(),
    )
    assert req is not None
    q = req.questions[0]
    assert isinstance(q, dict)
    header = q["header"]
    assert "run_command" in header
    assert "command=" in header
    # Truncated — the full command should NOT be in the header
    assert long_cmd not in header
    assert "…" in header
    # The truncated preview should be present
    assert long_cmd[:50] in header


# ---------------------------------------------------------------------------
# Executor: tool_approval_enabled captures; disabled auto-approves
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_approval_captured_when_relay_active() -> None:
    """action_requests is captured into the relay (always-on; never auto-resumed)."""
    core = _StubCoreAgent()
    core.queue([], state_interrupts=(_tool_approval_interrupt(),))
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
        origin_node="execute",
    )
    _ = [c async for c in stream]

    assert capture.head is not None
    assert capture.head.origin_node == ORIGIN_TOOL_APPROVAL
    # Stream returned early (captured), no second call (no auto-resume)
    assert len(core.calls) == 1
