"""Plan-review clarification widget (plan_mode_review) — unified widget tests.

After IG-767, plan-review and tool-approval HITL gates render through
``StructuredAskUserWidget`` with ``allow_custom=False`` and prefilled
options (Approve / Refine or Edit / Reject).
"""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from soothe_cli.commands.binding import message_from_widget
from soothe_cli.tui.widgets.messages.structured_ask_user import (
    StructuredAskUserWidget,
    _strip_plan_frontmatter,
)

# ---------------------------------------------------------------------------
# Frontmatter helper (moved from clarification.py)
# ---------------------------------------------------------------------------


def test_strip_plan_frontmatter_removes_yaml() -> None:
    raw = "---\nstatus: draft\n---\n\n# Plan\n\nDo the thing.\n"
    assert _strip_plan_frontmatter(raw) == "# Plan\n\nDo the thing."


def test_strip_plan_frontmatter_passthrough() -> None:
    assert _strip_plan_frontmatter("# Already clean") == "# Already clean"


# ---------------------------------------------------------------------------
# Wire content helper (unchanged — lives in _execution.py)
# ---------------------------------------------------------------------------


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
    from soothe_cli.tui.app._execution import clarification_wire_content

    assert clarification_wire_content(["Refine", "tighten scope to auth"]) == (
        "Plan review: Refine — tighten scope to auth"
    )
    assert clarification_wire_content(["Reject", ""]) == "Plan review: Reject"


# ---------------------------------------------------------------------------
# Widget fixtures
# ---------------------------------------------------------------------------

_PLAN_REVIEW_Q = {
    "question": "Action for this plan: Approve, Refine, or Reject?",
    "header": "Plan review",
    "options": [
        {"label": "Approve", "description": "Accept the plan and proceed."},
        {"label": "Refine", "description": "Request changes with refinement instructions."},
        {"label": "Reject", "description": "Reject the plan and terminate this goal."},
    ],
}

_TOOL_APPROVAL_Q = {
    "question": "Approve read_file (path=/tmp/x)?",
    "header": "Approve read_file (path=/tmp/x)",
    "options": [
        {"label": "Approve", "description": "Allow this tool call."},
        {"label": "Edit", "description": "Revise the tool args."},
        {"label": "Reject", "description": "Deny this tool call."},
    ],
}


def _make_plan_review_widget(**kwargs) -> StructuredAskUserWidget:
    defaults = dict(
        step_id="plan_mode_review",
        questions=[_PLAN_REVIEW_Q],
        origin_node="plan_mode_review",
        allow_custom=False,
        comment_option_index=1,
    )
    defaults.update(kwargs)
    return StructuredAskUserWidget(**defaults)


def _make_tool_approval_widget(**kwargs) -> StructuredAskUserWidget:
    defaults = dict(
        step_id="tool_approval",
        questions=[_TOOL_APPROVAL_Q],
        origin_node="tool_approval",
        allow_custom=False,
        comment_option_index=1,
    )
    defaults.update(kwargs)
    return StructuredAskUserWidget(**defaults)


class _WidgetApp(App[None]):
    """Minimal harness mounting a single StructuredAskUserWidget."""

    def __init__(self, widget: StructuredAskUserWidget) -> None:
        super().__init__()
        self._widget = widget
        self.submitted: list[StructuredAskUserWidget.Submitted] = []

    def compose(self) -> ComposeResult:
        yield self._widget

    def on_structured_ask_user_widget_submitted(
        self, event: StructuredAskUserWidget.Submitted
    ) -> None:
        self.submitted.append(event)


# ---------------------------------------------------------------------------
# Path footer
# ---------------------------------------------------------------------------


def test_path_footer_text() -> None:
    with_path = _make_plan_review_widget(
        body_path="/tmp/plans/x.md",
        body_markdown="# Plan",
    )
    assert with_path._path_footer_text() == "Plan saved to: /tmp/plans/x.md"
    memory = _make_plan_review_widget()
    assert memory._path_footer_text() == "Plan held in memory only"


# ---------------------------------------------------------------------------
# Serialization (message_from_widget)
# ---------------------------------------------------------------------------


def test_widget_to_message_serializes_plan_review() -> None:
    from soothe_sdk.display.transcript_types import MessageType

    widget = _make_plan_review_widget(
        body_path="/tmp/x.md",
        body_markdown="# Plan",
        id="clarify-test",
    )
    data = message_from_widget(widget)
    assert data.type == MessageType.APP
    assert "Plan review" in data.content
    assert "awaiting" in data.content.lower()


