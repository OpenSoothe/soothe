"""Tests for the tool-approval ↔ clarification bridge.

Covers: force_manual_origins includes tool_approval, veritas prompt variant
dispatch, _answer_to_decision mapping, and the resume-payload translator in
node_execute that converts a relay answer into the HITL decisions shape.
"""

from __future__ import annotations

import pytest

from soothe.sloop.clarification.origins import (
    DEFAULT_FORCE_MANUAL_ORIGINS,
    ORIGIN_TOOL_APPROVAL,
)
from soothe.sloop.engine.execute.graph_interrupt import build_tool_approval_resume_payload
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
# _answer_to_decision mapping
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
    from soothe.sloop.stations.execute.execute import _answer_to_decision

    assert _answer_to_decision(answer) == expected


# ---------------------------------------------------------------------------
# Resume-payload translator (end-to-end shape)
# ---------------------------------------------------------------------------


def test_tool_approval_resume_payload_from_approve_answer() -> None:
    """A relay 'approve' answer produces the HITL decisions shape."""
    from soothe.sloop.stations.execute.execute import _answer_to_decision

    decision_type = _answer_to_decision("approve")
    payload = build_tool_approval_resume_payload("iTA", decisions=[{"type": decision_type}])
    assert payload == {"iTA": {"decisions": [{"type": "approve"}]}}


def test_tool_approval_resume_payload_from_reject_answer() -> None:
    from soothe.sloop.stations.execute.execute import _answer_to_decision

    decision_type = _answer_to_decision("no")
    payload = build_tool_approval_resume_payload("iTA", decisions=[{"type": decision_type}])
    assert payload == {"iTA": {"decisions": [{"type": "reject"}]}}


def test_tool_approval_resume_payload_from_edit_answer() -> None:
    from soothe.sloop.stations.execute.execute import _answer_to_decision

    decision_type = _answer_to_decision("edit")
    payload = build_tool_approval_resume_payload("iTA", decisions=[{"type": decision_type}])
    assert payload == {"iTA": {"decisions": [{"type": "edit"}]}}


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
