"""Plan-review clarification widget (planner_subagent_review)."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from soothe_cli.tui.binding import message_from_widget
from soothe_cli.tui.widgets.messages.clarification import (
    ClarificationInputMessage,
    _strip_plan_frontmatter,
)


def test_strip_plan_frontmatter_removes_yaml() -> None:
    raw = "---\nstatus: draft\n---\n\n# Plan\n\nDo the thing.\n"
    assert _strip_plan_frontmatter(raw) == "# Plan\n\nDo the thing."


def test_strip_plan_frontmatter_passthrough() -> None:
    assert _strip_plan_frontmatter("# Already clean") == "# Already clean"


def test_clarification_wire_content_plan_review() -> None:
    from soothe_cli.tui.app._execution import clarification_wire_content

    assert clarification_wire_content(["Reject", ""]) == "Plan review: Reject"
    assert clarification_wire_content(["Approve", ""]) == "Plan review: Approve"
    assert (
        clarification_wire_content(["More comments", "narrow scope"])
        == "Plan review: More comments — narrow scope"
    )
    assert clarification_wire_content(["auth flows"]) == "auth flows"
    assert clarification_wire_content(["a", "b"]) == "A1: a | A2: b"


def test_path_footer_text() -> None:
    with_path = ClarificationInputMessage(
        step_id="s1",
        questions=["Action?", "Comments?"],
        origin_node="planner_subagent_review",
        plan_path="/tmp/plans/x.md",
        plan_markdown="# Plan",
    )
    assert with_path._path_footer_text() == "Plan saved to: /tmp/plans/x.md"
    memory = ClarificationInputMessage(
        step_id="s1",
        questions=["Action?", "Comments?"],
        origin_node="planner_subagent_review",
    )
    assert memory._path_footer_text() == "Plan held in memory only"


def test_widget_to_message_serializes_plan_review() -> None:
    from soothe_sdk.display.transcript_types import MessageType

    widget = ClarificationInputMessage(
        step_id="s1",
        questions=["Action?", "Comments?"],
        origin_node="planner_subagent_review",
        plan_path="/tmp/x.md",
        plan_markdown="# Plan",
        id="clarify-test",
    )
    data = message_from_widget(widget)
    assert data.type == MessageType.APP
    assert "Plan review" in data.content
    assert "awaiting" in data.content.lower()


class _PlanReviewHarnessApp(App[None]):
    def __init__(self, **kwargs) -> None:  # noqa: ANN003
        super().__init__()
        self._kwargs = kwargs
        self.submitted: list[ClarificationInputMessage.Submitted] = []

    def compose(self) -> ComposeResult:
        yield ClarificationInputMessage(**self._kwargs)

    def on_clarification_input_message_submitted(
        self, event: ClarificationInputMessage.Submitted
    ) -> None:
        self.submitted.append(event)


@pytest.mark.asyncio
async def test_plan_review_approve_submits_immediately() -> None:
    app = _PlanReviewHarnessApp(
        step_id="planner_subagent_review",
        questions=[
            "Action for this plan: Approve, Reject, or More comments",
            "Revision comments (when choosing More comments)",
        ],
        origin_node="planner_subagent_review",
        plan_path="/ws/.soothe/plans/demo.md",
        plan_markdown="---\nstatus: draft\n---\n\n# Optimize deps\n\nStep 1.\n",
        id="clarify-approve",
    )
    async with app.run_test() as pilot:
        widget = app.query_one(ClarificationInputMessage)
        assert widget._path_footer_text() == "Plan saved to: /ws/.soothe/plans/demo.md"
        comments = widget.query_one("#plan-review-comments-input")
        assert comments.has_class("hidden")
        await pilot.click("#plan-review-btn-approve")
        assert len(app.submitted) == 1
        assert app.submitted[0].answers == ["Approve", ""]


@pytest.mark.asyncio
async def test_plan_review_arrow_keys_cycle_actions() -> None:
    app = _PlanReviewHarnessApp(
        step_id="planner_subagent_review",
        questions=[
            "Action for this plan: Approve, Reject, or More comments",
            "Revision comments (when choosing More comments)",
        ],
        origin_node="planner_subagent_review",
        plan_path="/ws/.soothe/plans/demo.md",
        plan_markdown="# Plan\n\nBody.\n",
        id="clarify-arrows",
    )
    async with app.run_test() as pilot:
        widget = app.query_one(ClarificationInputMessage)
        assert widget._plan_path.endswith("demo.md")
        assert widget._plan_markdown.startswith("# Plan")
        assert widget._selected_action == "approve"
        await pilot.press("right")
        assert widget._selected_action == "reject"
        await pilot.press("right")
        assert widget._selected_action == "comments"
        comments = widget.query_one("#plan-review-comments-input")
        assert not comments.has_class("hidden")
        await pilot.press("left")
        assert widget._selected_action == "reject"
        assert comments.has_class("hidden")
        await pilot.press("enter")
        assert len(app.submitted) == 1
        assert app.submitted[0].answers == ["Reject", ""]


@pytest.mark.asyncio
async def test_plan_review_comments_requires_text() -> None:
    app = _PlanReviewHarnessApp(
        step_id="planner_subagent_review",
        questions=[
            "Action for this plan: Approve, Reject, or More comments",
            "Revision comments (when choosing More comments)",
        ],
        origin_node="planner_subagent_review",
        plan_path="/ws/.soothe/plans/demo.md",
        plan_markdown="# Plan\n",
        id="clarify-comments",
    )
    async with app.run_test() as pilot:
        widget = app.query_one(ClarificationInputMessage)
        await pilot.click("#plan-review-btn-comments")
        comments = widget.query_one("#plan-review-comments-input")
        assert not comments.has_class("hidden")
        assert app.submitted == []
        await pilot.press("enter")
        assert app.submitted == []
        comments.value = "tighten scope"
        comments.focus()
        await pilot.press("enter")
        assert len(app.submitted) == 1
        assert app.submitted[0].answers == ["More comments", "tighten scope"]
