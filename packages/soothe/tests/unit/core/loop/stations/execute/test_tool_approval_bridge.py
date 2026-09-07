"""Tests for the tool-approval ↔ clarification bridge.

Covers: force_manual_origins includes tool_approval, veritas prompt variant
dispatch, answer_to_decision mapping, and the resume-payload translator in
node_execute that converts a relay answer into the HITL decisions shape.
"""

from __future__ import annotations

import pytest

from soothe.config.models import DEFAULT_FORCE_MANUAL_ORIGINS
from soothe.sloop.clarification.origins import (
    ORIGIN_EXECUTE,
    ORIGIN_TOOL_APPROVAL,
)
from soothe.sloop.clarification.protocol import answer_from_state, request_from_state
from soothe.sloop.relay.outbox import (
    build_clarification_resume_payload,
    build_tool_approval_resume_payload,
)
from soothe.subagents.veritas.prompts import build_veritas_system_prompt_for_origin

# ---------------------------------------------------------------------------
# force_manual_origins bridge
# ---------------------------------------------------------------------------


def test_tool_approval_not_in_default_force_manual_origins() -> None:
    """tool_approval is auto-evaluated by veritas in auto mode by default.

    Removing it from the default ``force_manual_origins`` lets safe tool actions
    auto-approve via the veritas security-approver prompt instead of always
    requiring a human. ``plan_mode_review`` stays a human call.
    """
    assert ORIGIN_TOOL_APPROVAL not in DEFAULT_FORCE_MANUAL_ORIGINS
    assert "plan_mode_review" in DEFAULT_FORCE_MANUAL_ORIGINS


# ---------------------------------------------------------------------------
# Veritas prompt variant
# ---------------------------------------------------------------------------


def test_veritas_prompt_for_tool_approval_origin() -> None:
    prompt = build_veritas_system_prompt_for_origin("tool_approval")
    assert "tool-action approval" in prompt.lower()
    assert "approve" in prompt.lower()
    assert "reject" in prompt.lower()


def test_veritas_prompt_for_other_origins_unchanged() -> None:
    prompt = build_veritas_system_prompt_for_origin("execute")
    assert "answerer subagent" in prompt.lower()
    assert "tool-action" not in prompt.lower()


def test_veritas_prompt_for_none_origin_is_default() -> None:
    assert build_veritas_system_prompt_for_origin(None) == build_veritas_system_prompt_for_origin(
        "execute"
    )


# ---------------------------------------------------------------------------
# answer_to_decision mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "answer,expected",
    [
        ("approve", "approve"),
        ("yes", "approve"),
        ("ok", "approve"),
        ("Allow", "approve"),
        ("proceed", "approve"),
        ("reject", "reject"),
        ("no", "reject"),
        ("deny", "reject"),
        ("cancel", "reject"),
        ("edit", "edit"),
        ("modify", "edit"),
        ("change", "edit"),
        ("", "approve"),  # default safe
        ("unknown token", "approve"),  # default safe
    ],
)
def test_answer_to_decision_mapping(answer: str, expected: str) -> None:
    from soothe.sloop.relay.outbox import answer_to_decision

    assert answer_to_decision(answer) == expected


# ---------------------------------------------------------------------------
# Resume-payload translator (end-to-end shape)
# ---------------------------------------------------------------------------


def test_tool_approval_resume_payload_from_approve_answer() -> None:
    """A relay 'approve' answer produces the HITL decisions shape."""
    from soothe.sloop.relay.outbox import answer_to_decision

    decision_type = answer_to_decision("approve")
    payload = build_tool_approval_resume_payload("iTA", decisions=[{"type": decision_type}])
    assert payload == {"iTA": {"decisions": [{"type": "approve"}]}}


def test_tool_approval_resume_payload_from_reject_answer() -> None:
    from soothe.sloop.relay.outbox import answer_to_decision

    decision_type = answer_to_decision("no")
    payload = build_tool_approval_resume_payload("iTA", decisions=[{"type": decision_type}])
    assert payload == {"iTA": {"decisions": [{"type": "reject"}]}}


def test_tool_approval_resume_payload_from_edit_answer() -> None:
    from soothe.sloop.relay.outbox import answer_to_decision

    decision_type = answer_to_decision("edit")
    payload = build_tool_approval_resume_payload("iTA", decisions=[{"type": decision_type}])
    assert payload == {"iTA": {"decisions": [{"type": "edit"}]}}


def _bridge_request(origin_node: str) -> object:
    return request_from_state(
        {
            "questions": ["q"],
            "origin_node": origin_node,
            "origin_interrupt_id": "i1",
            "loop_state": {
                "goal_id": "g",
                "goal_description": "",
                "user_request": "",
                "iteration": 0,
                "intent_classification": None,
                "plan_summary": None,
                "recent_step_outputs": [],
                "workspace_summary": None,
                "active_skills": [],
                "active_mcp_servers": [],
            },
        }
    )


def _bridge_answer(answers: tuple[str, ...]) -> object:
    return answer_from_state(
        {
            "answers": list(answers),
            "source": "human",
            "confidence": None,
            "defer": False,
            "audit": {},
        }
    )


