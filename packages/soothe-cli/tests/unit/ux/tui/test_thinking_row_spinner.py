"""Thinking-row spinner helpers and LoadingWidget pause/resume."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe_cli.tui.textual_adapter import (
    SPINNER_LABEL_RUNNING_TOOLS,
    SPINNER_LABEL_THINKING,
    TextualUIAdapter,
    _format_retry_spinner_label,
    _maybe_set_running_tools_spinner,
    _maybe_set_thinking_spinner,
)
from soothe_cli.tui.widgets.loading import LoadingWidget


def test_format_retry_spinner_label_with_counts() -> None:
    assert _format_retry_spinner_label(2, 3) == "Retrying (2/3)"


def test_format_retry_spinner_label_fallback() -> None:
    assert _format_retry_spinner_label(0, 0) == "Retrying"


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
    adapter._set_spinner.assert_awaited_once_with(SPINNER_LABEL_RUNNING_TOOLS)


def test_loading_widget_activate_status_clears_pause() -> None:
    widget = LoadingWidget("Thinking")
    widget.pause("Awaiting your answer")
    assert widget._paused is True
    widget.activate_status("Executing step")
    assert widget._paused is False
    assert widget._status == "Executing step"


def test_loading_widget_startup_mode_omits_interrupt_hint() -> None:
    widget = LoadingWidget("Connecting to daemon", show_interrupt_hint=False)
    assert widget._show_interrupt_hint is False
    widget.activate_status("Waiting for agent to be ready", show_interrupt_hint=False)
    assert widget._show_interrupt_hint is False
    assert widget._format_status_line("Connecting to daemon") == " Connecting to daemon... "
    assert widget._format_hint_line(12.0, include_interrupt=False) == "(12s)"
    assert widget._format_hint_line(12.0, include_interrupt=True) == "(12s · esc to interrupt)"


def test_loading_widget_startup_mode_still_shows_elapsed() -> None:
    widget = LoadingWidget("Waiting for agent to be ready", show_interrupt_hint=False)
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
        widget = LoadingWidget("Waiting for agent to be ready", show_interrupt_hint=False)
        await container.mount(widget)
        await pilot.pause()
        assert widget._animation_timer is not None
        widget._stop_timer()
        widget.activate_status("Connecting to daemon", show_interrupt_hint=False)
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
        widget = LoadingWidget("Waiting for agent to be ready", show_interrupt_hint=False)
        await container.mount(widget)
        await pilot.pause(1.1)
        elapsed_before = int(widget._elapsed_seconds())
        widget.activate_status("Connecting to daemon", show_interrupt_hint=False)
        await pilot.pause(1.1)
        elapsed_after = int(widget._elapsed_seconds())
        assert elapsed_before >= 1
        assert elapsed_after >= elapsed_before + 1
        assert widget._format_hint_line(float(elapsed_after), include_interrupt=False) == (
            f"({elapsed_after}s)"
        )
