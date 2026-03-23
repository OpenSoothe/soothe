"""Domain-socket protocol integration tests for daemon backend APIs.

This module focuses on runtime behavior for the Unix Domain Socket transport and
all protocol message operations routed through it.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import os
import uuid
from pathlib import Path

import pytest

from soothe.config import SootheConfig
from soothe.config.daemon_config import UnixSocketConfig
from soothe.daemon import DaemonClient, SootheDaemon
from soothe.daemon.transports.unix_socket import UnixSocketTransport


def _build_daemon_config(tmp_path: Path) -> tuple[SootheConfig, str]:
    """Build an isolated daemon config for unix socket protocol tests."""
    socket_path = f"/tmp/soothe-domain-socket-{os.getpid()}-{uuid.uuid4().hex[:8]}.sock"

    # Try to load from config.dev.yml to get available providers
    config_path = Path(__file__).parent.parent.parent / "config.dev.yml"
    if config_path.exists():
        base_config = SootheConfig.from_yaml_file(str(config_path))
    else:
        base_config = SootheConfig()

    return (
        SootheConfig(
            providers=base_config.providers,
            router=base_config.router,
            vector_stores=base_config.vector_stores,
            vector_store_router=base_config.vector_store_router,
            persistence={"persist_dir": str(tmp_path / "persistence")},
            protocols={
                "memory": {"enabled": False},
                "durability": {"backend": "json", "persist_dir": str(tmp_path / "durability")},
            },
            daemon={
                "transports": {
                    "unix_socket": {"enabled": True, "path": socket_path},
                    "websocket": {"enabled": False},
                    "http_rest": {"enabled": False},
                },
            },
            # Disable unified classification for integration tests to avoid model compatibility issues
            performance={"unified_classification": False},
        ),
        socket_path,
    )


def _force_isolated_home(home: Path) -> None:
    """Force daemon paths to a test-local SOOTHE_HOME to avoid pid-socket contention."""
    os.environ["SOOTHE_HOME"] = str(home)
    import soothe.config as soothe_config
    from soothe import config as config_module

    soothe_config.SOOTHE_HOME = str(home)
    config_module.SOOTHE_HOME = str(home)

    import soothe.daemon.paths as daemon_paths

    # Update in-memory constants for already-imported modules
    daemon_paths.SOOTHE_HOME = str(home)
    importlib.reload(daemon_paths)

    import soothe.daemon.thread_logger as daemon_thread_logger

    daemon_thread_logger.SOOTHE_HOME = str(home)

    import soothe.core.thread.manager as thread_manager

    thread_manager.SOOTHE_HOME = str(home)


async def _await_event_type(readable, expected_type: str, timeout: float = 2.5) -> dict:
    """Read protocol events until a specific type is observed."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            msg = f"Timed out waiting for event type: {expected_type}"
            raise TimeoutError(msg)
        event = await asyncio.wait_for(readable(), timeout=remaining)
        if event is not None and event.get("type") == expected_type:
            return event


async def _await_status_state(
    readable,
    expected_states: str | set[str] | tuple[str, ...],
    timeout: float = 3.0,
) -> dict:
    """Read protocol events until a status event with the expected state appears."""
    expected: set[str] = {expected_states} if isinstance(expected_states, str) else set(expected_states)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            states = ", ".join(sorted(expected))
            msg = f"Timed out waiting for status state: {states}"
            raise TimeoutError(msg)
        event = await asyncio.wait_for(readable(), timeout=remaining)
        if event is not None and event.get("type") == "status" and event.get("state") in expected:
            return event


async def _await_thread_user_messages(
    client: DaemonClient,
    thread_id: str,
    *,
    expected_messages: set[str] | list[str] | tuple[str, ...],
    limit: int = 10,
    offset: int = 0,
    timeout: float = 15.0,
) -> list[str]:
    """Request thread messages until all expected messages are visible."""
    expected = {expected_messages} if isinstance(expected_messages, str) else set(expected_messages)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        await client.send_thread_messages(thread_id, limit=limit, offset=offset)
        remaining = max(0.1, deadline - loop.time())
        response = await asyncio.wait_for(
            _await_event_type(client.read_event, "thread_messages_response", timeout=remaining),
            timeout=remaining + 0.1,
        )
        user_messages = [message["content"] for message in response["messages"] if message.get("role") == "user"]
        if expected.issubset(set(user_messages)):
            return user_messages
        if loop.time() >= deadline:
            missing = ", ".join(sorted(expected - set(user_messages)))
            msg = f"Timed out waiting for messages: {missing}"
            raise TimeoutError(msg)
        await asyncio.sleep(0.3)


