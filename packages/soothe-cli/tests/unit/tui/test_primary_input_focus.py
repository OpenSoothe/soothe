"""Tests for sole-input auto-focus behavior in the TUI."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static, TextArea

from soothe_cli.tui.app._messages_mixin import _MessagesMixin


class _FocusAppStub(_MessagesMixin):
    """Minimal app stub for primary-input focus helpers."""

    def __init__(self) -> None:
        self._ui_adapter: MagicMock | None = None
        self._chat_input = MagicMock()
        self.screen = MagicMock()
        self.screen.is_modal = False
        self.focused = None
        self.set_focus = MagicMock()
        self.call_after_refresh = MagicMock(side_effect=lambda fn: fn())
        self.set_timer = MagicMock()


class _ChatFocusHarnessApp(App[None]):
    """Minimal layout mirroring main-screen transcript + chat input."""

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="chat"):
            yield Static("transcript", id="transcript")
        yield TextArea(id="chat-input")

    async def on_mount(self) -> None:
        chat = self.query_one("#chat", VerticalScroll)
        chat.can_focus = False
        self.query_one("#chat-input", TextArea).focus()


@pytest.mark.asyncio
async def test_click_transcript_keeps_chat_input_focused() -> None:
    """Clicking outside the prompt must not leave the user unable to type."""
    async with _ChatFocusHarnessApp().run_test() as pilot:
        text_area = pilot.app.query_one("#chat-input", TextArea)
        assert text_area.has_focus

        await pilot.click("#transcript")
        await pilot.pause()

        assert text_area.has_focus
        assert pilot.app.focused is text_area


def test_primary_text_input_prefers_clarification_field() -> None:
    """Active clarification answer box wins over the bottom chat prompt."""
    clar_input = MagicMock()
    clar_input.disabled = False
    clar_message = MagicMock()
    clar_message._submitted = False
    clar_message._inputs = [clar_input]

    app = _FocusAppStub()
    app._ui_adapter = MagicMock()
    app._ui_adapter._clarification_input_by_step = {"step-1": clar_message}

    assert app._primary_text_input() is clar_input


def test_primary_text_input_returns_sole_non_chat_input() -> None:
    """A lone modal filter box is treated as the primary input."""
    sole_input = MagicMock()
    sole_input.can_focus = True
    sole_input.disabled = False

    app = _FocusAppStub()
    app.screen.query.return_value = [sole_input]

    assert app._primary_text_input() is sole_input


def test_primary_text_input_none_when_ambiguous() -> None:
    """Multiple non-chat inputs do not auto-focus."""
    first = MagicMock(can_focus=True, disabled=False)
    second = MagicMock(can_focus=True, disabled=False)

    app = _FocusAppStub()
    app.screen.query.return_value = [first, second]

    assert app._primary_text_input() is None


def test_focus_primary_input_falls_back_to_chat() -> None:
    """Idle main screen keeps focus on the chat prompt."""
    app = _FocusAppStub()
    app.screen.query.return_value = []

    app.focus_primary_input()

    app._chat_input.focus_input.assert_called_once()


def test_focus_primary_input_targets_clarification_input() -> None:
    """Clarification cards schedule focus on their answer field."""
    clar_input = MagicMock()
    clar_input.disabled = False
    clar_input.focus = MagicMock()
    clar_message = MagicMock()
    clar_message._submitted = False
    clar_message._inputs = [clar_input]

    app = _FocusAppStub()
    app._ui_adapter = MagicMock()
    app._ui_adapter._clarification_input_by_step = {"step-1": clar_message}

    app.focus_primary_input()

    app.set_focus.assert_called_once_with(clar_input)


def test_is_input_focused_includes_clarification_field() -> None:
    """Paste routing treats clarification inputs as focused text inputs."""
    clar_input = MagicMock()
    clar_input.disabled = False
    clar_input.walk_children.return_value = [clar_input]
    clar_message = MagicMock()
    clar_message._submitted = False
    clar_message._inputs = [clar_input]

    app = _FocusAppStub()
    app._ui_adapter = MagicMock()
    app._ui_adapter._clarification_input_by_step = {"step-1": clar_message}
    app.focused = clar_input

    assert app._is_input_focused() is True
