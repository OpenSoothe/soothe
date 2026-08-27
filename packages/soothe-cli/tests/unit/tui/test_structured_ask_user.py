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
    title: str = "Auth method",
    description: str = "How should the API authenticate requests?",
    recommended: int = 0,
) -> dict:
    return {
        "title": title,
        "description": description,
        "options": [
            {"short": "OAuth", "long": "OAuth 2.0 with PKCE. Best for browser flows."},
            {"short": "API key", "long": "Static API key in a header. Simplest to implement."},
            {"short": "Session", "long": "Server-side session with cookies. Best for SSR apps."},
        ],
        "recommended": recommended,
    }


def _questions(n: int = 2) -> list[dict]:
    titles = ["Auth method", "Token store", "Retry policy", "Cache layer", "Log level"]
    return [_question_dict(title=titles[i], description=f"Question {i + 1} desc") for i in range(n)]


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


class _WidgetApp(App[None]):
    """Minimal harness mounting a single StructuredAskUserWidget."""

    def __init__(self, widget: StructuredAskUserWidget) -> None:
        super().__init__()
        self._widget = widget

    def compose(self) -> ComposeResult:
        yield self._widget


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
async def test_structured_compose_renders_4_option_rows() -> None:
    app = _WidgetApp(_make_widget())
    async with app.run_test() as pilot:
        await pilot.pause()
        w = pilot.app.query_one("#test-widget", StructuredAskUserWidget)
        opts = w.query(".saq-option-row")
        assert len(opts) == 4


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
        assert w._highlighted == 3
        w.action_next_option()
        assert w._highlighted == 0


@pytest.mark.asyncio
async def test_prev_option_cycles_highlight() -> None:
    app = _WidgetApp(_make_widget())
    async with app.run_test() as pilot:
        await pilot.pause()
        w = pilot.app.query_one("#test-widget", StructuredAskUserWidget)
        w.action_prev_option()
        assert w._highlighted == 3
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
        w.action_next_option()
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


@pytest.mark.asyncio
async def test_custom_empty_hint_shown_when_custom_highlighted() -> None:
    """§9c.7: highlighting the custom row with no text shows the hint."""
    from textual.widgets import Static

    app = _WidgetApp(_make_widget())
    async with app.run_test() as pilot:
        await pilot.pause()
        w = pilot.app.query_one("#test-widget", StructuredAskUserWidget)
        # Navigate to custom row
        w.action_next_option()
        w.action_next_option()
        w.action_next_option()
        assert w._highlighted == 3
        hint = w.query_one("#saq-custom-hint", Static)
        assert hint.has_class("is-visible")


@pytest.mark.asyncio
async def test_custom_empty_hint_hidden_when_custom_not_highlighted() -> None:
    """§9c.7: hint is hidden when a non-custom option is highlighted."""
    from textual.widgets import Static

    app = _WidgetApp(_make_widget())
    async with app.run_test() as pilot:
        await pilot.pause()
        w = pilot.app.query_one("#test-widget", StructuredAskUserWidget)
        assert w._highlighted == 0
        hint = w.query_one("#saq-custom-hint", Static)
        assert not hint.has_class("is-visible")


# ---------------------------------------------------------------------------
# Tab footer focus
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tab_moves_focus_to_footer_submit() -> None:
    """§9c.5: Tab cycles focus from question area to footer (Submit first)."""
    app = _WidgetApp(_make_widget())
    async with app.run_test() as pilot:
        await pilot.pause()
        w = pilot.app.query_one("#test-widget", StructuredAskUserWidget)
        assert w._footer_focused is False
        w.action_focus_footer()
        await pilot.pause()
        assert w._footer_focused is True


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
async def test_answer_text_returns_selected_option_short() -> None:
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
