"""Tests for per-loop accumulated token usage in the TUI."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from soothe_cli.tui.app._ui import _UIMixin


class _TokenApp(_UIMixin):
    """Minimal host object for _UIMixin token helpers."""

    def __init__(self) -> None:
        self._lc_loop_id = "loop-a"
        self._context_tokens = 0
        self._loop_token_scope_id = None
        self._loop_baseline_tokens = 0
        self._loop_input_tokens = 0
        self._loop_output_tokens = 0
        self._tokens_approximate = False
        self._inflight_turn_stats = None
        self._loading_widget = None
        self._status_bar = SimpleNamespace(
            set_tokens=lambda count, approximate=False: None,
            hide_tokens=lambda: None,
        )


def test_record_loop_turn_tokens_accumulates_within_loop() -> None:
    app = _TokenApp()

    app._record_loop_turn_tokens(100, 50)
    assert app._loop_token_total() == 150
    assert app._context_tokens == 150

    app._record_loop_turn_tokens(200, 25)
    assert app._loop_token_total() == 375
    assert app._context_tokens == 375


def test_reset_loop_token_usage_clears_on_loop_change() -> None:
    app = _TokenApp()
    app._record_loop_turn_tokens(1000, 500)
    app._reset_loop_token_usage("loop-b")

    assert app._loop_token_scope_id == "loop-b"
    assert app._loop_token_total() == 0
    assert app._context_tokens == 0


def test_seed_loop_token_baseline_then_accumulate() -> None:
    app = _TokenApp()
    app._lc_loop_id = "loop-resumed"
    app._seed_loop_token_baseline("loop-resumed", 900)

    assert app._loop_token_total() == 900

    app._record_loop_turn_tokens(100, 50)
    assert app._loop_token_total() == 1050


def test_ensure_loop_token_scope_resets_when_loop_id_changes() -> None:
    app = _TokenApp()
    app._record_loop_turn_tokens(300, 100)
    app._lc_loop_id = "loop-b"
    app._record_loop_turn_tokens(10, 5)

    assert app._loop_token_scope_id == "loop-b"
    assert app._loop_token_total() == 15


def test_refresh_token_displays_updates_thinking_row() -> None:
    app = _TokenApp()
    loading = SimpleNamespace(set_token_usage=MagicMock())
    app._loading_widget = loading
    app._loop_input_tokens = 500
    app._loop_output_tokens = 250

    app._refresh_token_displays()

    loading.set_token_usage.assert_called_once_with(750, approximate=False)


def test_apply_authoritative_loop_tokens_merges_backend_goal_total() -> None:
    app = _TokenApp()
    app._seed_loop_token_baseline("loop-a", 1000)
    app._record_loop_turn_tokens(100, 50)

    app._apply_authoritative_loop_tokens(500)

    assert app._loop_token_total() == 1500
    assert app._loop_output_tokens == 500
    assert app._loop_input_tokens == 0