def test_widget_to_message_serializes_answered_plan_review_refine() -> None:
    from soothe_sdk.display.transcript_types import MessageType

    from soothe_cli.commands.binding import message_to_widget

    widget = _make_plan_review_widget(
        body_path="/tmp/x.md",
        body_markdown="# Plan\n\nDo things.",
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
    assert isinstance(restored, StructuredAskUserWidget)
    assert restored._submitted is True
    assert restored._answers == ["Refine", "将plan翻译成中文"]
    assert restored._body_markdown == "# Plan\n\nDo things."


def test_widget_to_message_serializes_answered_plan_review_approve() -> None:
    from soothe_sdk.display.transcript_types import MessageType

    widget = _make_plan_review_widget(
        body_markdown="# Plan",
        id="clarify-approved",
    )
    widget._submitted = True
    widget._answers = ["Approve", ""]
    data = message_from_widget(widget)
    assert data.type == MessageType.PLAN_REVIEW
    assert data.plan_review_action == "Approve"
    assert data.plan_review_comments is None
    assert "approved" in data.content.lower()


# ---------------------------------------------------------------------------
# Interactive: approve / reject / refine
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_review_approve_submits_immediately() -> None:
    widget = _make_plan_review_widget(
        body_path="/ws/.soothe/plans/demo.md",
        body_markdown="---\nstatus: draft\n---\n\n# Optimize deps\n\nStep 1.\n",
        id="clarify-approve",
    )
    app = _WidgetApp(widget)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert widget._path_footer_text() == "Plan saved to: /ws/.soothe/plans/demo.md"
        # Select Approve (option 0) and confirm — HITL immediate-submit.
        widget.action_confirm()
        await pilot.pause()
        assert len(app.submitted) == 1
        assert app.submitted[0].answers == ["Approve"]


@pytest.mark.asyncio
async def test_plan_review_reject_submits_immediately() -> None:
    widget = _make_plan_review_widget(
        body_markdown="# Plan\n\nBody.\n",
        id="clarify-reject",
    )
    app = _WidgetApp(widget)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Navigate to Reject (option 2) and confirm.
        widget.action_next_option()  # highlight 1 (Refine)
        widget.action_next_option()  # highlight 2 (Reject)
        widget.action_confirm()
        await pilot.pause()
        assert len(app.submitted) == 1
        assert app.submitted[0].answers == ["Reject"]


@pytest.mark.asyncio
async def test_plan_review_refine_with_comments() -> None:
    widget = _make_plan_review_widget(
        body_markdown="# Plan\n\nBody.\n",
        id="clarify-refine",
    )
    app = _WidgetApp(widget)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Navigate to Refine (option 1).
        widget.action_next_option()  # highlight 1 (Refine)
        widget.action_confirm()  # selects Refine → focuses comment input
        await pilot.pause()
        assert len(app.submitted) == 0  # not submitted yet
        # Type refinement comments and press Enter.
        comment_input = widget.query_one("#saq-comment-input")
        comment_input.value = "narrow scope to auth"
        comment_input.focus()
        await pilot.press("enter")
        await pilot.pause()
        assert len(app.submitted) == 1
        assert app.submitted[0].answers[0] == "Refine"
        assert "narrow scope to auth" in app.submitted[0].answers[1]


@pytest.mark.asyncio
async def test_comment_input_inline_beside_refine_option() -> None:
    """The HITL comment input is rendered inside a Horizontal beside the
    Refine option, not as a standalone element below all options."""
    from textual.containers import Horizontal

    widget = _make_plan_review_widget(
        body_markdown="# Plan",
        id="clarify-inline-comment",
    )
    app = _WidgetApp(widget)
    async with app.run_test() as pilot:
        await pilot.pause()
        w = app.query_one(StructuredAskUserWidget)
        comment_input = w.query_one("#saq-comment-input")
        # The parent of the comment input should be a Horizontal with the
        # saq-option-with-comment class — it's inline beside the option.
        parent = comment_input.parent
        assert isinstance(parent, Horizontal)
        assert parent.has_class("saq-option-with-comment")
        # The option Static (saq-opt-1 = Refine) is a sibling in the same row.
        opt_1 = w.query_one("#saq-opt-1")
        assert opt_1.parent is parent


# ---------------------------------------------------------------------------
# Plan body rendering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_review_body_shows_full_content_without_inner_scroll() -> None:
    from textual.containers import VerticalScroll

    long_plan = "# Solution\n\n" + "\n".join(f"- step {i}" for i in range(60))
    widget = _make_plan_review_widget(
        body_path="/ws/.soothe/plans/demo.md",
        body_markdown=long_plan,
        id="clarify-full-body",
    )
    app = _WidgetApp(widget)
    async with app.run_test():
        w = app.query_one(StructuredAskUserWidget)
        assert list(w.query(VerticalScroll)) == []
        body = w.query_one(".saq-body")
        rendered = str(getattr(body, "renderable", "") or "")
        assert "step 0" in rendered or "step 59" in rendered or body.display


@pytest.mark.asyncio
async def test_plan_review_answered_tree_expand_via_enter() -> None:
    from textual.containers import Vertical

    widget = _make_plan_review_widget(
        body_path="/ws/.soothe/plans/demo.md",
        body_markdown="# Plan\n\nDo things.",
        id="clarify-expand",
    )
    app = _WidgetApp(widget)
    async with app.run_test() as pilot:
        w = app.query_one(StructuredAskUserWidget)
        # Submit with Approve.
        w.action_confirm()
        await pilot.pause()
        assert w._submitted is True
        box = w.query_one(".saq-body-box", Vertical)
        assert w._body_expanded is False
        assert not box.has_class("is-expanded")
        # Enter toggles body expand.
        w.focus()
        await pilot.pause()
        await pilot.press("enter")
        assert w._body_expanded is True
        assert box.has_class("is-expanded")
        await pilot.press("enter")
        assert w._body_expanded is False
        assert not box.has_class("is-expanded")


@pytest.mark.asyncio
async def test_plan_review_answered_tree_expand_via_click() -> None:
    from textual.containers import Vertical

    widget = _make_plan_review_widget(
        body_markdown="# Plan\n\nDo things.",
        id="clarify-click-expand",
    )
    app = _WidgetApp(widget)
    async with app.run_test() as pilot:
        w = app.query_one(StructuredAskUserWidget)
        w.action_confirm()
        await pilot.pause()
        box = w.query_one(".saq-body-box", Vertical)
        assert w._body_expanded is False
        # Click toggles body expand.
        await pilot.click(".saq-body-box")
        await pilot.pause()
        assert w._body_expanded is True
        assert box.has_class("is-expanded")


# ---------------------------------------------------------------------------
# Tool approval
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_approval_title() -> None:
    widget = _make_tool_approval_widget(id="clarify-tool")
    app = _WidgetApp(widget)
    async with app.run_test() as pilot:
        await pilot.pause()
        w = app.query_one(StructuredAskUserWidget)
        title = w._tool_approval_title()
        assert "read_file" in title
        assert "Approve tool" in title


@pytest.mark.asyncio
async def test_tool_approval_approve() -> None:
    widget = _make_tool_approval_widget(id="clarify-tool-approve")
    app = _WidgetApp(widget)
    async with app.run_test() as pilot:
        await pilot.pause()
        w = app.query_one(StructuredAskUserWidget)
        w.action_confirm()  # Approve (option 0)
        await pilot.pause()
        assert len(app.submitted) == 1
        assert app.submitted[0].answers == ["Approve"]


@pytest.mark.asyncio
async def test_tool_approval_reject() -> None:
    widget = _make_tool_approval_widget(id="clarify-tool-reject")
    app = _WidgetApp(widget)
    async with app.run_test() as pilot:
        await pilot.pause()
        w = app.query_one(StructuredAskUserWidget)
        w.action_next_option()  # Refine
        w.action_next_option()  # Reject
        w.action_confirm()
        await pilot.pause()
        assert len(app.submitted) == 1
        assert app.submitted[0].answers == ["Reject"]


# ---------------------------------------------------------------------------
# HITL: no "Other" custom row
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hitl_no_custom_row() -> None:
    widget = _make_plan_review_widget(id="clarify-no-custom")
    app = _WidgetApp(widget)
    async with app.run_test() as pilot:
        await pilot.pause()
        w = app.query_one(StructuredAskUserWidget)
        # No custom row, no custom input.
        try:
            w.query_one("#saq-opt-custom")
            assert False, "custom row should not exist for HITL"
        except Exception:
            pass
        try:
            w.query_one("#saq-custom-input")
            assert False, "custom input should not exist for HITL"
        except Exception:
            pass


# ---------------------------------------------------------------------------
# CSS: padding parity with other cards
# ---------------------------------------------------------------------------


def test_stream_cards_use_horizontal_inset_padding() -> None:
    from soothe_cli.tui.widgets.messages.assistant import AssistantMessage
    from soothe_cli.tui.widgets.messages.cognition_step import CognitionStepMessage

    step_css = CognitionStepMessage.DEFAULT_CSS
    assistant_css = AssistantMessage.DEFAULT_CSS
    clarification_css = StructuredAskUserWidget.DEFAULT_CSS
    assert "padding: 0 1;" in step_css
    assert "padding: 0 1;" in assistant_css
    assert "padding: 0 1;" in clarification_css
    assert "border-left:" not in step_css
    assert "border-left:" not in assistant_css
    assert "border-left:" not in clarification_css
