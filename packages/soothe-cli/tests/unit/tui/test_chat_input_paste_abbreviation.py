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
    assert chat_input._pending_paste_texts == {"[Pasted text #1 +4 lines]": pasted}


def test_second_paste_composes_full_text_not_display_token(chat_input: ChatInput) -> None:
    first = "alpha\nbeta\ngamma\ndelta\nepsilon"
    second = "one\ntwo\nthree\nfour\nfive"

    chat_input._apply_abbreviated_paste_display(first)
    chat_input._text_area.text = "[Pasted text #1 +4 lines]"
    chat_input._get_cursor_offset.return_value = len(chat_input._text_area.text)

    chat_input._apply_abbreviated_paste_display(second)

    assert chat_input._text_area.text == "[Pasted text #1 +4 lines][Pasted text #2 +4 lines]"
    assert chat_input._pending_paste_texts == {
        "[Pasted text #1 +4 lines]": first,
        "[Pasted text #2 +4 lines]": second,
    }
    assert chat_input._resolve_submit_text(chat_input._text_area.text) == f"{first}{second}"


def test_resolve_submit_text_returns_full_payload_when_abbreviated(chat_input: ChatInput) -> None:
    pasted = "a\nb\nc\nd\ne"
    chat_input._apply_abbreviated_paste_display(pasted)

    submitted = chat_input._resolve_submit_text(chat_input._text_area.text)

    assert submitted == pasted


def test_edit_after_paste_preserves_full_text(chat_input: ChatInput) -> None:
    """Typing after a paste must not drop the full pasted payload (regression)."""
    pasted = "line one\nline two\nline three\nline four\nline five"
    chat_input._apply_abbreviated_paste_display(pasted)

    display = chat_input._text_area.text + " please review"
    submitted = chat_input._resolve_submit_text(display)

    assert submitted == f"{pasted} please review"


def test_removing_token_drops_paste(chat_input: ChatInput) -> None:
    """Deleting the abbreviation token removes the paste instead of expanding it."""
    pasted = "line one\nline two\nline three\nline four\nline five"
    chat_input._apply_abbreviated_paste_display(pasted)

    submitted = chat_input._resolve_submit_text("")

    assert submitted == ""


def test_modified_token_does_not_expand(chat_input: ChatInput) -> None:
    """A token the user edited inside no longer expands to the stale payload."""
    pasted = "line one\nline two\nline three\nline four\nline five"
    chat_input._apply_abbreviated_paste_display(pasted)

    display = chat_input._text_area.text.replace("+4", "+5")
    submitted = chat_input._resolve_submit_text(display)

    assert submitted == "[Pasted text #1 +5 lines]"
