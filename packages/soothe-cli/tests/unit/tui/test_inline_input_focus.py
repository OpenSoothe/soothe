"""Inline option inputs in StructuredAskUserWidget — shared behavior.

Covers plan-review, tool-approval, and generic ask_user: an inline input
is enabled and focused when its option is highlighted, arrows stay free,
typed text is visible, and Ctrl+C abandons a HITL card to focus chat.
"""

from __future__ import annotations

from collections import deque
from unittest.mock import MagicMock

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Input

from soothe_cli.tui.app._messages_mixin import _MessagesMixin
from soothe_cli.tui.widgets.messages.structured_ask_user import (
    StructuredAskUserWidget,
)

# ---------------------------------------------------------------------------
# Shared fixtures (mirror test_plan_review_clarification.py conventions)
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

_CUSTOM_Q = {
    "question": "Which region?",
    "header": "Region",
    "options": [
        {"label": "us-east-1", "description": "Virginia."},
        {"label": "eu-west-1", "description": "Ireland."},
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


def _make_custom_widget(**kwargs) -> StructuredAskUserWidget:
    defaults = dict(
        step_id="ask_user",
        questions=[_CUSTOM_Q],
        origin_node="ask_user",
        allow_custom=True,
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
# Principle 1 + 2: highlight-gated enable + focus
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_comment_input_focuses_when_refine_highlighted() -> None:
    """Arrowing onto Refine enables + focuses the comment input before Enter."""
    widget = _make_plan_review_widget(id="clarify-refine-focus")
    app = _WidgetApp(widget)
    async with app.run_test() as pilot:
        await pilot.pause()
        comment_input = widget.query_one("#saq-comment-input", Input)
        # Highlight starts at 0 (Approve) — input disabled.
        assert comment_input.disabled

        widget.action_next_option()  # highlight 1 (Refine)
        await pilot.pause()

        assert not comment_input.disabled
        assert app.focused is comment_input
        assert len(app.submitted) == 0  # no submit fired


@pytest.mark.asyncio
async def test_arrows_remain_free_while_comment_input_focused() -> None:
    """↑/↓ move the highlight even while the comment input is focused."""
    widget = _make_plan_review_widget(id="clarify-arrows")
    app = _WidgetApp(widget)
    async with app.run_test() as pilot:
        await pilot.pause()
        comment_input = widget.query_one("#saq-comment-input", Input)

        widget.action_next_option()  # → Refine
        await pilot.pause()
        assert app.focused is comment_input

        widget.action_prev_option()  # → Approve
        await pilot.pause()
        assert comment_input.disabled  # left Refine → disabled
        assert widget._highlighted == 0

        widget.action_next_option()  # back to Refine
        await pilot.pause()
        assert not comment_input.disabled  # reactivated
        assert app.focused is comment_input

        widget.action_next_option()  # → Reject
        await pilot.pause()
        assert comment_input.disabled
        assert widget._highlighted == 2
        assert len(app.submitted) == 0  # never submitted


@pytest.mark.asyncio
async def test_comment_input_displays_typed_text() -> None:
    """Typed text is visible in the comment input (regression for height:1 clip)."""
    widget = _make_plan_review_widget(id="clarify-type")
    app = _WidgetApp(widget)
    async with app.run_test() as pilot:
        await pilot.pause()
        widget.action_next_option()  # Refine
        await pilot.pause()
        comment_input = widget.query_one("#saq-comment-input", Input)
        comment_input.value = "narrow scope to auth"
        await pilot.pause()
        assert comment_input.value == "narrow scope to auth"


@pytest.mark.asyncio
async def test_first_keystroke_not_lost_after_refine_highlight() -> None:
    """First char typed right after highlighting Refine is not dropped."""
    widget = _make_plan_review_widget(id="clarify-firstchar")
    app = _WidgetApp(widget)
    async with app.run_test() as pilot:
        await pilot.pause()
        widget.action_next_option()  # highlight Refine — no pause
        for ch in "hello":
            await pilot.press(ch)
        await pilot.pause()
        comment_input = widget.query_one("#saq-comment-input", Input)
        assert comment_input.value == "hello"


@pytest.mark.asyncio
async def test_enter_on_refine_with_empty_comment_keeps_focus() -> None:
    """Enter on Refine with no comment keeps focus on the input, not submit."""
    widget = _make_plan_review_widget(id="clarify-empty-enter")
    app = _WidgetApp(widget)
    async with app.run_test() as pilot:
        await pilot.pause()
        widget.action_next_option()  # highlight Refine
        await pilot.pause()
        comment_input = widget.query_one("#saq-comment-input", Input)
        assert app.focused is comment_input

        # Enter with empty comment — must not submit, focus must stay.
        await pilot.press("enter")
        await pilot.pause()

        assert len(app.submitted) == 0
        assert app.focused is comment_input

        # Typing still works after Enter.
        for ch in "hi":
            await pilot.press(ch)
        await pilot.pause()
        assert comment_input.value == "hi"


@pytest.mark.asyncio
async def test_refine_submit_via_comment_input_enter() -> None:
    """Refine + comment via Enter on the input, bypassing action_confirm."""
    widget = _make_plan_review_widget(id="clarify-refine-enter")
    app = _WidgetApp(widget)
    async with app.run_test() as pilot:
        await pilot.pause()
        widget.action_next_option()  # highlight Refine
        await pilot.pause()
        comment_input = widget.query_one("#saq-comment-input", Input)
        comment_input.value = "narrow scope to auth"
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        assert len(app.submitted) == 1
        assert app.submitted[0].answers[0] == "Refine"
        assert "narrow scope to auth" in app.submitted[0].answers[1]


# ---------------------------------------------------------------------------
# Generic ask_user: the "Other" custom input follows the same rules
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_custom_input_focuses_when_other_highlighted() -> None:
    """Arrowing onto "Other" enables + focuses the custom input before Enter."""
    widget = _make_custom_widget(id="clarify-custom-focus")
    app = _WidgetApp(widget)
    async with app.run_test() as pilot:
        await pilot.pause()
        custom_input = widget.query_one("#saq-custom-input", Input)

        # Two options → "Other" is at index 2. Highlight starts at 0.
        widget.action_next_option()  # 1
        widget.action_next_option()  # 2 → "Other"
        await pilot.pause()

        assert not custom_input.disabled
        assert app.focused is custom_input


@pytest.mark.asyncio
async def test_custom_input_displays_typed_text() -> None:
    """Typed text is visible in the custom input (shared CSS regression)."""
    widget = _make_custom_widget(id="clarify-custom-type")
    app = _WidgetApp(widget)
    async with app.run_test() as pilot:
        await pilot.pause()
        widget.action_next_option()  # 1
        widget.action_next_option()  # 2 → "Other"
        await pilot.pause()
        custom_input = widget.query_one("#saq-custom-input", Input)
        custom_input.value = "ap-southeast-2"
        await pilot.pause()
        assert custom_input.value == "ap-southeast-2"


@pytest.mark.asyncio
async def test_arrow_to_approve_reject_does_not_scroll_to_plan_header() -> None:
    """Highlighting Approve/Reject must not scroll to the plan header."""
    from textual.containers import VerticalScroll
    from textual.widgets import Static

    plan = "# Plan\n\n" + "\n\nParagraph of plan content.\n" * 30

    class _ScrollApp(App[None]):
        def compose(self) -> ComposeResult:
            with VerticalScroll(id="chat"):
                yield Static("transcript above\n" * 10, id="above")
                yield StructuredAskUserWidget(
                    step_id="plan_mode_review",
                    questions=[_PLAN_REVIEW_Q],
                    origin_node="plan_mode_review",
                    allow_custom=False,
                    comment_option_index=1,
                    body_markdown=plan,
                    id="clarify-scroll",
                )

    app = _ScrollApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        w = pilot.app.query_one(StructuredAskUserWidget)
        chat = pilot.app.query_one("#chat", VerticalScroll)
        # Scroll so the options menu is visible (bottom of card).
        w.query_one(".saq-option-list").scroll_visible()
        await pilot.pause()
        y_before = chat.scroll_offset.y
        assert y_before > 0  # scrolled past the plan header

        # Cycle through all options with real keypresses — scroll must not
        # jump to the plan header.  The regression: disabling the comment
        # input on Refine→Reject dropped focus to None, the 200 ms guard
        # recaptured via set_focus(self), and Textual scrolled to the top.
        await pilot.press("down")  # Refine
        await pilot.pause()
        await pilot.press("down")  # Reject
        await pilot.pause()
        await pilot.press("up")  # Refine
        await pilot.pause()
        await pilot.press("up")  # Approve
        await pilot.pause()

        assert chat.scroll_offset.y >= y_before


# ---------------------------------------------------------------------------
# Principle 4: Ctrl+C abandons a HITL card → focus chat input
# ---------------------------------------------------------------------------


class _QuitAppStub(App, _MessagesMixin):
    """Minimal App + mixin stub for the Ctrl+C intercept path.

    Chat input is mocked; mounting a real ChatInput pulls in design tokens
    the bare App doesn't define.
    """

    def __init__(self) -> None:
        super().__init__()
        self._ctrl_c_pressed_time: float | None = None
        self._daemon_session = None
        self._shutdown_prepared = False
        self._shell_running = False
        self._shell_worker = None
        self._agent_running = False
        self._agent_worker = None
        self._pending_messages = deque()
        self._queued_widgets = deque()
        self._deferred_actions = []
        self._detaching = False
        self._chat_input: MagicMock | None = MagicMock()
        self._chat_input.focus_input = MagicMock()
        self._chat_input.clear_input = MagicMock()
        self._chat_input.value = ""
        self._ui_adapter: MagicMock | None = None
        self.notify = MagicMock()


@pytest.mark.asyncio
async def test_ctrl_c_abandons_plan_review_and_focuses_chat() -> None:
    """Ctrl+C on an active plan-review card abandons it and focuses chat."""
    widget = _make_plan_review_widget(id="clarify-ctrlc")
    widget._abandon = MagicMock(side_effect=widget._abandon)

    app = _QuitAppStub()
    # Wire the adapter so _active_plan_review_widget() finds the card.
    adapter = MagicMock()
    adapter._clarification_input_by_step = {"step-1": widget}
    app._ui_adapter = adapter

    async with app.run_test() as pilot:
        await pilot.pause()
        assert app._has_active_qa_widget()

        app.action_quit_or_interrupt()
        await pilot.pause()

        # Card abandoned (empty answers posted) and chat input focused.
        widget._abandon.assert_called_once()
        assert widget._submitted is True
        assert app._ctrl_c_pressed_time is None  # no exit arming
        app._chat_input.focus_input.assert_called_once()


@pytest.mark.asyncio
async def test_ctrl_c_outside_plan_review_keeps_global_behavior() -> None:
    """With no active card, Ctrl+C still clears chat + arms exit (regression)."""
    app = _QuitAppStub()
    app._chat_input.value = "draft text"
    # No adapter → _has_active_qa_widget() is False.
    async with app.run_test() as pilot:
        await pilot.pause()

        app.action_quit_or_interrupt()
        await pilot.pause()

        # First-press idle path: input cleared + exit armed (not abandoned).
        app._chat_input.clear_input.assert_called_once()
        assert app._ctrl_c_pressed_time is not None


@pytest.mark.asyncio
async def test_escape_abandons_generic_ask_user() -> None:
    """Esc remains the universal cancel for non-HITL (generic ask_user) cards."""
    widget = _make_custom_widget(id="clarify-escape")
    app = _WidgetApp(widget)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert not widget._submitted

        widget.action_abandon()
        await pilot.pause()

        assert widget._submitted is True
        assert len(app.submitted) == 1
        assert app.submitted[0].answers == []
