"""Unit tests for approved-plan → DISPATCH / execute grounding (RFC-904)."""

from __future__ import annotations

from soothe.sloop.plans.grounding import (
    approved_plan_section_body,
    compose_root_full_description,
    consume_approved_plan_from_state,
    peek_approved_plan_from_state,
    root_already_grounded,
)
from soothe.sloop.prompts.user_message import UserMessageBuilder


def test_compose_root_full_description_embeds_plan() -> None:
    text = compose_root_full_description(
        "migrate auth",
        approved_plan_markdown="# Solution\n\nUse OAuth.\n",
        approved_plan_path="/ws/.soothe/plans/demo.md",
    )
    assert text.startswith("migrate auth")
    assert root_already_grounded(text)
    assert "path: /ws/.soothe/plans/demo.md" in text
    assert "decompose_task" in text
    assert "Use OAuth" in text


def test_consume_approved_plan_is_one_shot() -> None:
    state = type("S", (), {})()
    state.approved_plan_markdown = "# Solution\n\nUse OAuth.\n"
    state.approved_plan_path = "/ws/p.md"
    body, path = consume_approved_plan_from_state(state)
    assert body == "# Solution\n\nUse OAuth."
    assert path == "/ws/p.md"
    assert state.approved_plan_markdown is None
    assert state.approved_plan_path is None
    assert peek_approved_plan_from_state(state) == (None, None)


def test_execute_step_message_includes_approved_plan_section() -> None:
    msg = UserMessageBuilder().build_execute_step_message(
        "Implement the approved plan",
        step_id="AAA-01",
        approved_plan_path="/ws/.soothe/plans/demo.md",
        approved_plan_markdown="# Solution\n\nUse OAuth.\n",
    )
    assert "APPROVED PLAN" in msg
    assert "path: /ws/.soothe/plans/demo.md" in msg
    assert "Use OAuth" in msg
    assert "decompose_task" in msg
    assert "DECOMPOSITION vs TODOS" in msg
    assert "When APPROVED PLAN is present" in msg


def test_approved_plan_section_body_empty_without_markdown() -> None:
    assert approved_plan_section_body(approved_plan_markdown="") == ""
