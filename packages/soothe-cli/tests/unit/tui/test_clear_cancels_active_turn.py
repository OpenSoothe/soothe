"""Tests for /clear cancelling an in-flight daemon turn before loop switch."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from textual.css.query import NoMatches


@pytest.mark.asyncio
async def test_clear_cancels_agent_before_new_loop() -> None:
    """IG-533: /clear must cancel synthesis on the old loop before switching loop_id."""
    from soothe_cli.tui.app._execution import _ExecutionMixin

    app = object.__new__(_ExecutionMixin)
    app._pending_messages = []
    app._queued_widgets = []
    app._context_tokens = 0
    app._tokens_approximate = False
    app._session_state = MagicMock(loop_id="old-loop")
    app._daemon_session = AsyncMock()
    app._daemon_session.new_loop = AsyncMock(
        return_value={"loop_id": "new-loop", "autopilot_mode": "solo"}
    )
    app._agent_running = True
    app._agent_worker = AsyncMock()
    app._agent_worker.wait = AsyncMock()
    app._interrupt_daemon_agent_turn = AsyncMock()
    app._cleanup_agent_task = AsyncMock()
    app._clear_messages = AsyncMock()
    app._update_status = MagicMock()
    app._update_tokens = MagicMock()
    app._lc_loop_id = "old-loop"
    app._clear_loop_model_override = MagicMock()
    app._mount_message = AsyncMock()
    app.query_one = MagicMock(side_effect=NoMatches())

    with patch("soothe_cli.tui.app._execution.asyncio.wait_for", new=AsyncMock()):
        await app._handle_command("/clear")

    app._interrupt_daemon_agent_turn.assert_awaited_once()
    app._cleanup_agent_task.assert_awaited_once()
    app._daemon_session.new_loop.assert_awaited_once()
    assert app._session_state.loop_id == "new-loop"
