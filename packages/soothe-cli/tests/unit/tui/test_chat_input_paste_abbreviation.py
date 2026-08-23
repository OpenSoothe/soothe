"""Widget tests for abbreviated paste display in ChatInput."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from soothe_cli.tui.widgets.chat_input import ChatInput


@pytest.fixture
def chat_input() -> ChatInput:
    widget = ChatInput()
    text_area = MagicMock()
    text_area.text = ""
    text_area.selection.is_empty = True
    text_area.selection.end = None
    widget._text_area = text_area
    widget._get_cursor_offset = MagicMock(return_value=0)  # type: ignore[method-assign]
    return widget


def test_apply_abbreviated_paste_shows_token_and_stores_full_text(chat_input: ChatInput) -> None:
    pasted = "line one\nline two\nline three\nline four\nline five"
    chat_input._apply_abbreviated_paste_display(pasted)

    assert chat_input._text_area.text == "[Pasted text #1 +4 lines]"
    assert chat_input._pending_submit_text == pasted


def test_second_paste_composes_full_text_not_display_token(chat_input: ChatInput) -> None:
    first = "alpha\nbeta\ngamma\ndelta\nepsilon"
    second = "one\ntwo\nthree\nfour\nfive"

    chat_input._apply_abbreviated_paste_display(first)
    chat_input._text_area.text = "[Pasted text #1 +4 lines]"
    chat_input._get_cursor_offset.return_value = len(chat_input._text_area.text)

    chat_input._apply_abbreviated_paste_display(second)

    assert chat_input._text_area.text == "[Pasted text #1 +4 lines][Pasted text #2 +4 lines]"
    assert chat_input._pending_submit_text == f"{first}{second}"


def test_resolve_submit_text_returns_full_payload_when_abbreviated(chat_input: ChatInput) -> None:
    pasted = "a\nb\nc\nd\ne"
    chat_input._apply_abbreviated_paste_display(pasted)

    submitted = chat_input._resolve_submit_text(chat_input._text_area.text)

    assert submitted == pasted
