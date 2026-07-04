"""Thinking-row spinner helpers and LoadingWidget pause/resume."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe_cli.tui.spinner_labels import (
    SPINNER_LABEL_INPUT,
    SPINNER_LABEL_THINKING,
    SPINNER_LABEL_TOOLS,
    daemon_connect_hint_extra,
    map_plan_phase_spinner_label,
    retry_spinner_hint,
)
from soothe_cli.tui.textual_adapter import (
    TextualUIAdapter,
    _maybe_set_running_tools_spinner,
    _maybe_set_thinking_spinner,
)
from soothe_cli.tui.widgets.loading import LoadingWidget


def test_map_plan_phase_spinner_label_known() -> None:
    assert map_plan_phase_spinner_label("Generating plan") == "Planning"
    assert map_plan_phase_spinner_label("Assessing continuation context") == "Assessing"


def test_map_plan_phase_spinner_label_unknown_falls_back_to_thinking() -> None:
    assert map_plan_phase_spinner_label("Unknown phase") == SPINNER_LABEL_THINKING


def test_retry_spinner_hint_with_counts() -> None:
    assert retry_spinner_hint(attempt=2, max_attempts=3) == "2/3"


def test_retry_spinner_hint_without_counts() -> None:
    assert retry_spinner_hint(attempt=0, max_attempts=0) is None


def test_daemon_connect_hint_extra_first_attempt() -> None:
    assert daemon_connect_hint_extra(attempt=1, max_attempts=3) is None


def test_daemon_connect_hint_extra_retry() -> None:
    assert daemon_connect_hint_extra(attempt=2, max_attempts=3) == "attempt 2/3"


@pytest.mark.asyncio
async def test_maybe_set_thinking_spinner_skips_during_clarification() -> None:
    adapter = TextualUIAdapter(MagicMock(), MagicMock(), set_spinner=AsyncMock())
    adapter._clarification_pending = True
    await _maybe_set_thinking_spinner(adapter)
    adapter._set_spinner.assert_not_called()


@pytest.mark.asyncio
async def test_maybe_set_thinking_spinner_when_idle() -> None:
    adapter = TextualUIAdapter(MagicMock(), MagicMock(), set_spinner=AsyncMock())
    await _maybe_set_thinking_spinner(adapter)
    adapter._set_spinner.assert_awaited_once_with(SPINNER_LABEL_THINKING)


@pytest.mark.asyncio
async def test_maybe_set_running_tools_spinner_when_tools_pending() -> None:
    adapter = TextualUIAdapter(MagicMock(), MagicMock(), set_spinner=AsyncMock())
    adapter._tool_to_step["tc-1"] = MagicMock()
    await _maybe_set_running_tools_spinner(adapter)
    adapter._set_spinner.assert_awaited_once_with(SPINNER_LABEL_TOOLS)


def test_loading_widget_activate_status_clears_pause() -> None:
    widget = LoadingWidget("Thinking")
    widget.pause(SPINNER_LABEL_INPUT)
    assert widget._paused is True
    widget.activate_status("Executing")
    assert widget._paused is False
    assert widget._status == "Executing"


def test_loading_widget_hint_extra_includes_attempt_and_elapsed() -> None:
    widget = LoadingWidget("Connecting", hint_extra="attempt 2/3")
    assert widget._format_hint_line(15.0) == "(attempt 2/3 · 15s)"


def test_loading_widget_default_omits_interrupt_hint() -> None:
    """Task spinners show elapsed time only (no esc hint)."""
    widget = LoadingWidget("Thinking")
    assert widget._show_interrupt_hint is False
    assert widget._format_hint_line(12.0) == "(12s)"


def test_loading_widget_startup_mode_omits_interrupt_hint() -> None:
    widget = LoadingWidget("Waiting", show_interrupt_hint=False)
    assert widget._show_interrupt_hint is False
    widget.activate_status("Connecting", show_interrupt_hint=False)
    assert widget._show_interrupt_hint is False
    assert widget._format_status_line("Connecting") == " Connecting... "
    assert widget._format_hint_line(12.0, include_interrupt=False) == "(12s)"
    assert widget._format_hint_line(12.0, include_interrupt=True) == "(12s · esc to interrupt)"


def test_loading_widget_resume_restores_pre_pause_label() -> None:
    widget = LoadingWidget("Executing")
    widget.pause(SPINNER_LABEL_INPUT)
    assert widget._status == SPINNER_LABEL_INPUT
    widget.resume()
    assert widget._status == "Executing"
    assert widget._paused is False


def test_loading_widget_startup_mode_still_shows_elapsed() -> None:
    widget = LoadingWidget("Waiting", show_interrupt_hint=False)
    widget._turn_start_mono = 100.0
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("soothe_cli.tui.widgets.loading.monotonic", lambda: 112.5)
        assert widget._elapsed_seconds() == 12.0
        hint = widget._format_hint_line(widget._elapsed_seconds(), include_interrupt=False)
    assert hint == "(12s)"


@pytest.mark.asyncio
async def test_loading_widget_activate_status_restarts_stopped_timer() -> None:
    from textual.app import App, ComposeResult
    from textual.containers import Container

    class _Harness(App[None]):
        def compose(self) -> ComposeResult:
            yield Container(id="thinking-status")

    app = _Harness()
    async with app.run_test() as pilot:
        container = app.query_one("#thinking-status", Container)
        widget = LoadingWidget("Waiting", show_interrupt_hint=False)
        await container.mount(widget)
        await pilot.pause()
        assert widget._animation_timer is not None
        widget._stop_timer()
        widget.activate_status("Connecting", show_interrupt_hint=False)
        assert widget._animation_timer is not None
        await pilot.pause(1.1)
        assert int(widget._elapsed_seconds()) >= 1


@pytest.mark.asyncio
async def test_loading_widget_elapsed_ticks_after_connect_status_change() -> None:
    """Daemon connect updates the label without freezing the elapsed-time counter."""
    from textual.app import App, ComposeResult
    from textual.containers import Container

    class _Harness(App[None]):
        def compose(self) -> ComposeResult:
            yield Container(id="thinking-status")

    app = _Harness()
    async with app.run_test() as pilot:
        container = app.query_one("#thinking-status", Container)
        widget = LoadingWidget("Waiting", show_interrupt_hint=False)
        await container.mount(widget)
        await pilot.pause(1.1)
        elapsed_before = int(widget._elapsed_seconds())
        widget.activate_status("Connecting", show_interrupt_hint=False, hint_extra="attempt 2/3")
        await pilot.pause(1.1)
        elapsed_after = int(widget._elapsed_seconds())
        assert elapsed_before >= 1
        assert elapsed_after >= elapsed_before + 1
        assert widget._format_hint_line(float(elapsed_after), include_interrupt=False) == (
            f"(attempt 2/3 · {elapsed_after}s)"
        )
