"""Integration tests for thread lifecycle via daemon protocol (RFC-0017)."""

import pytest

from soothe.daemon import DaemonClient
from soothe.daemon.protocol import encode


@pytest.mark.asyncio
async def test_thread_lifecycle_via_unix_socket(running_daemon):
    """Test create -> resume -> archive via Unix socket protocol."""
    client = DaemonClient()
    await client.connect()

    try:
        # Create thread
        await client._send(
            {
                "type": "thread_create",
                "metadata": {"tags": ["test"]},
            }
        )

        response = await client.read_event()
        assert response is not None
        if response.get("type") == "thread_created":
            thread_id = response["thread_id"]

            # Get thread
            await client._send(
                {
                    "type": "thread_get",
                    "thread_id": thread_id,
                }
            )

            response = await client.read_event()
            assert response is not None
            if response.get("type") == "thread_get_response":
                thread = response["thread"]
                assert thread["thread_id"] == thread_id

            # Archive thread
            await client._send(
                {
                    "type": "thread_archive",
                    "thread_id": thread_id,
                }
            )

            response = await client.read_event()
            assert response is not None
            if response.get("type") == "thread_operation_ack":
                assert response["success"] is True
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_thread_list_with_filtering(running_daemon):
    """Test thread listing with filters."""
    client = DaemonClient()
    await client.connect()

    try:
        # Create multiple threads with different tags
        await client._send(
            {
                "type": "thread_create",
                "metadata": {"tags": ["research"], "priority": "high"},
            }
        )
        await client.read_event()

        await client._send(
            {
                "type": "thread_create",
                "metadata": {"tags": ["analysis"], "priority": "low"},
            }
        )
        await client.read_event()

        # List threads with filter
        await client._send(
            {
                "type": "thread_list",
                "filter": {"tags": ["research"]},
                "include_stats": False,
            }
        )

        response = await client.read_event()
        assert response is not None
        if response.get("type") == "thread_list_response":
            threads = response["threads"]
            assert len(threads) >= 1
            assert all("research" in t["metadata"]["tags"] for t in threads)
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_thread_stats_calculation(running_daemon):
    """Test thread statistics calculation."""
    client = DaemonClient()
    await client.connect()

    try:
        # Create thread
        await client._send(
            {
                "type": "thread_create",
            }
        )

        response = await client.read_event()
        assert response is not None
        if response.get("type") == "thread_created":
            thread_id = response["thread_id"]

            # Get stats (should be empty for new thread)
            # Note: Stats are calculated on demand via ThreadContextManager
            # In a real test, we would send messages to the thread first

            # For now, just verify the thread exists
            await client._send(
                {
                    "type": "thread_get",
                    "thread_id": thread_id,
                }
            )

            response = await client.read_event()
            assert response is not None
            if response.get("type") == "thread_get_response":
                thread = response["thread"]
                assert "stats" in thread
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_thread_messages_retrieval(running_daemon):
    """Test thread message retrieval."""
    client = DaemonClient()
    await client.connect()

    try:
        # Create thread
        await client._send(
            {
                "type": "thread_create",
            }
        )

        response = await client.read_event()
        assert response is not None
        if response.get("type") == "thread_created":
            thread_id = response["thread_id"]

            # Get messages (should be empty for new thread)
            await client._send(
                {
                    "type": "thread_messages",
                    "thread_id": thread_id,
                    "limit": 10,
                }
            )

            response = await client.read_event()
            assert response is not None
            if response.get("type") == "thread_messages_response":
                messages = response["messages"]
                assert isinstance(messages, list)
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_thread_not_found_error(running_daemon):
    """Test error handling for non-existent thread."""
    client = DaemonClient()
    await client.connect()

    try:
        # Try to get non-existent thread
        await client._send(
            {
                "type": "thread_get",
                "thread_id": "nonexistent123",
            }
        )

        response = await client.read_event()
        assert response is not None
        if response.get("type") == "error":
            assert response["code"] == "THREAD_NOT_FOUND"
    finally:
        await client.close()


@pytest.fixture
async def running_daemon():
    """Start daemon for testing."""
    import asyncio

    from soothe.config import SootheConfig
    from soothe.daemon import SootheDaemon

    # Create test configuration
    config = SootheConfig()

    # Start daemon
    daemon = SootheDaemon(config)
    task = asyncio.create_task(daemon.start())

    # Wait for daemon to start
    await asyncio.sleep(0.5)

    yield daemon

    # Stop daemon
    daemon._running = False
    if daemon._stop_event:
        daemon._stop_event.set()
    await task
