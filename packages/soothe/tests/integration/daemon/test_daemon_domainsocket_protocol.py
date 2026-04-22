"""Domain-socket protocol integration tests for daemon backend APIs.

This module focuses on runtime behavior for the Unix Domain Socket transport and
all protocol message operations routed through it.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import uuid
from pathlib import Path

import pytest
from soothe.daemon.transports.unix_socket import UnixSocketTransport
from tests.integration.conftest import (
    await_event_type,
    await_status_state,
    build_daemon_config,
    force_isolated_home,
)

from soothe.config import SootheConfig
from soothe.config.daemon_config import UnixSocketConfig
from soothe.daemon import DaemonClient, SootheDaemon


def _build_daemon_config(tmp_path: Path) -> tuple[SootheConfig, str]:
    """Build an isolated daemon config for unix socket protocol tests."""
    socket_path = f"/tmp/soothe-domain-socket-{os.getpid()}-{uuid.uuid4().hex[:8]}.sock"
    config = build_daemon_config(tmp_path, socket_path)
    return config, socket_path


async def _await_thread_user_messages(
    client: DaemonClient,
    thread_id: str,
    *,
    expected_messages: set[str] | list[str] | tuple[str, ...],
    limit: int = 10,
    offset: int = 0,
    timeout: float = 10.0,
) -> list[str]:
    """Request thread messages until all expected messages are visible."""
    expected = {expected_messages} if isinstance(expected_messages, str) else set(expected_messages)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        await client.send_thread_messages(thread_id, limit=limit, offset=offset)
        remaining = max(0.1, deadline - loop.time())
        response = await asyncio.wait_for(
            await_event_type(client.read_event, "thread_messages_response", timeout=remaining),
            timeout=remaining + 0.1,
        )
        user_messages = [
            message["content"] for message in response["messages"] if message.get("role") == "user"
        ]
        if expected.issubset(set(user_messages)):
            return user_messages
        if loop.time() >= deadline:
            missing = ", ".join(sorted(expected - set(user_messages)))
            msg = f"Timed out waiting for messages: {missing}"
            raise TimeoutError(msg)
        await asyncio.sleep(0.2)


@pytest.fixture
async def unix_daemon_fixture(tmp_path: Path):
    """Start a daemon exposing only the unix socket transport."""
    force_isolated_home(tmp_path / "soothe-home")
    config, socket_path = _build_daemon_config(tmp_path)
    daemon = SootheDaemon(config)
    await daemon.start()
    await asyncio.sleep(0.2)
    try:
        yield daemon, socket_path
    finally:
        with contextlib.suppress(Exception):
            await daemon.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_unix_socket_transport_lifecycle_and_broadcast(tmp_path: Path) -> None:
    """Layer A: validate transport lifecycle and broadcast fanout for Unix socket."""
    transport_path = f"/tmp/soothe-domain-transport-{os.getpid()}-{uuid.uuid4().hex[:8]}.sock"
    config = UnixSocketConfig(enabled=True, path=transport_path)
    transport = UnixSocketTransport(config)
    await transport.start(lambda msg: None)
    assert transport.transport_type == "unix_socket"
    assert transport.client_count == 0

    client = DaemonClient(sock=Path(transport_path))
    await client.connect()
    await asyncio.sleep(0.1)
    assert transport.client_count == 1

    try:
        await transport.broadcast(
            {"type": "event", "scope": "integration", "origin": "domain-socket"}
        )
        event = await await_event_type(client.read_event, "event")
        assert event["type"] == "event"
    finally:
        await client.close()
        await asyncio.sleep(0.1)
        assert transport.client_count == 0
        await transport.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_unix_socket_protocol_thread_backend_operations(
    unix_daemon_fixture: tuple[SootheDaemon, str],
) -> None:
    """Layer A: validate thread protocol operations via unix socket client."""
    _, socket_path = unix_daemon_fixture
    client = DaemonClient(sock=Path(socket_path))
    await client.connect()

    try:
        await client.send_thread_create(
            initial_message="prepare socket thread",
            metadata={"channel": "unix", "tags": ["unix"], "priority": "normal"},
        )
        created = await await_event_type(client.read_event, "thread_created")
        thread_id = created["thread_id"]
        assert isinstance(thread_id, str)

        await client.send_thread_list(include_stats=True)
        list_response = await await_event_type(client.read_event, "thread_list_response")
        assert list_response["total"] >= 1
        assert any(entry["thread_id"] == thread_id for entry in list_response["threads"])

        await client.send_thread_list(
            {"status": "idle", "tags": ["unix"], "priority": "normal"},
            include_stats=True,
        )
        filtered_list_response = await await_event_type(client.read_event, "thread_list_response")
        filtered_threads = {
            thread["thread_id"]: thread for thread in filtered_list_response["threads"]
        }
        assert thread_id in filtered_threads
        assert filtered_threads[thread_id].get("last_human_message") is None

        await client.send_thread_get(thread_id)
        get_response = await await_event_type(client.read_event, "thread_get_response")
        assert get_response["thread"]["thread_id"] == thread_id

        await client.send_resume_thread(thread_id)
        resume_response = await await_event_type(client.read_event, "status")
        assert resume_response["thread_resumed"] is True
        assert resume_response["thread_id"] == thread_id

        await client.send_input("Say hello")
        first_turn_status = await await_status_state(
            client.read_event,
            {"running", "idle"},
            timeout=6.0,
        )
        if first_turn_status.get("state") == "running":
            await await_status_state(client.read_event, "idle", timeout=6.0)

        # Verify thread can accept another input (proves first completed successfully)
        await client.send_input("Say world")
        second_turn_status = await await_status_state(
            client.read_event,
            {"running", "idle"},
            timeout=6.0,
        )
        if second_turn_status.get("state") == "running":
            await await_status_state(client.read_event, "idle", timeout=6.0)

        # Verify thread operations work after multiple turns
        await client.send_thread_list({"priority": "normal"}, include_stats=True)
        after_turns_list = await await_event_type(client.read_event, "thread_list_response")
        assert after_turns_list["type"] == "thread_list_response"

        await client.send_thread_artifacts(thread_id)
        artifacts_response = await await_event_type(client.read_event, "thread_artifacts_response")
        assert artifacts_response["thread_id"] == thread_id

        await client.send_thread_archive(thread_id)
        archive_response = await await_event_type(client.read_event, "thread_operation_ack")
        assert archive_response["operation"] == "archive"
        assert archive_response["thread_id"] == thread_id
        assert archive_response["success"] is True

        await client.send_resume_thread(thread_id)
        resume_response = await await_event_type(client.read_event, "status")
        assert resume_response["thread_resumed"] is True
        assert resume_response["thread_id"] == thread_id

        await client.send_new_thread()
        new_thread_response = await await_event_type(client.read_event, "status")
        assert new_thread_response["new_thread"] is True

        await client.send_command("/clear")
        clear_response = await await_event_type(client.read_event, "clear")
        assert clear_response["type"] == "clear"

        await client.send_detach()
        detach_response = await await_event_type(client.read_event, "status")
        assert detach_response["state"] == "detached"
    finally:
        await client.close()
