"""Tests for shared daemon connection error presentation."""

from __future__ import annotations

from soothe_cli.cli.execution.daemon_errors import (
    friendly_daemon_connection_error,
    is_daemon_connection_error,
)


def test_is_daemon_connection_error_detects_connection_error_type() -> None:
    assert is_daemon_connection_error(ConnectionError("Connection closed")) is True


def test_is_daemon_connection_error_detects_message_markers() -> None:
    assert is_daemon_connection_error(RuntimeError("Not connected to daemon")) is True


def test_friendly_daemon_connection_error_actionable_copy() -> None:
    msg = friendly_daemon_connection_error(ConnectionError("Connection closed"))
    assert "Daemon connection lost" in msg
    assert "Send your message again" in msg
