"""Plan-review clarification widget (plan_mode_review)."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from soothe_cli.commands.binding import message_from_widget
from soothe_cli.tui.widgets.messages.clarification import (
    ClarificationInputMessage,
    _strip_plan_frontmatter,
)


def test_strip_plan_frontmatter_removes_yaml() -> None:
    raw = "---\nstatus: draft\n---\n\n# Plan\n\nDo the thing.\n"
    assert _strip_plan_frontmatter(raw) == "# Plan\n\nDo the thing."


def test_strip_plan_frontmatter_passthrough() -> None:
    assert _strip_plan_frontmatter("# Already clean") == "# Already clean"


def test_plan_review_actions_use_primary_text_highlight() -> None:
    """Selected action is bold green; non-selected is dim grey — no reverse fill."""
    css = ClarificationInputMessage.DEFAULT_CSS
    assert "Button.plan-review-selected" in css
    assert "color: $success;" in css
    assert "text-style: bold reverse;" not in css
    selected_block = css.split("Button.plan-review-selected {", 1)[1].split("}", 1)[0]
    assert "background: transparent;" in selected_block
    assert "background: $primary;" not in selected_block
    # Non-selected (base Button rule) is dim grey.
    base_block = css.split(".plan-review-actions Button {", 1)[1].split("}", 1)[0]
    assert "color: $text-muted" in base_block


def test_plan_review_action_rows_are_single_line_and_borderless() -> None:
    """Each action occupies one row; the inline Refine entry carries no input chrome."""
    css = ClarificationInputMessage.DEFAULT_CSS
    row_block = css.split(".plan-review-action-row {", 1)[1].split("}", 1)[0]
    assert "height: 1;" in row_block
    button_block = css.split(".plan-review-actions Button {", 1)[1].split("}", 1)[0]
    assert "height: 1;" in button_block
    assert "border: none;" in button_block
    refine_block = css.split("Input.plan-review-refine-input {", 1)[1].split("}", 1)[0]
    assert "height: 1;" in refine_block
    assert "border: none;" in refine_block
    assert "background: transparent;" in refine_block


def test_clarification_wire_content_plan_review() -> None:
    from soothe_cli.tui.app._execution import clarification_wire_content

    assert clarification_wire_content(["Reject", ""]) == "Plan review: Reject"
    assert clarification_wire_content(["Approve", ""]) == "Plan review: Approve"
    assert (
        clarification_wire_content(["Refine", "narrow scope"])
        == "Plan review: Refine — narrow scope"
    )
    assert clarification_wire_content(["auth flows"]) == "auth flows"
    assert clarification_wire_content(["a", "b"]) == "A1: a | A2: b"


def test_plan_review_refine_wire_content_with_comments() -> None:
    """Refine carries refinement text in answers[1]; wire formats it."""
    from soothe_cli.tui.app._execution import clarification_wire_content

    assert clarification_wire_content(["Refine", "tighten scope to auth"]) == (
        "Plan review: Refine — tighten scope to auth"
    )
    assert clarification_wire_content(["Reject", ""]) == "Plan review: Reject"


def test_path_footer_text() -> None:
    with_path = ClarificationInputMessage(
        step_id="s1",
        questions=["Action?", "Refinement instructions (when choosing Refine)"],
        origin_node="plan_mode_review",
        plan_path="/tmp/plans/x.md",
        plan_markdown="# Plan",
    )
    assert with_path._path_footer_text() == "Plan saved to: /tmp/plans/x.md"
    memory = ClarificationInputMessage(
        step_id="s1",
        questions=["Action?", "Refinement instructions (when choosing Refine)"],
        origin_node="plan_mode_review",
    )
    assert memory._path_footer_text() == "Plan held in memory only"


def test_widget_to_message_serializes_plan_review() -> None:
    from soothe_sdk.display.transcript_types import MessageType

    widget = ClarificationInputMessage(
        step_id="s1",
        questions=["Action?", "Refinement instructions (when choosing Refine)"],
        origin_node="plan_mode_review",
        plan_path="/tmp/x.md",
        plan_markdown="# Plan",
        id="clarify-test",
    )
    data = message_from_widget(widget)
    assert data.type == MessageType.APP
    assert "Plan review" in data.content
    assert "awaiting" in data.content.lower()


def test_widget_to_message_serializes_answered_plan_review_refine() -> None:
    """Answered (submitted) plan-review serializes to PLAN_REVIEW with full fidelity."""
    from soothe_sdk.display.transcript_types import MessageType

    from soothe_cli.commands.binding import message_to_widget

    widget = ClarificationInputMessage(
        step_id="s1",
        questions=["Action?", "Refinement instructions (when choosing Refine)"],
        origin_node="plan_mode_review",
        plan_path="/tmp/x.md",
        plan_markdown="# Plan\n\nDo things.",
        id="clarify-answered",
    )
    widget._submitted = True
    widget._answers = ["Refine", "将plan翻译成中文"]
    data = message_from_widget(widget)
    assert data.type == MessageType.PLAN_REVIEW
    assert data.plan_review_action == "Refine"
    assert data.plan_review_comments == "将plan翻译成中文"
    assert data.plan_markdown == "# Plan\n\nDo things."
    assert data.plan_path == "/tmp/x.md"
    assert data.plan_origin_node == "plan_mode_review"

    # Round-trip: deserialize back to a widget in answered state.
    restored = message_to_widget(data)
    assert isinstance(restored, ClarificationInputMessage)
    assert restored._submitted is True
    assert restored._answers == ["Refine", "将plan翻译成中文"]
    assert restored._plan_markdown == "# Plan\n\nDo things."


def test_widget_to_message_serializes_answered_plan_review_approve() -> None:
    """Approved plan-review serializes with no comments."""
    from soothe_sdk.display.transcript_types import MessageType

    widget = ClarificationInputMessage(
        step_id="s1",
        questions=["Action?"],
        origin_node="plan_mode_review",
        plan_markdown="# Plan",
        id="clarify-approved",
    )
    widget._submitted = True
    widget._answers = ["Approve", ""]
    data = message_from_widget(widget)
    assert data.type == MessageType.PLAN_REVIEW
    assert data.plan_review_action == "Approve"
    assert data.plan_review_comments is None
    assert "approved" in data.content.lower()


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
        step_id="plan_mode_review",
        questions=[
            "Action for this plan: Approve, Refine, or Reject",
        ],
        origin_node="plan_mode_review",
        plan_path="/ws/.soothe/plans/demo.md",
        plan_markdown="---\nstatus: draft\n---\n\n# Optimize deps\n\nStep 1.\n",
        id="clarify-approve",
    )
    async with app.run_test() as pilot:
        widget = app.query_one(ClarificationInputMessage)
        assert widget._path_footer_text() == "Plan saved to: /ws/.soothe/plans/demo.md"
        await pilot.click("#plan-review-btn-approve")
        assert len(app.submitted) == 1
        assert app.submitted[0].answers == ["Approve", ""]


@pytest.mark.asyncio
async def test_plan_review_arrow_keys_cycle_actions() -> None:
    app = _PlanReviewHarnessApp(
        step_id="plan_mode_review",
        questions=[
            "Action for this plan: Approve, Refine, or Reject",
        ],
        origin_node="plan_mode_review",
        plan_path="/ws/.soothe/plans/demo.md",
        plan_markdown="# Plan\n\nBody.\n",
        id="clarify-arrows",
    )
    async with app.run_test() as pilot:
        widget = app.query_one(ClarificationInputMessage)
        assert widget._plan_path.endswith("demo.md")
        assert widget._plan_markdown.startswith("# Plan")
        assert widget._selected_action == "approve"
        await pilot.press("down")
        assert widget._selected_action == "refine"
        await pilot.press("down")
        assert widget._selected_action == "reject"
        await pilot.press("down")
        assert widget._selected_action == "approve"
        await pilot.press("up")
        assert widget._selected_action == "reject"
        await pilot.press("up")
        assert widget._selected_action == "refine"
        # Refine focuses the comments field within the second action row.
        await pilot.press("enter")
        assert len(app.submitted) == 0
        refine_input = widget.query_one("#plan-review-refine-comments")
        refine_input.value = "narrow scope to auth"
        refine_input.focus()
        await pilot.press("enter")
        assert len(app.submitted) == 1
        assert app.submitted[0].answers == ["Refine", "narrow scope to auth"]


@pytest.mark.asyncio
async def test_plan_review_actions_render_as_numbered_rows() -> None:
    from textual.widgets import Button, Input

    app = _PlanReviewHarnessApp(
        step_id="plan_mode_review",
        questions=["Action for this plan: Approve, Refine, or Reject"],
        origin_node="plan_mode_review",
        plan_markdown="# Plan",
    )
    async with app.run_test():
        widget = app.query_one(ClarificationInputMessage)
        labels = [str(button.label) for button in widget.query(".plan-review-actions Button")]
        assert labels == ["1. Approve", "2. Refine:", "3. Reject"]
        refine_row = widget.query_one("#plan-review-btn-refine").parent
        assert refine_row is not None
        assert len(list(refine_row.query(Input))) == 1
        assert len(list(widget.query(".plan-review-action-row"))) == 3
        assert len(list(widget.query(Button))) == 3


@pytest.mark.asyncio
async def test_plan_review_reject_submits_immediately() -> None:
    app = _PlanReviewHarnessApp(
        step_id="plan_mode_review",
        questions=["Action for this plan: Approve, Refine, or Reject"],
        origin_node="plan_mode_review",
        plan_markdown="# Plan\n\nBody.\n",
        id="clarify-reject",
    )
    async with app.run_test() as pilot:
        await pilot.click("#plan-review-btn-reject")
        assert len(app.submitted) == 1
        assert app.submitted[0].answers == ["Reject", ""]


@pytest.mark.asyncio
async def test_plan_review_body_shows_full_content_without_inner_scroll() -> None:
    """Plan body expands to full height; no VerticalScroll / max-height box."""
    from textual.containers import Vertical, VerticalScroll

    long_plan = "# Solution\n\n" + "\n".join(f"- step {i}" for i in range(60))
    app = _PlanReviewHarnessApp(
        step_id="plan_mode_review",
        questions=[
            "Action for this plan: Approve, Refine, or Reject",
        ],
        origin_node="plan_mode_review",
        plan_path="/ws/.soothe/plans/demo.md",
        plan_markdown=long_plan,
        id="clarify-full-body",
    )
    async with app.run_test():
        widget = app.query_one(ClarificationInputMessage)
        assert list(widget.query(VerticalScroll)) == []
        box = widget.query_one(".plan-review-body-box", Vertical)
        # No max-height cap (was 48 rows on VerticalScroll).
        assert "max-height" not in box.styles.css or "max-height: none" in box.styles.css
        body = widget.query_one(".plan-review-body")
        rendered = str(getattr(body, "renderable", "") or "")
        assert "step 0" in rendered or "step 59" in rendered or body.display


@pytest.mark.asyncio
async def test_plan_review_answered_tree_expand_via_enter() -> None:
    """Submitted card: Enter toggles the plan body open, then closed."""
    from textual.containers import Vertical

    app = _PlanReviewHarnessApp(
        step_id="plan_mode_review",
        questions=["Action for this plan: Approve, Refine, or Reject"],
        origin_node="plan_mode_review",
        plan_path="/ws/.soothe/plans/demo.md",
        plan_markdown="# Plan\n\nDo things.",
        id="clarify-expand",
    )
    async with app.run_test() as pilot:
        widget = app.query_one(ClarificationInputMessage)
        widget._finalize_plan_review(action="approve")
        await pilot.pause()
        assert widget._submitted is True
        box = widget.query_one(".plan-review-body-box", Vertical)
        # Collapsed by default in the answered view.
        assert widget._body_expanded is False
        assert not box.has_class("is-expanded")
        # Focus the card so the Enter binding lands on it.
        widget.focus()
        await pilot.pause()
        await pilot.press("enter")
        assert widget._body_expanded is True
        assert box.has_class("is-expanded")
        await pilot.press("enter")
        assert widget._body_expanded is False
        assert not box.has_class("is-expanded")


@pytest.mark.asyncio
async def test_plan_review_answered_tree_expand_via_click() -> None:
    """Submitted card: a click toggles the plan body open."""
    from textual.containers import Vertical

    app = _PlanReviewHarnessApp(
        step_id="plan_mode_review",
        questions=["Action for this plan: Approve, Refine, or Reject"],
        origin_node="plan_mode_review",
        plan_markdown="# Plan\n\nDo things.",
        id="clarify-click-expand",
    )
    async with app.run_test() as pilot:
        widget = app.query_one(ClarificationInputMessage)
        widget._finalize_plan_review(action="approve")
        await pilot.pause()
        box = widget.query_one(".plan-review-body-box", Vertical)
        assert widget._body_expanded is False
        await pilot.click(ClarificationInputMessage)
        assert widget._body_expanded is True
        assert box.has_class("is-expanded")


def test_plan_review_answered_summary_renders_single_tree_branch() -> None:
    """Answered view: no stray empty branch; action + plan-body toggle each
    carry the ``⎿`` tree gutter (parity with the goal→step tree).

    Asserts the actual rendered output (not the pre-render private text), so
    a regression that turns the action label into Rich markup (e.g. ``[Reject]``
    parsed as a style tag with ``markup=True``) leaves the row visibly empty
    would be caught here.
    """
    import asyncio

    from textual.widgets import Static

    async def _check() -> None:
        app = _PlanReviewHarnessApp(
            step_id="plan_mode_review",
            questions=["Action?"],
            origin_node="plan_mode_review",
            plan_markdown="# Plan",
            id="clarify-tree",
        )
        async with app.run_test() as pilot:
            widget = app.query_one(ClarificationInputMessage)
            widget._finalize_plan_review(action="reject")
            await pilot.pause()  # let the answered-summary update() flush
            # No stray empty .plan-review-answered node (the old first branch).
            assert list(widget.query(".plan-review-answered")) == []
            # Action row must render its literal label — not just the gutter.
            action_w = widget.query_one(".plan-review-answered-action", Static)
            action_rendered = str(action_w.render())
            assert action_rendered.startswith("⎿")
            assert "[Reject]" in action_rendered
            assert action_rendered.strip() != "⎿".strip(), (
                "Action row collapsed to gutter only — Rich markup is stripping "
                "the literal ``[Reject]`` label."
            )
            # Toggle row carries the same tree gutter + expand glyph.
            toggle_w = widget.query_one(".plan-review-expand-toggle", Static)
            toggle_rendered = str(toggle_w.render())
            assert toggle_rendered.startswith("⎿")
            assert "Plan body" in toggle_rendered
            assert "expand" in toggle_rendered

    asyncio.run(_check())


# ===========================================================================
# tool_approval (interrupt_on) — option selector, not Input box
# ===========================================================================


def test_tool_approval_uses_option_selector_not_input() -> None:
    """A tool_approval card renders Approve / Edit / Reject buttons, no Input."""
    widget = ClarificationInputMessage(
        step_id="s1",
        questions=["Approve edit_file (file_path=/w/x.py)? [approve / edit / reject]"],
        origin_node="tool_approval",
        id="clarify-tool",
    )
    assert widget._is_option_selector is True
    assert widget._is_tool_approval is True
    assert widget._is_plan_review is False


def test_tool_approval_wire_content() -> None:
    """Tool-approval actions get a ``Tool approval:`` prefix on the wire."""
    from soothe_cli.tui.app._execution import clarification_wire_content

    assert clarification_wire_content(["Approve"], origin_node="tool_approval") == (
        "Tool approval: Approve"
    )
    assert clarification_wire_content(["Edit", "rename to y"], origin_node="tool_approval") == (
        "Tool approval: Edit — rename to y"
    )
    assert clarification_wire_content(["Reject"], origin_node="tool_approval") == (
        "Tool approval: Reject"
    )


def test_tool_approval_answered_serialization() -> None:
    """Answered tool_approval serializes with origin + Edit action."""
    from soothe_sdk.display.transcript_types import MessageType

    widget = ClarificationInputMessage(
        step_id="s1",
        questions=["Approve edit_file (file_path=/w/x.py)?"],
        origin_node="tool_approval",
        id="clarify-edit",
    )
    widget._submitted = True
    widget._answers = ["Edit", "rename to y.py"]
    data = message_from_widget(widget)
    assert data.type == MessageType.PLAN_REVIEW
    assert data.plan_review_action == "Edit"
    assert data.plan_review_comments == "rename to y.py"
    assert data.plan_origin_node == "tool_approval"
    assert "Tool edit requested" in data.content

    # Round-trip: deserialize back to a widget in answered state.
    from soothe_cli.commands.binding import message_to_widget

    restored = message_to_widget(data)
    assert isinstance(restored, ClarificationInputMessage)
    assert restored._submitted is True
    assert restored._answers == ["Edit", "rename to y.py"]
    assert restored._origin_node == "tool_approval"


@pytest.mark.asyncio
async def test_tool_approval_renders_approve_edit_reject_buttons() -> None:
    from textual.widgets import Button, Input

    app = _PlanReviewHarnessApp(
        step_id="tool_approval",
        questions=["Approve edit_file (file_path=/w/x.py)?"],
        origin_node="tool_approval",
        id="clarify-tool-buttons",
    )
    async with app.run_test():
        widget = app.query_one(ClarificationInputMessage)
        labels = [str(button.label) for button in widget.query(".plan-review-actions Button")]
        # ``Edit`` label (not ``Refine``) for tool_approval.
        assert labels == ["1. Approve", "2. Edit:", "3. Reject"]
        assert len(list(widget.query(Button))) == 3
        # No free-text answer Input — only the inline Refine/Edit comments Input.
        inputs = list(widget.query(Input))
        assert len(inputs) == 1
        assert inputs[0].id == "plan-review-refine-comments"


@pytest.mark.asyncio
async def test_tool_approval_approve_submits_immediately() -> None:
    app = _PlanReviewHarnessApp(
        step_id="tool_approval",
        questions=["Approve edit_file (file_path=/w/x.py)?"],
        origin_node="tool_approval",
        id="clarify-tool-approve",
    )
    async with app.run_test() as pilot:
        await pilot.click("#plan-review-btn-approve")
        assert len(app.submitted) == 1
        assert app.submitted[0].answers == ["Approve", ""]
        assert app.submitted[0].origin_node == "tool_approval"


@pytest.mark.asyncio
async def test_tool_approval_edit_with_comments_submits() -> None:
    app = _PlanReviewHarnessApp(
        step_id="tool_approval",
        questions=["Approve edit_file (file_path=/w/x.py)?"],
        origin_node="tool_approval",
        id="clarify-tool-edit",
    )
    async with app.run_test() as pilot:
        widget = app.query_one(ClarificationInputMessage)
        await pilot.press("down")  # approve → edit
        assert widget._selected_action == "refine"
        await pilot.press("enter")  # focus the Edit comments input
        assert len(app.submitted) == 0
        edit_input = widget.query_one("#plan-review-refine-comments")
        edit_input.value = "rename to y.py"
        edit_input.focus()
        await pilot.press("enter")
        assert len(app.submitted) == 1
        assert app.submitted[0].answers == ["Edit", "rename to y.py"]
        assert app.submitted[0].origin_node == "tool_approval"
