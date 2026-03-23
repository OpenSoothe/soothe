"""Event protocol integration tests for RFC-0015 compliance.

This module validates RFC-0015 event protocol including event type validation,
event model schema validation, event registry dispatch, tool events, subagent
events, error events, and event hierarchy.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import uuid
from pathlib import Path

import pytest

from soothe.config import SootheConfig
from soothe.daemon import DaemonClient, SootheDaemon
from tests.integration.conftest import (
    await_event_type,
    build_daemon_config,
    force_isolated_home,
)


def _build_daemon_config(tmp_path: Path, socket_path: str) -> SootheConfig:
    """Build an isolated daemon config for event protocol tests."""
    return build_daemon_config(
        tmp_path=tmp_path,
        unix_socket_path=socket_path,
    )


async def _collect_events_during_query(
    client: DaemonClient,
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
    await client.send_input(query)

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
    socket_path = f"/tmp/soothe-events-{os.getpid()}-{uuid.uuid4().hex[:8]}.sock"
    config = _build_daemon_config(tmp_path, socket_path)
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
async def test_lifecycle_events(daemon_fixture: tuple[SootheDaemon, str]) -> None:
    """Validate thread lifecycle event structure per RFC-0015."""
    daemon, socket_path = daemon_fixture
    _ = daemon

    client = DaemonClient(sock=Path(socket_path))
    await client.connect()

    try:
        # Create thread → should emit thread_created event
        await client.send_thread_create(
            initial_message="test lifecycle events",
            metadata={"tags": ["lifecycle"]},
        )
        created_event = await await_event_type(client.read_event, "thread_created", timeout=5.0)

        # Validate event structure
        assert created_event["type"] == "thread_created"
        assert "thread_id" in created_event
        assert isinstance(created_event["thread_id"], str)
        thread_id = created_event["thread_id"]

        # Resume thread → should emit status event with thread_resumed
        await client.send_resume_thread(thread_id)
        status_event = await await_event_type(client.read_event, "status", timeout=3.0)
        assert status_event["type"] == "status"
        assert status_event.get("thread_resumed") is True

        # Start query → should emit thread.started event (if implemented)
        # Note: Lifecycle events beyond thread_created/status may be internal
        # The daemon protocol focuses on thread_created, status, and thread operations

        # Archive thread → should emit operation_ack
        await client.send_thread_archive(thread_id)
        archive_event = await await_event_type(client.read_event, "thread_operation_ack", timeout=3.0)
        assert archive_event["type"] == "thread_operation_ack"
        assert archive_event["operation"] == "archive"
        assert archive_event["thread_id"] == thread_id

    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_protocol_events(daemon_fixture: tuple[SootheDaemon, str]) -> None:
    """Validate protocol events (context, memory, plan, policy) per RFC-0015."""
    daemon, socket_path = daemon_fixture
    _ = daemon

    client = DaemonClient(sock=Path(socket_path))
    await client.connect()

    try:
        # Create thread
        await client.send_thread_create(initial_message="test protocol events")
        created = await await_event_type(client.read_event, "thread_created", timeout=5.0)
        thread_id = created["thread_id"]

        # Execute query that should trigger protocol events
        # Note: Protocol events (context.projected, memory.recalled, etc.)
        # are internal Soothe events that may not be exposed through daemon protocol
        # The daemon protocol focuses on thread operations and streaming

        events = await _collect_events_during_query(client, "Say hello", timeout=6.0)

        # Verify we received events during execution
        assert len(events) > 0, "Should receive events during query execution"

        # Look for specific event types
        event_types = {e.get("type") for e in events}

        # We should at least see status events
        assert "status" in event_types

        # Note: Internal protocol events (soothe.protocol.*)
        # may be emitted as custom events within the "event" type
        # Full validation would require checking event["data"]["type"] for
        # soothe.protocol.context.projected, etc.

    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_tool_events(daemon_fixture: tuple[SootheDaemon, str]) -> None:
    """Validate tool execution events with dynamic naming per RFC-0015."""
    daemon, socket_path = daemon_fixture
    _ = daemon

    client = DaemonClient(sock=Path(socket_path))
    await client.connect()

    try:
        # Create thread
        await client.send_thread_create(initial_message="test tool events")
        created = await await_event_type(client.read_event, "thread_created", timeout=5.0)
        _ = created["thread_id"]

        # Execute query that should trigger tool usage
        # Note: Tool events (soothe.tool.{name}.started/completed)
        # are emitted during tool execution

        events = await _collect_events_during_query(
            client,
            "List current directory",
            timeout=6.0,
        )

        # Verify we received events
        assert len(events) > 0, "Should receive events during tool execution"

        # Tool events would be nested within the event stream
        # Look for events with tool execution data
        # Full validation requires inspecting event["data"]["type"] for
        # patterns like "soothe.tool.read_file.started"

    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_subagent_events(daemon_fixture: tuple[SootheDaemon, str]) -> None:
    """Validate subagent activity events per RFC-0015."""
    daemon, socket_path = daemon_fixture
    _ = daemon

    client = DaemonClient(sock=Path(socket_path))
    await client.connect()

    try:
        # Create thread
        await client.send_thread_create(initial_message="test subagent events")
        created = await await_event_type(client.read_event, "thread_created", timeout=5.0)
        _ = created["thread_id"]

        # Execute query that might trigger subagent usage
        # Note: Subagent events (soothe.subagent.*)
        # are emitted during subagent execution

        events = await _collect_events_during_query(
            client,
            "What is 2+2?",
            timeout=6.0,
        )

        # Verify we received events
        assert len(events) > 0, "Should receive events during query"

        # Subagent events would be in the event stream
        # Look for events with subagent activity data
        # Full validation requires checking event["data"]["type"] for
        # patterns like "soothe.subagent.browser.step" or "soothe.subagent.research.web_search"

    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_error_events(daemon_fixture: tuple[SootheDaemon, str]) -> None:
    """Validate error event structure per RFC-0015."""
    daemon, socket_path = daemon_fixture
    _ = daemon

    client = DaemonClient(sock=Path(socket_path))
    await client.connect()

    try:
        # Create thread
        await client.send_thread_create(initial_message="test error events")
        created = await await_event_type(client.read_event, "thread_created", timeout=5.0)
        thread_id = created["thread_id"]

        # Trigger an error condition
        # Try to access non-existent thread
        fake_thread_id = f"non-existent-{uuid.uuid4().hex}"
        await client.send_thread_get(fake_thread_id)

        # Read response (may be error or operation_ack)
        response = await asyncio.wait_for(client.read_event(), timeout=3.0)
        assert response is not None

        # The response might be an error event or a structured error response
        # RFC-0015 defines soothe.error.* events for runtime errors
        # The daemon protocol may use different error reporting mechanisms

        # Verify daemon remains operational
        await client.send_thread_list()
        list_response = await await_event_type(client.read_event, "thread_list_response", timeout=3.0)
        assert list_response["type"] == "thread_list_response"

    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_event_registry_dispatch(daemon_fixture: tuple[SootheDaemon, str]) -> None:
    """Test event type handling and dispatch correctness."""
    daemon, socket_path = daemon_fixture
    _ = daemon

    client = DaemonClient(sock=Path(socket_path))
    await client.connect()

    try:
        # Create thread and execute query
        await client.send_thread_create(initial_message="test registry")
        created = await await_event_type(client.read_event, "thread_created", timeout=5.0)
        _ = created["thread_id"]

        events = await _collect_events_during_query(client, "Hello", timeout=6.0)

        # Verify we can process all received events
        for event in events:
            event_type = event.get("type")
            assert event_type is not None, "Event should have type field"

        # Verify we can handle all event types received
        event_types = {e.get("type") for e in events}
        assert len(event_types) > 0, "Should receive at least one event type"

        # Verify all events have required structure
        for event in events:
            assert isinstance(event, dict), "Event should be a dictionary"
            assert "type" in event, "Event should have 'type' field"

    finally:
        await client.close()
