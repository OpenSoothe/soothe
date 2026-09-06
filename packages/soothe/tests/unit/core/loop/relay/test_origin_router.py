"""Unit tests for the origin router — resume payload building."""

from __future__ import annotations

import pytest

from soothe.sloop.clarification.origins import (
    ORIGIN_EXECUTE,
    ORIGIN_PLAN_MODE_REVIEW,
    ORIGIN_RAIL_PAUSE,
    ORIGIN_TOOL_APPROVAL,
)
from soothe.sloop.clarification.protocol import (
    ClarificationRequest,
    LoopStateView,
)
from soothe.sloop.relay.errors import InvalidAnswerSchemaError
from soothe.sloop.relay.origin_router import (
    ToolApprovalDecision,
    build_core_agent_resume,
    resume_station_for_origin,
)
from soothe.sloop.relay.store import ClarificationRow


def _view() -> LoopStateView:
    return LoopStateView(
        goal_id="g1",
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


def _request(origin: str, iid: str = "iid-1") -> ClarificationRequest:
    return ClarificationRequest(
        questions=("q?",),
        origin_node=origin,  # type: ignore[arg-type]
        origin_interrupt_id=iid,
        loop_state=_view(),
    )


def _row(
    origin: str = ORIGIN_EXECUTE,
    iid: str = "iid-1",
    thread_id: str | None = "thread-1",
) -> ClarificationRow:
    return ClarificationRow.from_handle(
        relay_id="r1",
        loop_id="loop-1",
        goal_id="g1",
        handle_origin=origin,
        handle_interrupt_id=iid,
        request=_request(origin, iid),
        core_agent_thread_id=thread_id,
        step_id="step-1",
        step_description="step",
        policy_mode="manual",
        captured_at="2026-01-01T00:00:00+00:00",
    )


class TestToolApprovalDecision:
    def test_approve_synonyms(self) -> None:
        for token in ("approve", "allow", "accept", "proceed", "yes", "y"):
            d = ToolApprovalDecision.from_answer_string(token)
            assert d.type == "approve"
            assert d.message is None

    def test_reject_synonyms(self) -> None:
        for token in ("reject", "deny", "block", "cancel", "no", "n"):
            d = ToolApprovalDecision.from_answer_string(token)
            assert d.type == "reject"

    def test_edit_synonyms(self) -> None:
        for token in ("edit", "modify", "revise"):
            d = ToolApprovalDecision.from_answer_string(token)
            assert d.type == "edit"

    def test_instructive_reject_attaches_message(self) -> None:
        d = ToolApprovalDecision.from_answer_string(
            "reject", instructive_reason="dangerous command"
        )
        assert d.type == "reject"
        assert d.message == "dangerous command"

    def test_instructive_reason_only_on_reject(self) -> None:
        d = ToolApprovalDecision.from_answer_string(
            "approve", instructive_reason="shouldn't attach"
        )
        assert d.type == "approve"
        assert d.message is None

    def test_case_insensitive(self) -> None:
        d = ToolApprovalDecision.from_answer_string("APPROVE")
        assert d.type == "approve"

    def test_empty_raises(self) -> None:
        with pytest.raises(InvalidAnswerSchemaError, match="empty"):
            ToolApprovalDecision.from_answer_string("")

    def test_unrecognized_raises_fail_closed(self) -> None:
        with pytest.raises(InvalidAnswerSchemaError, match="unrecognized"):
            ToolApprovalDecision.from_answer_string("maybe")

    def test_json_structured_dict(self) -> None:
        d = ToolApprovalDecision.from_answer_string('{"decision": "reject"}')
        assert d.type == "reject"

    def test_to_dict(self) -> None:
        d = ToolApprovalDecision(type="reject", message="blocked")
        assert d.to_dict() == {"type": "reject", "message": "blocked"}

    def test_to_dict_no_message(self) -> None:
        d = ToolApprovalDecision(type="approve")
        assert d.to_dict() == {"type": "approve"}


class TestResumeStation:
    def test_execute_routes_to_execute(self) -> None:
        assert resume_station_for_origin(ORIGIN_EXECUTE) == "execute"

    def test_tool_approval_routes_to_execute(self) -> None:
        assert resume_station_for_origin(ORIGIN_TOOL_APPROVAL) == "execute"

    def test_plan_review_routes_to_plan_review(self) -> None:
        assert resume_station_for_origin(ORIGIN_PLAN_MODE_REVIEW) == "plan_review"

    def test_rail_pause_routes_to_end(self) -> None:
        assert resume_station_for_origin(ORIGIN_RAIL_PAUSE) == "END"


class TestBuildCoreAgentResume:
    def test_execute_origin_builds_answers_payload(self) -> None:
        row = _row(origin=ORIGIN_EXECUTE)
        spec = build_core_agent_resume(row, answers=("blue",))
        assert spec is not None
        assert spec.thread_id == "thread-1"
        assert spec.resume_payload == {"iid-1": {"answers": ["blue"]}}

    def test_tool_approval_builds_decisions_payload(self) -> None:
        request = _request(ORIGIN_TOOL_APPROVAL)
        # Build a request with action_requests metadata
        request_with_meta = ClarificationRequest(
            questions=request.questions,
            origin_node=ORIGIN_TOOL_APPROVAL,
            origin_interrupt_id="iid-1",
            loop_state=_view(),
            metadata={"action_requests": [{"name": "edit_file", "args": {"file_path": "/x"}}]},
        )
        row = ClarificationRow.from_handle(
            relay_id="r1",
            loop_id="loop-1",
            goal_id="g1",
            handle_origin=ORIGIN_TOOL_APPROVAL,
            handle_interrupt_id="iid-1",
            request=request_with_meta,
            core_agent_thread_id="thread-1",
            step_id="step-1",
            step_description="step",
            policy_mode="auto",
            captured_at="2026-01-01T00:00:00+00:00",
        )
        spec = build_core_agent_resume(row, answers=("approve",))
        assert spec is not None
        assert spec.thread_id == "thread-1"
        assert "iid-1" in spec.resume_payload
        assert "decisions" in spec.resume_payload["iid-1"]
        assert spec.resume_payload["iid-1"]["decisions"] == [{"type": "approve"}]

    def test_tool_approval_reject_with_instructive_reason(self) -> None:
        request_with_meta = ClarificationRequest(
            questions=("q?",),
            origin_node=ORIGIN_TOOL_APPROVAL,
            origin_interrupt_id="iid-1",
            loop_state=_view(),
            metadata={
                "action_requests": [{"name": "run_command", "args": {"command": "rm -rf /"}}]
            },
        )
        row = ClarificationRow.from_handle(
            relay_id="r1",
            loop_id="loop-1",
            goal_id="g1",
            handle_origin=ORIGIN_TOOL_APPROVAL,
            handle_interrupt_id="iid-1",
            request=request_with_meta,
            core_agent_thread_id="thread-1",
            step_id="step-1",
            step_description="step",
            policy_mode="auto",
            captured_at="2026-01-01T00:00:00+00:00",
        )
        spec = build_core_agent_resume(
            row,
            answers=("reject",),
            instructive_reason="dangerous command: rm -rf /",
        )
        assert spec is not None
        decisions = spec.resume_payload["iid-1"]["decisions"]
        assert decisions == [{"type": "reject", "message": "dangerous command: rm -rf /"}]

    def test_plan_mode_review_returns_none(self) -> None:
        row = _row(origin=ORIGIN_PLAN_MODE_REVIEW)
        spec = build_core_agent_resume(row, answers=("approve",))
        assert spec is None

    def test_rail_pause_returns_none(self) -> None:
        row = _row(origin=ORIGIN_RAIL_PAUSE, thread_id=None)
        spec = build_core_agent_resume(row, answers=("proceed",))
        assert spec is None

    def test_no_thread_returns_none(self) -> None:
        row = _row(origin=ORIGIN_EXECUTE, thread_id=None)
        spec = build_core_agent_resume(row, answers=("blue",))
        assert spec is None

    def test_tool_approval_unrecognized_raises(self) -> None:
        request_with_meta = ClarificationRequest(
            questions=("q?",),
            origin_node=ORIGIN_TOOL_APPROVAL,
            origin_interrupt_id="iid-1",
            loop_state=_view(),
            metadata={"action_requests": [{"name": "edit_file", "args": {}}]},
        )
        row = ClarificationRow.from_handle(
            relay_id="r1",
            loop_id="loop-1",
            goal_id="g1",
            handle_origin=ORIGIN_TOOL_APPROVAL,
            handle_interrupt_id="iid-1",
            request=request_with_meta,
            core_agent_thread_id="thread-1",
            step_id="step-1",
            step_description="step",
            policy_mode="auto",
            captured_at="2026-01-01T00:00:00+00:00",
        )
        with pytest.raises(InvalidAnswerSchemaError, match="unrecognized"):
            build_core_agent_resume(row, answers=("maybe",))
