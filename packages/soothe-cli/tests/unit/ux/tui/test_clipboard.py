"""Tests for TUI clipboard copy helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from soothe_cli.tui.widgets.clipboard import (
    _clipboard_copy_methods,
    _collect_selected_texts,
    _copy_native,
    _copy_osc52,
    _copy_texts_to_clipboard,
    _selected_text_from_screen,
    clear_widget_text_selection,
    copy_selection_to_clipboard,
    screen_has_text_selection,
)


def test_screen_has_text_selection_uses_selections_not_extract() -> None:
    """Click guards must not call get_selected_text (stale offsets can raise)."""
    screen = MagicMock()
    screen.selections = {MagicMock(): MagicMock()}
    screen.get_selected_text.side_effect = IndexError("list index out of range")

    assert screen_has_text_selection(screen) is True
    screen.get_selected_text.assert_not_called()


def test_selected_text_from_screen_tolerates_index_error() -> None:
    app = MagicMock()
    app.screen.get_selected_text.side_effect = IndexError("list index out of range")

    assert _selected_text_from_screen(app) is None


def test_clear_widget_text_selection_removes_widget_entry() -> None:
    widget = MagicMock()
    other = MagicMock()
    screen = MagicMock()
    widget.screen = screen
    screen.selections = {widget: MagicMock(), other: MagicMock()}

    clear_widget_text_selection(widget)

    assert widget not in screen.selections
    assert other in screen.selections


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


def test_clipboard_methods_use_osc52_before_textual_in_tmux(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unwrapped Textual OSC 52 must not run before tmux-wrapped /dev/tty copy."""
    monkeypatch.setenv("TMUX", "/tmp/tmux-123/default,12345,0")
    app = MagicMock()

    methods = _clipboard_copy_methods(app)

    assert _copy_native in methods
    assert _copy_osc52 in methods
    assert app.copy_to_clipboard not in methods
    native_idx = methods.index(_copy_native)
    osc52_idx = methods.index(_copy_osc52)
    assert native_idx < osc52_idx


def test_clipboard_methods_use_textual_before_osc52_locally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Local sessions prefer native then Textual's driver, with OSC 52 as fallback."""
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("SSH_CONNECTION", raising=False)
    app = MagicMock()

    methods = _clipboard_copy_methods(app)

    assert _copy_native in methods
    assert methods[-1] is _copy_osc52
    native_idx = methods.index(_copy_native)
    textual_idx = methods.index(app.copy_to_clipboard)
    assert native_idx < textual_idx


def test_copy_in_tmux_calls_native_then_osc52_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end copy: native clipboard is preferred; OSC 52 is tmux fallback."""
    monkeypatch.setenv("TMUX", "/tmp/tmux-123/default,12345,0")
    app = MagicMock()
    native_mock = MagicMock()
    monkeypatch.setattr(
        "soothe_cli.tui.widgets.clipboard._copy_native",
        native_mock,
    )

    _copy_texts_to_clipboard(app, ["hello"])

    native_mock.assert_called_once_with("hello")
    app.copy_to_clipboard.assert_not_called()
    app.notify.assert_called_once()


def test_copy_falls_through_to_osc52_when_native_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When native clipboard fails, OSC 52 is the next fallback."""
    monkeypatch.setenv("TMUX", "/tmp/tmux-123/default,12345,0")
    app = MagicMock()
    native_mock = MagicMock(side_effect=RuntimeError("no pbcopy"))
    osc52_mock = MagicMock()
    monkeypatch.setattr(
        "soothe_cli.tui.widgets.clipboard._copy_native",
        native_mock,
    )
    monkeypatch.setattr(
        "soothe_cli.tui.widgets.clipboard._copy_osc52",
        osc52_mock,
    )

    _copy_texts_to_clipboard(app, ["hello"])

    native_mock.assert_called_once_with("hello")
    osc52_mock.assert_called_once_with("hello")
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
