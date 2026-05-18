"""Tests for TUI clipboard copy helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from soothe_cli.tui.widgets.clipboard import (
    _collect_selected_texts,
    copy_selection_to_clipboard,
)


def test_copy_uses_screen_get_selected_text() -> None:
    """Screen-level selection API is preferred over per-widget scans."""
    app = MagicMock()
    app.screen.get_selected_text.return_value = "hello world"
    app.query.return_value = []

    assert _collect_selected_texts(app) == ["hello world"]


def test_copy_returns_false_when_empty() -> None:
    """No notification unless explicitly requested."""
    app = MagicMock()
    app.screen.get_selected_text.return_value = None
    app.query.return_value = []

    assert copy_selection_to_clipboard(app) is False
    app.notify.assert_not_called()


def test_copy_notifies_when_empty_and_requested() -> None:
    app = MagicMock()
    app.screen.get_selected_text.return_value = None
    app.query.return_value = []

    assert copy_selection_to_clipboard(app, notify_if_empty=True) is False
    app.notify.assert_called_once()


def test_text_selected_copies_synchronously_not_after_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Copy must run in on_text_selected before Click handlers clear selection."""
    from textual.events import TextSelected

    from soothe_cli.tui.app._messages_mixin import _MessagesMixin

    copy_mock = MagicMock(return_value=True)

    class _AppStub(_MessagesMixin):
        def __init__(self) -> None:
            self.screen = MagicMock()
            self.screen.get_selected_text.return_value = "selected text"
            self.call_after_refresh = MagicMock()

    monkeypatch.setattr(
        "soothe_cli.tui.widgets.clipboard.copy_selection_to_clipboard",
        copy_mock,
    )
    app = _AppStub()
    app.on_text_selected(TextSelected())

    app.call_after_refresh.assert_not_called()
    copy_mock.assert_called_once_with(app)
