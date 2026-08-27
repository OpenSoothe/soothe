"""Unit tests for ``StructuredAskUserWidget`` (RFC-622 §9c)."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult

from soothe_cli.tui.widgets.messages.structured_ask_user import (
    StructuredAskUserWidget,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _question_dict(
    question: str = "How should the API authenticate requests?",
    header: str = "Auth method",
) -> dict:
    return {
        "question": question,
        "header": header,
        "options": [
            {"label": "OAuth", "description": "OAuth 2.0 with PKCE. Best for browser flows."},
            {
                "label": "API key",
                "description": "Static API key in a header. Simplest to implement.",
            },
            {
                "label": "Session",
                "description": "Server-side session with cookies. Best for SSR apps.",
            },
        ],
    }


def _questions(n: int = 2) -> list[dict]:
    headers = ["Auth", "Token", "Retry", "Cache", "Log"]
    return [_question_dict(header=headers[i], question=f"Question {i + 1}?") for i in range(n)]


class _WidgetApp(App[None]):
    """Minimal harness mounting a single StructuredAskUserWidget."""

    def __init__(self, widget: StructuredAskUserWidget) -> None:
        super().__init__()
        self._widget = widget

    def compose(self) -> ComposeResult:
        yield self._widget


class _StreamLayoutApp(App[None]):
    """Harness replicating the real app layout (#chat scroll → #messages stream).

    The production app mounts message widgets into a ``layout: stream``
    container; Vertical children with the default ``1fr`` height collapse
    there. Regression guard for the missing ``height: auto`` bug.
    """

    CSS = """
    #chat { height: 1fr; }
    #messages { layout: stream; height: auto; }
    """

    def __init__(self, widget: StructuredAskUserWidget) -> None:
        super().__init__()
        self._widget = widget

    def compose(self) -> ComposeResult:
        from textual.containers import Container, VerticalScroll

        with VerticalScroll(id="chat"):
            yield Container(self._widget, id="messages")


def _make_widget(
    *,
    questions: list | None = None,
    degraded: bool = False,
    origin_node: str = "execute",
) -> StructuredAskUserWidget:
    return StructuredAskUserWidget(
        step_id="step-1",
        questions=questions or _questions(2),
        widget_id="test-widget",
        id="test-widget",
        origin_node=origin_node,
        degraded=degraded,
    )


# ---------------------------------------------------------------------------
# Compose — structured mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_structured_compose_renders_tab_bar_for_multiple_questions() -> None:
    app = _WidgetApp(_make_widget(questions=_questions(3)))
    async with app.run_test() as pilot:
        await pilot.pause()
        w = pilot.app.query_one("#test-widget", StructuredAskUserWidget)
        tabs = w.query(".saq-tab")
        assert len(tabs) == 3


@pytest.mark.asyncio
async def test_structured_compose_hides_tab_bar_for_single_question() -> None:
    app = _WidgetApp(_make_widget(questions=[_question_dict()]))
    async with app.run_test() as pilot:
        await pilot.pause()
        w = pilot.app.query_one("#test-widget", StructuredAskUserWidget)
        tabs = w.query(".saq-tab")
        assert len(tabs) == 0


@pytest.mark.asyncio
async def test_structured_compose_renders_option_rows_plus_custom() -> None:
    app = _WidgetApp(_make_widget())
    async with app.run_test() as pilot:
        await pilot.pause()
        w = pilot.app.query_one("#test-widget", StructuredAskUserWidget)
        opts = w.query(".saq-option-row")
        # 3 options + 1 custom row
        assert len(opts) == 4


@pytest.mark.asyncio
async def test_structured_renders_inline_option_descriptions() -> None:
    """Each option's long description renders directly below its label."""
    app = _WidgetApp(_make_widget())
    async with app.run_test() as pilot:
        await pilot.pause()
        w = pilot.app.query_one("#test-widget", StructuredAskUserWidget)
        descs = w.query(".saq-option-desc")
        assert len(descs) == 3  # one per option, custom row has none
        first = w.query_one("#saq-optdesc-0")
        assert "OAuth 2.0 with PKCE" in str(first.render())
        # No hover-preview box — descriptions are inline now.
        assert len(w.query(".saq-preview-box")) == 0
        # Recap box hidden until submit review opens.
        recap = w.query_one("#saq-recap-box")
        assert "is-visible" not in recap.classes


@pytest.mark.asyncio
async def test_no_hint_line() -> None:
    """The keyboard hint line is removed — keybindings are self-evident."""
    app = _WidgetApp(_make_widget())
    async with app.run_test() as pilot:
        await pilot.pause()
        w = pilot.app.query_one("#test-widget", StructuredAskUserWidget)
        assert len(w.query(".saq-hint")) == 0


@pytest.mark.asyncio
async def test_visual_separators_above_and_below() -> None:
    """Top + bottom separator rules distinguish the widget from surrounding messages."""
    app = _WidgetApp(_make_widget())
    async with app.run_test() as pilot:
        await pilot.pause()
        w = pilot.app.query_one("#test-widget", StructuredAskUserWidget)
        seps = w.query(".saq-separator")
        assert len(seps) == 2


@pytest.mark.asyncio
async def test_separators_hidden_after_submit() -> None:
    """After submit the separators are hidden — the widget collapses to a compact summary."""
    app = _WidgetApp(_make_widget())
    async with app.run_test() as pilot:
        await pilot.pause()
        w = pilot.app.query_one("#test-widget", StructuredAskUserWidget)
        # Visible before submit.
        seps = list(w.query(".saq-separator"))
        assert len(seps) == 2
        assert all(s.display for s in seps)
        w.action_confirm()  # Q1 selected, auto-advance to Q2
        w.action_confirm()  # Q2 selected, auto-open review
        w.action_confirm()  # finalizes
        await pilot.pause()
        assert w._submitted is True
        # Separators are in the DOM but visually hidden via display: none.
        seps = list(w.query(".saq-separator"))
        assert len(seps) == 2
        assert all(not s.display for s in seps)


@pytest.mark.asyncio
async def test_focus_guard_runs_while_active() -> None:
    """A recurring focus guard starts on mount to recapture focus from the chat input."""
    app = _WidgetApp(_make_widget())
    async with app.run_test() as pilot:
        await pilot.pause()
        w = pilot.app.query_one("#test-widget", StructuredAskUserWidget)
        assert w._focus_guard_timer is not None
        # And it stops after submit/abandon.
        w._finalize()
        await pilot.pause()
        assert w._focus_guard_timer is None


@pytest.mark.asyncio
async def test_structured_compose_renders_footer_with_submit_and_abandon() -> None:
    app = _WidgetApp(_make_widget())
    async with app.run_test() as pilot:
        await pilot.pause()
        w = pilot.app.query_one("#test-widget", StructuredAskUserWidget)
        assert w._submit_btn is not None
        assert w._abandon_btn is not None


# ---------------------------------------------------------------------------
# Navigation — question switching
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_next_question_switches_tab() -> None:
    app = _WidgetApp(_make_widget(questions=_questions(3)))
    async with app.run_test() as pilot:
        await pilot.pause()
        w = pilot.app.query_one("#test-widget", StructuredAskUserWidget)
        assert w._current_q == 0
        w.action_next_question()
        assert w._current_q == 1
        w.action_next_question()
        assert w._current_q == 2
        w.action_next_question()
        assert w._current_q == 0


@pytest.mark.asyncio
async def test_prev_question_switches_tab() -> None:
    app = _WidgetApp(_make_widget(questions=_questions(3)))
    async with app.run_test() as pilot:
        await pilot.pause()
        w = pilot.app.query_one("#test-widget", StructuredAskUserWidget)
        w.action_prev_question()
        assert w._current_q == 2
        w.action_prev_question()
        assert w._current_q == 1


@pytest.mark.asyncio
async def test_question_switch_noop_for_single_question() -> None:
    app = _WidgetApp(_make_widget(questions=[_question_dict()]))
    async with app.run_test() as pilot:
        await pilot.pause()
        w = pilot.app.query_one("#test-widget", StructuredAskUserWidget)
        w.action_next_question()
        assert w._current_q == 0


# ---------------------------------------------------------------------------
# Navigation — option highlight
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_next_option_cycles_highlight() -> None:
    app = _WidgetApp(_make_widget())
    async with app.run_test() as pilot:
        await pilot.pause()
        w = pilot.app.query_one("#test-widget", StructuredAskUserWidget)
        assert w._highlighted == 0
        w.action_next_option()
        assert w._highlighted == 1
        w.action_next_option()
        assert w._highlighted == 2
        w.action_next_option()
        assert w._highlighted == 3  # custom
        w.action_next_option()
        assert w._highlighted == 0  # wraps


@pytest.mark.asyncio
async def test_prev_option_cycles_highlight() -> None:
    app = _WidgetApp(_make_widget())
    async with app.run_test() as pilot:
        await pilot.pause()
        w = pilot.app.query_one("#test-widget", StructuredAskUserWidget)
        w.action_prev_option()
        assert w._highlighted == 3  # wraps backward to custom
        w.action_prev_option()
        assert w._highlighted == 2


# ---------------------------------------------------------------------------
# Enter — option selection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enter_selects_option() -> None:
    app = _WidgetApp(_make_widget(questions=_questions(2)))
    async with app.run_test() as pilot:
        await pilot.pause()
        w = pilot.app.query_one("#test-widget", StructuredAskUserWidget)
        w.action_next_option()  # highlight 1
        assert w._highlighted == 1
        w.action_confirm()
        assert w._selected.get(0) == 1
        assert w._all_answered is False


@pytest.mark.asyncio
async def test_enter_auto_advances_to_next_unanswered() -> None:
    app = _WidgetApp(_make_widget(questions=_questions(3)))
    async with app.run_test() as pilot:
        await pilot.pause()
        w = pilot.app.query_one("#test-widget", StructuredAskUserWidget)
        w.action_confirm()
        assert w._selected.get(0) == 0
        assert w._current_q == 1


@pytest.mark.asyncio
async def test_last_answer_auto_opens_submit_review() -> None:
    """Selecting the final unanswered option opens the review so Enter submits."""
    app = _WidgetApp(_make_widget(questions=_questions(1)))
    async with app.run_test() as pilot:
        await pilot.pause()
        w = pilot.app.query_one("#test-widget", StructuredAskUserWidget)
        assert w._num_questions == 1
        w.action_confirm()
        assert w._all_answered is True
        assert w._submit_review_open is True
        # Enter again finalizes.
        w.action_confirm()
        await pilot.pause()
        assert w._submitted is True


@pytest.mark.asyncio
async def test_escape_from_review_returns_to_editing() -> None:
    """Escape closes the review (keep editing) instead of abandoning."""
    app = _WidgetApp(_make_widget(questions=_questions(1)))
    async with app.run_test() as pilot:
        await pilot.pause()
        w = pilot.app.query_one("#test-widget", StructuredAskUserWidget)
        w.action_confirm()
        assert w._submit_review_open is True
        w.action_abandon()
        assert w._submit_review_open is False
        assert w._submitted is False
        # Second Escape (outside review) abandons.
        w.action_abandon()
        assert w._submitted is True


@pytest.mark.asyncio
async def test_all_answered_after_selecting_each_question() -> None:
    app = _WidgetApp(_make_widget(questions=_questions(2)))
    async with app.run_test() as pilot:
        await pilot.pause()
        w = pilot.app.query_one("#test-widget", StructuredAskUserWidget)
        w.action_confirm()
        assert w._current_q == 1
        w.action_confirm()
        assert w._all_answered is True


# ---------------------------------------------------------------------------
# Custom row
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_custom_row_enables_input_when_highlighted() -> None:
    app = _WidgetApp(_make_widget())
    async with app.run_test() as pilot:
        await pilot.pause()
        w = pilot.app.query_one("#test-widget", StructuredAskUserWidget)
        w.action_next_option()
        w.action_next_option()
        w.action_next_option()
        assert w._highlighted == 3
        assert w._custom_input is not None
        assert w._custom_input.disabled is False


@pytest.mark.asyncio
async def test_custom_row_disables_input_when_not_highlighted() -> None:
    app = _WidgetApp(_make_widget())
    async with app.run_test() as pilot:
        await pilot.pause()
        w = pilot.app.query_one("#test-widget", StructuredAskUserWidget)
        assert w._highlighted == 0
        assert w._custom_input is not None
        assert w._custom_input.disabled is True


# ---------------------------------------------------------------------------
# Submit flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_disabled_until_all_answered() -> None:
    app = _WidgetApp(_make_widget(questions=_questions(2)))
    async with app.run_test() as pilot:
        await pilot.pause()
        w = pilot.app.query_one("#test-widget", StructuredAskUserWidget)
        assert w._all_answered is False
        w.action_confirm()
        assert w._all_answered is False
        w.action_confirm()
        assert w._all_answered is True


@pytest.mark.asyncio
async def test_submit_opens_recap_then_finalizes() -> None:
    app = _WidgetApp(_make_widget(questions=_questions(2)))
    async with app.run_test() as pilot:
        await pilot.pause()
        w = pilot.app.query_one("#test-widget", StructuredAskUserWidget)
        w.action_confirm()
        w.action_confirm()
        assert w._all_answered is True
        assert w._submit_btn is not None
        w._submit_btn.press()
        await pilot.pause()
        assert w._submit_review_open is True
        w.action_confirm()
        await pilot.pause()
        assert w._submitted is True


@pytest.mark.asyncio
async def test_submit_button_does_nothing_when_not_all_answered() -> None:
    app = _WidgetApp(_make_widget(questions=_questions(2)))
    async with app.run_test() as pilot:
        await pilot.pause()
        w = pilot.app.query_one("#test-widget", StructuredAskUserWidget)
        assert w._submit_btn is not None
        w._submit_btn.press()
        await pilot.pause()
        assert w._submit_review_open is False
        assert w._submitted is False


# ---------------------------------------------------------------------------
# Abandon
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_abandon_posts_submitted_with_empty_answers() -> None:
    app = _WidgetApp(_make_widget())
    async with app.run_test() as pilot:
        await pilot.pause()
        w = pilot.app.query_one("#test-widget", StructuredAskUserWidget)
        w.action_abandon()
        await pilot.pause()
        assert w._submitted is True


# ---------------------------------------------------------------------------
# Submitted state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submitted_state_adds_class() -> None:
    app = _WidgetApp(_make_widget(questions=_questions(2)))
    async with app.run_test() as pilot:
        await pilot.pause()
        w = pilot.app.query_one("#test-widget", StructuredAskUserWidget)
        w.action_confirm()
        w.action_confirm()
        assert w._submit_btn is not None
        w._submit_btn.press()
        await pilot.pause()
        w.action_confirm()
        await pilot.pause()
        assert w.has_class("is-submitted")


# ---------------------------------------------------------------------------
# Degraded mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_degraded_renders_free_text_inputs() -> None:
    app = _WidgetApp(_make_widget(questions=["Q1?", "Q2?"], degraded=True))
    async with app.run_test() as pilot:
        await pilot.pause()
        w = pilot.app.query_one("#test-widget", StructuredAskUserWidget)
        inputs = w.query(".saq-degraded-input")
        assert len(inputs) == 2
        assert w._degraded is True


@pytest.mark.asyncio
async def test_degraded_no_tab_bar() -> None:
    app = _WidgetApp(_make_widget(questions=["Q1?", "Q2?"], degraded=True))
    async with app.run_test() as pilot:
        await pilot.pause()
        w = pilot.app.query_one("#test-widget", StructuredAskUserWidget)
        tabs = w.query(".saq-tab")
        assert len(tabs) == 0


@pytest.mark.asyncio
async def test_degraded_no_option_rows() -> None:
    app = _WidgetApp(_make_widget(questions=["Q1?", "Q2?"], degraded=True))
    async with app.run_test() as pilot:
        await pilot.pause()
        w = pilot.app.query_one("#test-widget", StructuredAskUserWidget)
        opts = w.query(".saq-option-row")
        assert len(opts) == 0


# ---------------------------------------------------------------------------
# Answer text collection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_answer_text_returns_selected_option_label() -> None:
    app = _WidgetApp(_make_widget(questions=_questions(2)))
    async with app.run_test() as pilot:
        await pilot.pause()
        w = pilot.app.query_one("#test-widget", StructuredAskUserWidget)
        w.action_next_option()  # highlight 1 = API key
        w.action_confirm()
        assert w._answer_text(0) == "API key"


@pytest.mark.asyncio
async def test_answer_text_returns_custom_text() -> None:
    app = _WidgetApp(_make_widget(questions=_questions(2)))
    async with app.run_test() as pilot:
        await pilot.pause()
        w = pilot.app.query_one("#test-widget", StructuredAskUserWidget)
        w._selected[0] = 3
        w._custom_texts[0] = "My custom answer"
        assert w._answer_text(0) == "My custom answer"


# ---------------------------------------------------------------------------
# Empty-options fallback (structured mode with missing/malformed options)
# ---------------------------------------------------------------------------


def _question_dict_no_options(
    question: str = "What is your focus area?",
    header: str = "Focus",
) -> dict:
    """Question dict that passes the ``is_structured`` key-check but has no options."""
    return {
        "question": question,
        "header": header,
        "options": [],
    }


@pytest.mark.asyncio
async def test_empty_options_falls_back_to_custom_input() -> None:
    """When a structured question has an empty options list, the widget should
    enable the custom input immediately so the user can still answer."""
    app = _WidgetApp(
        _make_widget(
            questions=[
                _question_dict_no_options(),
                _question_dict_no_options(header="Priority", question="What priority?"),
            ],
        )
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        w = pilot.app.query_one("#test-widget", StructuredAskUserWidget)
        # No option rows should be rendered (only "Other:" + custom input).
        opt_rows = [r for r in w.query(".saq-option-row") if r.id != "saq-opt-custom"]
        assert len(opt_rows) == 0
        # Custom input should be enabled (not disabled).
        assert w._custom_input is not None
        assert w._custom_input.disabled is False
        # Highlighted should point at the custom row (index 0 when 0 options).
        assert w._highlighted == 0


@pytest.mark.asyncio
async def test_empty_options_allows_typing_and_submit() -> None:
    """User can type in the custom input and submit when options are empty."""
    app = _WidgetApp(_make_widget(questions=[_question_dict_no_options()]))
    async with app.run_test() as pilot:
        await pilot.pause()
        w = pilot.app.query_one("#test-widget", StructuredAskUserWidget)
        # Simulate typing in the custom input.
        assert w._custom_input is not None
        w._custom_input.value = "Security"
        # Directly set the internal state as if Enter selected the custom row.
        w._selected[0] = 3
        w._custom_texts[0] = "Security"
        w._update_option_highlight()
        w._update_tab_highlight()
        w._update_submit_state()
        assert w._all_answered is True
        assert w._answer_text(0) == "Security"


# ---------------------------------------------------------------------------
# App-level Submitted forwarding — answers must reach the daemon
# ---------------------------------------------------------------------------


class _FakeAdapter:
    """Minimal adapter stand-in for handler-forwarding tests."""

    def __init__(self) -> None:
        self._current_step_messages: dict = {}
        self._clarification_input_by_step: dict = {}
        self._clarification_answers_pending: list[str] | None = None
        self._clarification_pending = False


class _ForwardingHarness:
    """Minimal stand-in exercising the app-level Submitted handler."""

    def __init__(self) -> None:
        self._composer_mode = "ask"
        self._status_bar = None
        self._ui_adapter = _FakeAdapter()
        self.sent: list[str] = []

    async def _set_spinner(self, status: Any, **_kwargs: Any) -> None:  # noqa: ANN401
        pass

    async def _resolve_default_clarification_mode(self) -> str:
        return "auto"

    async def _send_to_agent(self, message: str, **_kwargs: Any) -> None:  # noqa: ANN401
        self.sent.append(message)


def _structured_event(answers: list[str]) -> StructuredAskUserWidget.Submitted:
    return StructuredAskUserWidget.Submitted(
        step_id="step-1",
        questions=[
            {
                "question": "What is your focus?",
                "header": "Focus",
                "options": [{"label": "Code", "description": "d"}],
            }
        ],
        answers=answers,
        widget_id="test-widget",
        origin_node="execute",
    )


@pytest.mark.asyncio
async def test_submitted_event_forwards_answers_to_agent() -> None:
    """Regression guard: the app must handle StructuredAskUserWidget.Submitted.

    Before this handler existed, submitting answers collapsed the widget but
    the message bubbled to nothing — the daemon never received the answers
    and the loop stayed parked in await_clarification forever (loop 328b).
    """
    from soothe_cli.tui.app._execution import _ExecutionMixin

    class _Harness(_ForwardingHarness, _ExecutionMixin):
        pass

    app = _Harness()
    event = _structured_event(["Code"])
    await app.on_structured_ask_user_widget_submitted(event)

    # The answers were handed to the turn pipeline with the resume flag set.
    assert app.sent, "answers must be forwarded via _send_to_agent"
    assert app._ui_adapter._clarification_pending is True
    assert app._ui_adapter._clarification_answers_pending == ["Code"]


@pytest.mark.asyncio
async def test_submitted_event_abandon_sends_nothing() -> None:
    """Abandon (empty answers) must not trigger a resume turn."""
    from soothe_cli.tui.app._execution import _ExecutionMixin

    class _Harness(_ForwardingHarness, _ExecutionMixin):
        pass

    app = _Harness()
    event = _structured_event([])
    await app.on_structured_ask_user_widget_submitted(event)

    assert app.sent == []
    assert app._ui_adapter._clarification_pending is False


# ---------------------------------------------------------------------------
# Focus on mount — keep focus on the widget, not the chat input
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_widget_has_focus_after_mount() -> None:
    """After the widget mounts, focus should be on the widget itself so
    arrow keys / Enter navigate the option picker immediately."""
    app = _WidgetApp(_make_widget())
    async with app.run_test() as pilot:
        await pilot.pause()
        w = pilot.app.query_one("#test-widget", StructuredAskUserWidget)
        assert pilot.app.focused is w


@pytest.mark.asyncio
async def test_options_render_in_stream_layout() -> None:
    """Regression guard: in the real app, widgets mount into a stream-layout
    container (#messages).  Vertical children defaulting to ``1fr`` collapse
    there — question body and option list must declare ``height: auto`` or
    the description/options render at zero height."""
    app = _StreamLayoutApp(_make_widget())
    async with app.run_test() as pilot:
        await pilot.pause()
        w = pilot.app.query_one("#test-widget", StructuredAskUserWidget)
        # Description and option rows must have non-zero height.
        desc = w.query_one("#saq-desc")
        assert desc.region.height == 1
        opt0 = w.query_one("#saq-opt-0")
        assert opt0.region.height == 1
        opt_custom = w.query_one("#saq-opt-custom")
        assert opt_custom.region.height == 1
