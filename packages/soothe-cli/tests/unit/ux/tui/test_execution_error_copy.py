"""Tests for agent execution error presentation in the TUI."""

from __future__ import annotations

from soothe_cli.cli.execution.daemon_errors import friendly_daemon_execution_error


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
