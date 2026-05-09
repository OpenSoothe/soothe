"""Tests for daemon behavior during TUI interrupt cleanup."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, PropertyMock

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
    daemon_session = MagicMock()
    daemon_session.cancel_remote_query = AsyncMock()
    daemon_session.detach = AsyncMock()
    daemon_session.aupdate_loop_state = AsyncMock()

    await _handle_interrupt_cleanup(
        adapter=adapter,
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


@pytest.mark.asyncio
async def test_interrupt_cleanup_daemon_uses_aupdate_loop_state() -> None:
    """Interrupt cleanup persists partial output via ``loop_state_update`` RPC."""
    adapter = TextualUIAdapter(
        mount_message=AsyncMock(),
        update_status=lambda _s: None,
        request_approval=AsyncMock(),
        set_spinner=AsyncMock(),
        set_active_message=MagicMock(),
    )
    daemon_session = MagicMock()
    daemon_session.cancel_remote_query = AsyncMock()
    daemon_session.aupdate_loop_state = AsyncMock()

    await _handle_interrupt_cleanup(
        adapter=adapter,
        config={"configurable": {"thread_id": "loop-daemon-1"}},
        daemon_session=daemon_session,
        pending_text_by_namespace={(): "partial answer"},
        captured_input_tokens=0,
        captured_output_tokens=0,
        turn_stats=SessionStats(),
        start_time=0.0,
    )

    assert daemon_session.aupdate_loop_state.await_count == 2
    for call in daemon_session.aupdate_loop_state.await_args_list:
        assert call.args[0] == "loop-daemon-1"
        values = call.args[1]
        assert "messages" in values
        assert isinstance(values["messages"], list)
        assert len(values["messages"]) == 1

    first_types = [
        m.get("type")
        for m in daemon_session.aupdate_loop_state.await_args_list[0].args[1]["messages"]
    ]
    second_types = [
        m.get("type")
        for m in daemon_session.aupdate_loop_state.await_args_list[1].args[1]["messages"]
    ]
    assert first_types == ["ai"]
    assert second_types == ["human"]


@pytest.mark.asyncio
async def test_interrupt_cleanup_daemon_falls_back_to_session_loop_id() -> None:
    """When ``thread_id`` is empty, resolve loop id from the daemon session."""
    adapter = TextualUIAdapter(
        mount_message=AsyncMock(),
        update_status=lambda _s: None,
        request_approval=AsyncMock(),
        set_spinner=AsyncMock(),
        set_active_message=MagicMock(),
    )
    daemon_session = MagicMock()
    daemon_session.cancel_remote_query = AsyncMock()
    daemon_session.aupdate_loop_state = AsyncMock()
    type(daemon_session).loop_id = PropertyMock(return_value="sess-loop-9")

    await _handle_interrupt_cleanup(
        adapter=adapter,
        config={"configurable": {"thread_id": ""}},
        daemon_session=daemon_session,
        pending_text_by_namespace={(): "x"},
        captured_input_tokens=0,
        captured_output_tokens=0,
        turn_stats=SessionStats(),
        start_time=0.0,
    )

    assert daemon_session.aupdate_loop_state.await_count >= 1
    assert daemon_session.aupdate_loop_state.await_args_list[0].args[0] == "sess-loop-9"
