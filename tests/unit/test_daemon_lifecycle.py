"""Tests for daemon lifecycle semantics (IG-085, RFC-0013).

Tests that daemon persists across client sessions and only explicit
'soothe daemon stop' shuts down the daemon.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from soothe.config import SootheConfig
from soothe.daemon import SootheDaemon
from soothe.daemon.server import _ClientConn


class _FakeRunner:
    """Minimal runner stub for daemon lifecycle tests."""

    def __init__(self) -> None:
        self.current_thread_id = "thread-1"
        self.calls: list[dict] = []

    async def astream(self, text: str, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append({"text": text, **kwargs})
        yield ((), "custom", {"type": "soothe.lifecycle.thread.started"})


@pytest.mark.asyncio
async def test_daemon_persists_after_client_disconnect() -> None:
    """Test that daemon keeps running after client disconnects (IG-085)."""
    daemon = SootheDaemon(SootheConfig())
    daemon._runner = _FakeRunner()  # type: ignore[attr-defined]
    daemon._running = True

    sent: list[dict] = []

    async def _fake_broadcast(msg: dict) -> None:
        sent.append(msg)

    daemon._broadcast = _fake_broadcast  # type: ignore[method-assign]

    # Simulate client disconnect by sending detach message
    await daemon._handle_command("/detach")

    # Daemon should keep running
    assert daemon._running is True


@pytest.mark.asyncio
async def test_daemon_persists_after_exit_command() -> None:
    """Test that daemon keeps running after /exit command (IG-085)."""
    daemon = SootheDaemon(SootheConfig())
    daemon._runner = _FakeRunner()  # type: ignore[attr-defined]
    daemon._running = True

    sent: list[dict] = []

    async def _fake_broadcast(msg: dict) -> None:
        sent.append(msg)

    daemon._broadcast = _fake_broadcast  # type: ignore[method-assign]

    # Send /exit command
    await daemon._handle_command("/exit")

    # IG-085: Daemon should KEEP RUNNING
    assert daemon._running is True


@pytest.mark.asyncio
async def test_daemon_persists_after_quit_command() -> None:
    """Test that daemon keeps running after /quit command (IG-085)."""
    daemon = SootheDaemon(SootheConfig())
    daemon._runner = _FakeRunner()  # type: ignore[attr-defined]
    daemon._running = True

    sent: list[dict] = []

    async def _fake_broadcast(msg: dict) -> None:
        sent.append(msg)

    daemon._broadcast = _fake_broadcast  # type: ignore[method-assign]

    # Send /quit command
    await daemon._handle_command("/quit")

    # IG-085: Daemon should KEEP RUNNING
    assert daemon._running is True


@pytest.mark.asyncio
async def test_multiple_clients_connect_disconnect_daemon_persists() -> None:
    """Test that daemon keeps running across multiple client sessions (IG-085)."""
    daemon = SootheDaemon(SootheConfig())
    daemon._runner = _FakeRunner()  # type: ignore[attr-defined]
    daemon._running = True

    sent: list[dict] = []

    async def _fake_broadcast(msg: dict) -> None:
        sent.append(msg)

    daemon._broadcast = _fake_broadcast  # type: ignore[method-assign]

    # Simulate first client connecting and disconnecting
    await daemon._handle_command("/exit")
    assert daemon._running is True

    # Simulate second client connecting and disconnecting
    sent.clear()
    await daemon._handle_command("/quit")
    assert daemon._running is True

    # Simulate third client connecting and detaching
    sent.clear()
    await daemon._handle_command("/detach")
    assert daemon._running is True


@pytest.mark.asyncio
async def test_only_explicit_stop_shutdowns_daemon() -> None:
    """Test that only explicit stop() call shuts down daemon (IG-085)."""
    daemon = SootheDaemon(SootheConfig())
    daemon._runner = _FakeRunner()  # type: ignore[attr-defined]
    daemon._running = True

    # Multiple clients disconnect
    await daemon._handle_command("/exit")
    assert daemon._running is True

    await daemon._handle_command("/quit")
    assert daemon._running is True

    # Only explicit stop() should shutdown daemon
    await daemon.stop()
    assert daemon._running is False


@pytest.mark.asyncio
async def test_cancel_command_does_not_stop_daemon() -> None:
    """Test that /cancel command doesn't stop daemon (IG-085)."""
    daemon = SootheDaemon(SootheConfig())
    daemon._runner = _FakeRunner()  # type: ignore[attr-defined]
    daemon._running = True

    # Send /cancel command
    await daemon._handle_command("/cancel")

    # Daemon should keep running
    assert daemon._running is True


@pytest.mark.asyncio
async def test_daemon_detach_message_handler() -> None:
    """Test that detach message type doesn't stop daemon."""
    daemon = SootheDaemon(SootheConfig())
    daemon._runner = _FakeRunner()  # type: ignore[attr-defined]
    daemon._running = True

    # Create mock session manager that returns None (no active session)
    async def _fake_get_session(client_id: str) -> Any:
        return None

    daemon._session_manager.get_session = _fake_get_session  # type: ignore[method-assign]

    # Handle detach message from client
    await daemon._handle_client_message("client-1", {"type": "detach"})

    # Daemon should keep running
    assert daemon._running is True


@pytest.mark.asyncio
async def test_daemon_lifecycle_comprehensive_scenario() -> None:
    """Comprehensive test: multiple operations, daemon persists throughout (IG-085)."""
    daemon = SootheDaemon(SootheConfig())
    daemon._runner = _FakeRunner()  # type: ignore[attr-defined]
    daemon._running = True

    sent: list[dict] = []

    async def _fake_broadcast(msg: dict) -> None:
        sent.append(msg)

    daemon._broadcast = _fake_broadcast  # type: ignore[method-assign]

    # Scenario: Client A connects, sends query, disconnects
    await daemon._handle_command("/exit")
    assert daemon._running is True

    # Scenario: Client B connects and cancels
    sent.clear()
    await daemon._handle_command("/cancel")
    assert daemon._running is True

    sent.clear()
    await daemon._handle_command("/detach")
    assert daemon._running is True

    # Scenario: Client C connects and quits
    sent.clear()
    await daemon._handle_command("/quit")
    assert daemon._running is True

    # Final: Explicit stop shuts down daemon
    await daemon.stop()
    assert daemon._running is False
