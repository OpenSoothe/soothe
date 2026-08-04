"""Tests for the app-level Shift+Tab composer-mode cycle (IG-682)."""

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
    """Minimal stand-in carrying the attributes `cycle_composer_mode` reads."""

    def __init__(self, *, initial: str = "auto") -> None:
        self._composer_mode = initial
        self._status_bar: Any = _FakeStatusBar()


def test_cycle_auto_to_manual() -> None:
    """First press takes the user from Auto to Manual."""
    app = _AppHarness(initial="auto")
    app.cycle_composer_mode()
    assert app._composer_mode == "manual"
    assert app._status_bar.last_mode == "manual"


def test_cycle_manual_to_plan() -> None:
    """Second press advances Manual to Plan."""
    app = _AppHarness(initial="manual")
    app.cycle_composer_mode()
    assert app._composer_mode == "plan"
    assert app._status_bar.last_mode == "plan"


def test_cycle_plan_back_to_auto() -> None:
    """Third press returns Plan to Auto."""
    app = _AppHarness(initial="plan")
    app.cycle_composer_mode()
    assert app._composer_mode == "auto"
    assert app._status_bar.last_mode == "auto"


def test_cycle_full_round_trip() -> None:
    """Three presses from Auto land back on Auto."""
    app = _AppHarness(initial="auto")
    app.cycle_composer_mode()
    app.cycle_composer_mode()
    app.cycle_composer_mode()
    assert app._composer_mode == "auto"
    assert app._status_bar.last_mode == "auto"


def test_cycle_tolerates_missing_status_bar() -> None:
    """Cycling before mount must not raise."""
    app = _AppHarness(initial="auto")
    app._status_bar = None
    app.cycle_composer_mode()
    assert app._composer_mode == "manual"


def test_cycle_treats_unknown_initial_value_as_auto() -> None:
    """A garbage starting value normalises to Auto on the first cycle."""
    app = _AppHarness(initial="garbage")
    app.cycle_composer_mode()
    assert app._composer_mode == "auto"
    app.cycle_composer_mode()
    assert app._composer_mode == "manual"


def test_shift_tab_action_cycles_mode() -> None:
    """``action_shift_tab`` advances the composer mode on the main screen."""
    app = _AppHarness(initial="auto")
    # Loop selector check imports LoopSelectorScreen; without a screen attr,
    # mimic main-screen path by calling cycle directly via the action after
    # stubbing screen as a non-selector object.
    app.screen = object()  # type: ignore[attr-defined]
    app.action_shift_tab()
    assert app._composer_mode == "manual"
