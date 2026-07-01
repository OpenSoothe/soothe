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
