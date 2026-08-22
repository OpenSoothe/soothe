"""Unit tests for approved-plan → DISPATCH / execute grounding (RFC-904)."""

from __future__ import annotations

from soothe.prompts.user_message import UserMessageBuilder
from soothe.sloop.plans.grounding import (
    approved_plan_section_body,
    compose_root_full_description,
    consume_approved_plan_from_state,
    peek_approved_plan_from_state,
    root_already_grounded,
)


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
    assert "DECOMPOSITION vs TODOS" not in msg
    assert "FINISH HERE" not in msg


def test_approved_plan_section_body_empty_without_markdown() -> None:
    assert approved_plan_section_body(approved_plan_markdown="") == ""


def test_peek_approved_plan_reloads_body_from_path(tmp_path) -> None:
    """When the body is absent but a path is set, reload from disk (Bug #3)."""
    plan_file = tmp_path / "plan.md"
    plan_file.write_text(
        "---\nstatus: approved\n---\n\n# Plan\n\nDo the thing.\n", encoding="utf-8"
    )
    state = type("S", (), {})()
    state.approved_plan_markdown = None
    state.approved_plan_path = str(plan_file)
    body, path = peek_approved_plan_from_state(state)
    assert path == str(plan_file)
    assert body is not None
    assert "Do the thing." in body
    # Frontmatter stripped so the grounding envelope stays clean.
    assert "status: approved" not in body


def test_peek_approved_plan_returns_none_when_path_missing() -> None:
    """No body and an unreadable path → (None, path)."""
    state = type("S", (), {})()
    state.approved_plan_markdown = None
    state.approved_plan_path = "/nonexistent/plan.md"
    body, path = peek_approved_plan_from_state(state)
    assert body is None
    assert path == "/nonexistent/plan.md"
