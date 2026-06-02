"""Tests for the app-level Shift+Tab clarification-mode toggle (RFC-622)."""

from __future__ import annotations

from typing import Any

from soothe_cli.tui.app._messages_mixin import _MessagesMixin


class _FakeStatusBar:
    """Captures the last `set_clarification_mode` call for assertions."""

    def __init__(self) -> None:
        self.last_mode: str | None = None

    def set_clarification_mode(self, mode: str) -> None:
        self.last_mode = mode


class _AppHarness(_MessagesMixin):
    """Minimal stand-in carrying the attributes `toggle_clarification_mode` reads."""

    def __init__(self, *, initial: str = "auto") -> None:
        self._clarification_mode = initial
        self._status_bar: Any = _FakeStatusBar()


def test_toggle_flips_auto_to_manual() -> None:
    """First press of Shift+Tab takes the user from Auto to Manual."""
    app = _AppHarness(initial="auto")
    app.toggle_clarification_mode()
    assert app._clarification_mode == "manual"
    assert app._status_bar.last_mode == "manual"


def test_toggle_flips_manual_back_to_auto() -> None:
    """Two presses bring the user back to the Auto default."""
    app = _AppHarness(initial="auto")
    app.toggle_clarification_mode()
    app.toggle_clarification_mode()
    assert app._clarification_mode == "auto"
    assert app._status_bar.last_mode == "auto"


def test_toggle_tolerates_missing_status_bar() -> None:
    """Pressing the toggle before mount must not raise."""
    app = _AppHarness(initial="auto")
    app._status_bar = None
    app.toggle_clarification_mode()
    assert app._clarification_mode == "manual"


def test_toggle_treats_unknown_initial_value_as_auto() -> None:
    """A garbage starting value normalises to Auto on the first flip."""
    app = _AppHarness(initial="garbage")
    app.toggle_clarification_mode()
    # Toggle only treats "auto" specially, so an unknown value lands on Auto
    # first; one more press confirms the predictable two-step cycle.
    assert app._clarification_mode == "auto"
    app.toggle_clarification_mode()
    assert app._clarification_mode == "manual"
