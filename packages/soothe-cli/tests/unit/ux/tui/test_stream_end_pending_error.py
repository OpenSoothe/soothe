"""Tests for stream-end pending step/tool error messaging."""

from __future__ import annotations

from types import SimpleNamespace

from soothe_cli.tui.textual_adapter import _stream_end_pending_error_message


def _adapter_with_step_status(status: str) -> SimpleNamespace:
    return SimpleNamespace(
        _current_step_messages={"step-1": SimpleNamespace(_status=status)},
    )


def test_stream_end_message_prefers_cancellation_notice() -> None:
    adapter = _adapter_with_step_status("running")
    session = SimpleNamespace(
        last_turn_cancellation_seen=True,
        last_turn_end_state="idle",
    )
    assert _stream_end_pending_error_message(adapter, session) == "Stream cancelled"


def test_stream_end_message_uses_stopped_state() -> None:
    adapter = _adapter_with_step_status("running")
    session = SimpleNamespace(
        last_turn_cancellation_seen=False,
        last_turn_end_state="stopped",
    )
    assert _stream_end_pending_error_message(adapter, session) == "Stream cancelled"


def test_stream_end_message_reports_connection_loss() -> None:
    adapter = _adapter_with_step_status("running")
    session = SimpleNamespace(
        last_turn_cancellation_seen=False,
        last_turn_end_state="connection_lost",
    )
    assert _stream_end_pending_error_message(adapter, session) == "Connection lost during stream"


def test_stream_end_message_detects_incomplete_running_steps() -> None:
    adapter = _adapter_with_step_status("running")
    session = SimpleNamespace(
        last_turn_cancellation_seen=False,
        last_turn_end_state="idle",
    )
    assert (
        _stream_end_pending_error_message(adapter, session) == "Stream ended before steps completed"
    )


def test_stream_end_message_falls_back_to_unexpected() -> None:
    adapter = SimpleNamespace(_current_step_messages={})
    session = SimpleNamespace(
        last_turn_cancellation_seen=False,
        last_turn_end_state="idle",
    )
    assert _stream_end_pending_error_message(adapter, session) == "Stream ended unexpectedly"
