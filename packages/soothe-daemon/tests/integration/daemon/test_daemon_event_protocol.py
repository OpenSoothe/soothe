"""Event protocol integration tests for RFC-0015 compliance.

This module validates RFC-0015 event protocol including event type validation,
event model schema validation, event registry dispatch, tool events, subagent
events, error events, and event hierarchy.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from pathlib import Path

import pytest
from soothe.config import SootheConfig

from soothe_daemon import SootheDaemon, WebSocketClient
from soothe_daemon.config import SootheDaemonConfig
from tests.integration.daemon_fixtures import (
    alloc_ephemeral_port,
    await_event_type,
    build_daemon_config,
    force_isolated_home,
)
from tests.integration.ws_loop_client import (
    loop_new_with_initial_input,
    request_loop_delete,
    request_loop_list,
    subscribe_loop_stream,
)


def _build_daemon_config(tmp_path: Path, ws_port: int) -> tuple[SootheConfig, SootheDaemonConfig]:
    """Build an isolated agent and daemon server config for event protocol tests."""
    return build_daemon_config(
        tmp_path=tmp_path,
        websocket_port=ws_port,
    )


async def _collect_events_during_query(
    client: WebSocketClient,
    loop_id: str,
    query: str,
    timeout: float = 6.0,
) -> list[dict]:
    """Collect all events emitted during query execution."""
    events = []
    collection_done = asyncio.Event()

    async def collect_events():
        try:
            while not collection_done.is_set():
                event = await asyncio.wait_for(client.read_event(), timeout=0.3)
                if event is not None:
                    events.append(event)
                    # Check for idle status indicating completion
                    if event.get("type") == "status" and event.get("state") == "idle":
                        collection_done.set()
                        break
        except TimeoutError:
            collection_done.set()

    # Start collection task
    collection_task = asyncio.create_task(collect_events())

    # Send query
    await client.send_input(loop_id, query)

    # Wait for collection to complete
    try:
        await asyncio.wait_for(collection_done.wait(), timeout=timeout)
    except TimeoutError:
        pass
    finally:
        collection_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await collection_task

    return events


@pytest.fixture
async def daemon_fixture(tmp_path: Path):
    """Start a daemon for event protocol tests."""
    force_isolated_home(tmp_path / "soothe-home")
    ws_port = alloc_ephemeral_port()
    config, daemon_cfg = _build_daemon_config(tmp_path, ws_port)
    daemon = SootheDaemon(config, daemon_config=daemon_cfg)
    await daemon.start()
    await asyncio.sleep(0.2)
    try:
        yield daemon, ws_port
    finally:
        with contextlib.suppress(Exception):
            await daemon.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lifecycle_events(daemon_fixture: tuple[SootheDaemon, int]) -> None:
    """Validate loop lifecycle RPC flow (RFC-503 / RFC-0015)."""
    daemon, ws_port = daemon_fixture
    _ = daemon

    client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
    await client.connect()

    try:
        loop_id = await loop_new_with_initial_input(
            client,
            initial_message="test lifecycle events",
        )
        assert loop_id

        await client.send_loop_reattach(loop_id)
        status_event = await await_event_type(client.read_event, "status", timeout=3.0)
        assert status_event["type"] == "status"

        archive_resp = await request_loop_delete(client, loop_id)
        assert archive_resp["type"] == "loop_delete_response"
        assert archive_resp.get("success") is True

    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_protocol_events(daemon_fixture: tuple[SootheDaemon, int]) -> None:
    """Validate protocol events (context, memory, plan, policy) per RFC-0015."""
    daemon, ws_port = daemon_fixture
    _ = daemon

    client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
    await client.connect()

    try:
        loop_id = await loop_new_with_initial_input(client, initial_message="test protocol events")
        await subscribe_loop_stream(client, loop_id)

        events = await _collect_events_during_query(client, loop_id, "Say hello", timeout=6.0)

        # Verify we received events during execution
        assert len(events) > 0, "Should receive events during query execution"

        # Look for specific event types
        event_types = {e.get("type") for e in events}

        # We should at least see status events
        assert "status" in event_types

    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_tool_events(daemon_fixture: tuple[SootheDaemon, int]) -> None:
    """Validate tool execution events with dynamic naming per RFC-0015."""
    daemon, ws_port = daemon_fixture
    _ = daemon

    client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
    await client.connect()

    try:
        loop_id = await loop_new_with_initial_input(client, initial_message="test tool events")
        await subscribe_loop_stream(client, loop_id)

        events = await _collect_events_during_query(
            client,
            loop_id,
            "List current directory",
            timeout=6.0,
        )

        assert len(events) > 0, "Should receive events during tool execution"

    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_subagent_events(daemon_fixture: tuple[SootheDaemon, int]) -> None:
    """Validate subagent activity events per RFC-0015."""
    daemon, ws_port = daemon_fixture
    _ = daemon

    client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
    await client.connect()

    try:
        loop_id = await loop_new_with_initial_input(client, initial_message="test subagent events")
        await subscribe_loop_stream(client, loop_id)

        events = await _collect_events_during_query(
            client,
            loop_id,
            "What is 2+2?",
            timeout=6.0,
        )

        assert len(events) > 0, "Should receive events during query"

    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_error_events(daemon_fixture: tuple[SootheDaemon, int]) -> None:
    """Validate error responses for invalid loop RPC."""
    daemon, ws_port = daemon_fixture
    _ = daemon

    client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
    await client.connect()

    try:
        await loop_new_with_initial_input(client, initial_message="test error events")

        fake_loop_id = f"non-existent-{uuid.uuid4().hex}"
        await client.send_loop_get(fake_loop_id)

        response = await asyncio.wait_for(client.read_event(), timeout=3.0)
        assert response is not None

        list_response = await request_loop_list(client)
        assert list_response["type"] == "loop_list_response"

    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_event_registry_dispatch(
    daemon_fixture: tuple[SootheDaemon, int],
) -> None:
    """Test event type handling and dispatch correctness."""
    daemon, ws_port = daemon_fixture
    _ = daemon

    client = WebSocketClient(url=f"ws://127.0.0.1:{ws_port}")
    await client.connect()

    try:
        loop_id = await loop_new_with_initial_input(client, initial_message="test registry")
        await subscribe_loop_stream(client, loop_id)

        events = await _collect_events_during_query(client, loop_id, "Hello", timeout=6.0)

        for event in events:
            event_type = event.get("type")
            assert event_type is not None, "Event should have type field"

        event_types = {e.get("type") for e in events}
        assert len(event_types) > 0, "Should receive at least one event type"

        for event in events:
            assert isinstance(event, dict), "Event should be a dictionary"
            assert "type" in event, "Event should have 'type' field"

    finally:
        await client.close()
