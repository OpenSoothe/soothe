"""Tests for daemon behavior during TUI interrupt cleanup."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe_cli.tui._session_stats import SessionStats
from soothe_cli.tui.textual_adapter import TextualUIAdapter, _handle_interrupt_cleanup


@pytest.mark.asyncio
async def test_interrupt_cleanup_cancels_remote_query_not_detach() -> None:
    """Ctrl+C / worker cancel must stop the daemon job, not detach it."""
    adapter = TextualUIAdapter(
        mount_message=AsyncMock(),
        update_status=lambda _s: None,
        request_approval=AsyncMock(),
        set_spinner=AsyncMock(),
        set_active_message=MagicMock(),
    )
    agent = MagicMock()
    agent.aupdate_state = AsyncMock()

    daemon_session = MagicMock()
    daemon_session.cancel_remote_query = AsyncMock()
    daemon_session.detach = AsyncMock()

    await _handle_interrupt_cleanup(
        adapter=adapter,
        agent=agent,
        config={"configurable": {"thread_id": "t1"}},
        daemon_session=daemon_session,
        pending_text_by_namespace={},
        captured_input_tokens=0,
        captured_output_tokens=0,
        turn_stats=SessionStats(),
        start_time=0.0,
    )

    daemon_session.cancel_remote_query.assert_awaited_once()
    daemon_session.detach.assert_not_called()
