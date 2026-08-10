"""Tests for agent execution error presentation in the TUI."""

from __future__ import annotations

from soothe_cli.cli.execution.daemon_errors import (
    friendly_daemon_execution_error,
    is_attach_idle_timeout,
)


def test_friendly_message_for_daemon_worker_subprocess_loss() -> None:
    """Pool worker exit should surface as an actionable retry hint, not raw daemon text."""
    err = RuntimeError(
        "Worker subprocess exited unexpectedly during query execution; "
        "check daemon logs for worker or model errors. (worker exit code: 0)"
    )
    msg = friendly_daemon_execution_error(err)
    assert "Send your message again" in msg
    assert "Worker subprocess exited unexpectedly" not in msg


def test_friendly_message_for_daemon_worker_thread_loss() -> None:
    """Thread pool worker exit should surface as an actionable retry hint."""
    err = RuntimeError(
        "Worker thread exited unexpectedly during query execution; check daemon logs for errors."
    )
    msg = friendly_daemon_execution_error(err)
    assert "Send your message again" in msg
    assert "Worker thread exited unexpectedly" not in msg


def test_other_runtime_errors_pass_through() -> None:
    """Unrecognized errors keep their string form."""
    err = RuntimeError("something else broke")
    assert friendly_daemon_execution_error(err) == "something else broke"


def test_is_attach_idle_timeout_detects_marker() -> None:
    """The attach-only idle timeout is recognized by its marker string."""
    err = TimeoutError("No daemon stream progress within 45s attach window (loop=abc)")
    assert is_attach_idle_timeout(err) is True


def test_is_attach_idle_timeout_rejects_other_timeout() -> None:
    """Unrelated timeouts are not classified as attach idle timeouts."""
    assert is_attach_idle_timeout(TimeoutError("Turn timed out after 30s")) is False


def test_friendly_message_for_attach_idle_timeout() -> None:
    """Attach idle timeout surfaces as a benign ready-for-input hint, not a red error."""
    err = TimeoutError("No daemon stream progress within 45s attach window (loop=abc)")
    msg = friendly_daemon_execution_error(err)
    assert "follow-on turn" in msg
    assert "Ready for your next message" in msg