def test_build_clarification_resume_payload_tool_approval() -> None:
    """Unified translator emits the HITL decisions shape for tool_approval."""
    req = _bridge_request(ORIGIN_TOOL_APPROVAL)
    ans = _bridge_answer(("approve",))
    payload = build_clarification_resume_payload(req, ans)  # type: ignore[arg-type]
    assert payload == {"i1": {"decisions": [{"type": "approve"}]}}


def test_build_clarification_resume_payload_tool_approval_multi_action() -> None:
    """Multi-action tool_approval produces one decision per pending tool call.

    Regression test for the bug where ``build_clarification_resume_payload``
    only emitted a single decision regardless of how many action requests
    (hanging tool calls) were pending. The ``HumanInTheLoopMiddleware``
    requires the decisions list length to match the number of hanging tool
    calls — a mismatch raises ``ValueError`` at resume time.
    """
    req = request_from_state(
        {
            "questions": ["q1", "q2"],
            "origin_node": ORIGIN_TOOL_APPROVAL,
            "origin_interrupt_id": "i2",
            "loop_state": {
                "goal_id": "g",
                "goal_description": "",
                "user_request": "",
                "iteration": 0,
                "intent_classification": None,
                "plan_summary": None,
                "recent_step_outputs": [],
                "workspace_summary": None,
                "active_skills": [],
                "active_mcp_servers": [],
            },
            "metadata": {
                "action_requests": [
                    {"name": "run_command", "args": {"command": "git log"}},
                    {"name": "run_command", "args": {"command": "git diff"}},
                ],
            },
        }
    )
    ans = _bridge_answer(("approve", "approve"))
    payload = build_clarification_resume_payload(req, ans)  # type: ignore[arg-type]
    assert payload == {"i2": {"decisions": [{"type": "approve"}, {"type": "approve"}]}}


def test_build_clarification_resume_payload_tool_approval_multi_answer_no_metadata() -> None:
    """When action_requests metadata is missing, fall back to answer count."""
    req = _bridge_request(ORIGIN_TOOL_APPROVAL)
    ans = _bridge_answer(("approve", "reject"))
    payload = build_clarification_resume_payload(req, ans)  # type: ignore[arg-type]
    assert payload == {"i1": {"decisions": [{"type": "approve"}, {"type": "reject"}]}}


def test_build_clarification_resume_payload_ask_user() -> None:
    """Unified translator delivers answers verbatim for ask_user (execute)."""
    req = _bridge_request(ORIGIN_EXECUTE)
    ans = _bridge_answer(("run the tests",))
    payload = build_clarification_resume_payload(req, ans)  # type: ignore[arg-type]
    assert payload == {"i1": {"answers": ["run the tests"]}}


def test_build_clarification_resume_payload_instructive_reject() -> None:
    """Instructive reject attaches the safety reason as ``message`` on the
    reject decision so the model's ToolMessage explains why the call was blocked."""
    req = _bridge_request(ORIGIN_TOOL_APPROVAL)
    ans = answer_from_state(
        {
            "answers": ["reject"],
            "source": "static",
            "confidence": 1.0,
            "defer": False,
            "audit": {
                "stage": "safety_check",
                "reason": "Command blocked by security rule: rm\\s+-rf\\b",
                "rule_id": "command.dangerous.rm_rf",
                "instructive": True,
            },
        }
    )
    payload = build_clarification_resume_payload(req, ans)  # type: ignore[arg-type]
    decisions = payload["i1"]["decisions"]
    assert len(decisions) == 1
    assert decisions[0]["type"] == "reject"
    assert decisions[0]["message"] == "Command blocked by security rule: rm\\s+-rf\\b"


def test_build_clarification_resume_payload_non_instructive_reject_no_message() -> None:
    """A plain human reject (no instructive audit) has no ``message`` field."""
    req = _bridge_request(ORIGIN_TOOL_APPROVAL)
    ans = _bridge_answer(("reject",))  # default audit={}
    payload = build_clarification_resume_payload(req, ans)  # type: ignore[arg-type]
    decisions = payload["i1"]["decisions"]
    assert len(decisions) == 1
    assert decisions[0]["type"] == "reject"
    assert "message" not in decisions[0]


# ---------------------------------------------------------------------------
# AutoClarificationPolicy routing: tool_approval is veritas-evaluated by default
# ---------------------------------------------------------------------------


def test_auto_policy_evaluates_tool_approval_via_veritas_by_default() -> None:
    """By default tool_approval is NOT force-manual, so veritas evaluates it."""
    from soothe.sloop.clarification.auto import AutoClarificationPolicy

    sentinel = object()

    def _veritas(req: object) -> object:
        return sentinel

    policy = AutoClarificationPolicy(
        veritas_answer=_veritas,
        force_manual_origins=DEFAULT_FORCE_MANUAL_ORIGINS,
    )
    assert not policy.requires_manual(ORIGIN_TOOL_APPROVAL)
    assert policy.requires_manual("plan_mode_review")
    assert not policy.requires_manual("execute")
