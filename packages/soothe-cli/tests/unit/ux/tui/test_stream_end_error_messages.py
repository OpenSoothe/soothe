"""Tests for stream-end error labels (IG-533 §4.3)."""

from __future__ import annotations

from unittest.mock import MagicMock

from soothe_cli.tui.textual_adapter import TextualUIAdapter, _stream_end_pending_error_message


def test_stream_end_worker_thread_lost_message() -> None:
    adapter = TextualUIAdapter(mount_message=MagicMock(), update_status=MagicMock())
    session = MagicMock()
    session.last_turn_cancellation_seen = False
    session.last_turn_end_state = "idle"
    session.last_turn_error_message = (
        "Worker thread exited unexpectedly during query execution; check daemon logs."
    )
    adapter._current_step_messages = {"s1": MagicMock(_status="running")}

    msg = _stream_end_pending_error_message(adapter, session)

    assert msg == "Worker stopped during stream"


def test_stream_end_cancelled_message() -> None:
    adapter = TextualUIAdapter(mount_message=MagicMock(), update_status=MagicMock())
    session = MagicMock()
    session.last_turn_cancellation_seen = True
    session.last_turn_end_state = "idle"
    session.last_turn_error_message = None
    adapter._current_step_messages = {"s1": MagicMock(_status="running")}

    assert _stream_end_pending_error_message(adapter, session) == "Stream cancelled"