@pytest.fixture
async def unix_daemon_fixture(tmp_path: Path):
    """Start a daemon exposing only the unix socket transport."""
    _force_isolated_home(tmp_path / "soothe-home")
    config, socket_path = _build_daemon_config(tmp_path)
    daemon = SootheDaemon(config)
    await daemon.start()
    await asyncio.sleep(0.4)
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
        await transport.broadcast({"type": "event", "scope": "integration", "origin": "domain-socket"})
        event = await _await_event_type(client.read_event, "event")
        assert event["type"] == "event"
    finally:
        await client.close()
        await asyncio.sleep(0.1)
        assert transport.client_count == 0
        await transport.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_unix_socket_protocol_thread_backend_operations(unix_daemon_fixture: tuple[SootheDaemon, str]) -> None:
    """Layer A: validate thread protocol operations via unix socket client."""
    daemon, socket_path = unix_daemon_fixture
    _ = daemon
    client = DaemonClient(sock=Path(socket_path))
    await client.connect()

    try:
        await client.send_thread_create(
            initial_message="prepare socket thread",
            metadata={"channel": "unix", "tags": ["unix"], "priority": "normal"},
        )
        created = await _await_event_type(client.read_event, "thread_created")
        thread_id = created["thread_id"]
        assert isinstance(thread_id, str)

        await client.send_thread_list(include_stats=True)
        list_response = await _await_event_type(client.read_event, "thread_list_response")
        assert list_response["total"] >= 1
        assert any(entry["thread_id"] == thread_id for entry in list_response["threads"])

        await client.send_thread_list({"status": "idle", "tags": ["unix"], "priority": "normal"}, include_stats=True)
        filtered_list_response = await _await_event_type(client.read_event, "thread_list_response")
        filtered_threads = {thread["thread_id"]: thread for thread in filtered_list_response["threads"]}
        assert thread_id in filtered_threads
        assert filtered_threads[thread_id].get("last_human_message") is None

        await client.send_thread_get(thread_id)
        get_response = await _await_event_type(client.read_event, "thread_get_response")
        assert get_response["thread"]["thread_id"] == thread_id

        await client.send_resume_thread(thread_id)
        resume_response = await _await_event_type(client.read_event, "status")
        assert resume_response["thread_resumed"] is True
        assert resume_response["thread_id"] == thread_id

        await client.send_input("Let's continue thread history with first prompt.")
        first_turn_status = await _await_status_state(
            client.read_event,
            {"running", "idle"},
            timeout=4.0,
        )
        if first_turn_status.get("state") == "running":
            await _await_status_state(client.read_event, "idle", timeout=4.0)

        user_messages = await _await_thread_user_messages(
            client,
            thread_id,
            expected_messages=("Let's continue thread history with first prompt.",),
            timeout=15.0,
        )
        assert "Let's continue thread history with first prompt." in user_messages

        await client.send_input("Continue from previous context in same thread.")
        second_turn_status = await _await_status_state(
            client.read_event,
            {"running", "idle"},
            timeout=4.0,
        )
        if second_turn_status.get("state") == "running":
            await _await_status_state(client.read_event, "idle", timeout=4.0)

        continued_user_messages = await _await_thread_user_messages(
            client,
            thread_id,
            expected_messages=(
                "Let's continue thread history with first prompt.",
                "Continue from previous context in same thread.",
            ),
            timeout=15.0,
        )
        assert len(continued_user_messages) >= 2
        assert "Let's continue thread history with first prompt." in continued_user_messages
        assert "Continue from previous context in same thread." in continued_user_messages

        await client.send_thread_list({"priority": "normal"}, include_stats=True)
        after_turns_list = await _await_event_type(client.read_event, "thread_list_response")
        listed_thread = next(item for item in after_turns_list["threads"] if item["thread_id"] == thread_id)
        assert listed_thread.get("last_human_message") is not None

        await client.send_thread_artifacts(thread_id)
        artifacts_response = await _await_event_type(client.read_event, "thread_artifacts_response")
        assert artifacts_response["thread_id"] == thread_id

        await client.send_thread_archive(thread_id)
        archive_response = await _await_event_type(client.read_event, "thread_operation_ack")
        assert archive_response["operation"] == "archive"
        assert archive_response["thread_id"] == thread_id
        assert archive_response["success"] is True

        await client.send_resume_thread(thread_id)
        resume_response = await _await_event_type(client.read_event, "status")
        assert resume_response["thread_resumed"] is True
        assert resume_response["thread_id"] == thread_id

        await client.send_new_thread()
        new_thread_response = await _await_event_type(client.read_event, "status")
        assert new_thread_response["new_thread"] is True

        await client.send_command("/clear")
        clear_response = await _await_event_type(client.read_event, "clear")
        assert clear_response["type"] == "clear"

        await client.send_detach()
        detach_response = await _await_event_type(client.read_event, "status")
        assert detach_response["state"] == "detached"
    finally:
        await client.close()
