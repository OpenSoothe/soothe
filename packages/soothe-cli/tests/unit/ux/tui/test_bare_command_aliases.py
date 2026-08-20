"""Tests for bare plain-text command aliases (e.g. ``clear`` -> ``/clear``).

Mirrors the bare-quit test pattern: single-word normal-mode input is rewritten
to its canonical slash command before routing so the same queueing and
loop-switch guards apply.
"""

from __future__ import annotations

from collections import deque
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe_cli.tui.app._execution import _ExecutionMixin
from soothe_cli.tui.widgets.chat_input import ChatInput


class _SubmitAliasStub(_ExecutionMixin):
    """Minimal execution stub for bare-command-alias submission."""

    def __init__(self) -> None:
        self._loop_switching = False
        self._agent_running = False
        self._shell_running = False
        self._connecting = False
        self._pending_messages = deque()
        self._queued_widgets = deque()
        self._detach_or_exit = MagicMock()
        self._process_message = AsyncMock()


@pytest.mark.asyncio
@pytest.mark.parametrize("word", ["clear", "Clear", " CLEAR ", "claer", "clera", "cleer"])
async def test_bare_clear_is_routed_as_slash_clear(word: str) -> None:
    """Plain-text ``clear`` in normal mode must be rewritten to ``/clear``."""
    app = _SubmitAliasStub()
    event = ChatInput.Submitted(word, mode="normal")

    await app.on_chat_input_submitted(event)

    app._detach_or_exit.assert_not_called()
    app._process_message.assert_awaited_once()
    routed_value, routed_mode = app._process_message.await_args.args
    assert routed_value == "/clear"
    assert routed_mode == "command"


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["clear history", "please clear", "clearer"])
async def test_non_exact_clear_text_is_not_rewritten(text: str) -> None:
    """Only exact single-word ``clear`` should be rewritten to ``/clear``."""
    app = _SubmitAliasStub()
    event = ChatInput.Submitted(text, mode="normal")

    await app.on_chat_input_submitted(event)

    app._process_message.assert_awaited_once()
    routed_value, routed_mode = app._process_message.await_args.args
    assert routed_value == text
    assert routed_mode == "normal"


@pytest.mark.asyncio
async def test_slash_clear_in_command_mode_is_unaffected() -> None:
    """``/clear`` typed in command mode must keep its original value/mode."""
    app = _SubmitAliasStub()
    event = ChatInput.Submitted("/clear", mode="command")

    await app.on_chat_input_submitted(event)

    app._process_message.assert_awaited_once()
    routed_value, routed_mode = app._process_message.await_args.args
    assert routed_value == "/clear"
    assert routed_mode == "command"


def test_bare_command_aliases_registry_maps_clear() -> None:
    from soothe_cli.tui.command_registry import BARE_COMMAND_ALIASES

    assert BARE_COMMAND_ALIASES["clear"] == "/clear"
    assert BARE_COMMAND_ALIASES["claer"] == "/clear"
    assert BARE_COMMAND_ALIASES["clera"] == "/clear"
