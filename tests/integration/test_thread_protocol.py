"""Integration tests for RFC-0017 thread management via daemon protocol."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from soothe.backends.durability.json import JsonDurability
from soothe.config import SootheConfig
from soothe.core.thread import ThreadContextManager
from soothe.daemon import DaemonClient, SootheDaemon
from soothe.protocols.durability import ThreadMetadata


@pytest.fixture
async def daemon_server(tmp_path: Path):
    """Create and start a daemon server for testing."""
    config = SootheConfig(
        persistence={"persist_dir": str(tmp_path / "persistence")},
        daemon={
            "enabled": True,
            "transports": {
                "unix_socket": {"enabled": True, "path": str(tmp_path / "test.sock")},
                "websocket": {"enabled": False},
                "http_rest": {"enabled": False},
            },
        },
    )

    daemon = SootheDaemon(config)
    await daemon.start()

    # Give daemon time to initialize
    await asyncio.sleep(0.5)

    yield daemon

    # Cleanup
    try:
        await daemon.stop()
    except Exception:
        pass


@pytest.fixture
async def daemon_client(daemon_server):
    """Create a daemon client connected to the test daemon."""
    client = DaemonClient()
    await client.connect()
    yield client
    await client.close()


@pytest.mark.asyncio
class TestThreadProtocol:
    """Test thread management via daemon protocol (RFC-0017)."""

    async def test_thread_create(self, daemon_client):
        """Test thread creation via daemon protocol."""
        # Send thread_create message
        await daemon_client.send_message(
            {
                "type": "thread_create",
                "metadata": {
                    "tags": ["test", "integration"],
                    "priority": "high",
                    "category": "testing",
                },
            }
        )

        # Read response
        response = await daemon_client.read_event()
        assert response is not None
        assert response.get("type") == "thread_created"
        assert "thread_id" in response
        assert response.get("status") in ("idle", "active")

        thread_id = response["thread_id"]
        assert isinstance(thread_id, str)
        assert len(thread_id) > 0

    async def test_thread_create_with_initial_message(self, daemon_client):
        """Test thread creation with initial message."""
        await daemon_client.send_message(
            {
                "type": "thread_create",
                "initial_message": "Hello, this is a test",
                "metadata": {"tags": ["test"]},
            }
        )

        response = await daemon_client.read_event()
        assert response is not None
        assert response.get("type") == "thread_created"

    async def test_thread_get(self, daemon_client):
        """Test getting thread details via daemon protocol."""
        # Create a thread first
        await daemon_client.send_message(
            {
                "type": "thread_create",
                "metadata": {"tags": ["test"], "priority": "normal"},
            }
        )

        response = await daemon_client.read_event()
        thread_id = response["thread_id"]

        # Get thread details
        await daemon_client.send_message({"type": "thread_get", "thread_id": thread_id})

        response = await daemon_client.read_event()
        assert response is not None
        assert response.get("type") == "thread_get_response"

        thread = response.get("thread")
        assert thread is not None
        assert thread.get("thread_id") == thread_id
        assert "status" in thread
        assert "metadata" in thread
        assert "created_at" in thread
        assert "updated_at" in thread

        # Verify metadata
        metadata = thread.get("metadata", {})
        assert "test" in metadata.get("tags", [])
        assert metadata.get("priority") == "normal"

    async def test_thread_get_not_found(self, daemon_client):
        """Test getting non-existent thread returns error."""
        await daemon_client.send_message({"type": "thread_get", "thread_id": "nonexistent123"})

        response = await daemon_client.read_event()
        assert response is not None
        assert response.get("type") == "error"
        assert "THREAD_NOT_FOUND" in response.get("code", "")
        assert "nonexistent123" in response.get("message", "")

    async def test_thread_list(self, daemon_client):
        """Test listing threads via daemon protocol."""
        # Create multiple threads
        for i in range(3):
            await daemon_client.send_message(
                {
                    "type": "thread_create",
                    "metadata": {"tags": [f"test{i}"], "priority": "normal"},
                }
            )
            response = await daemon_client.read_event()
            assert response.get("type") == "thread_created"

        # List all threads
        await daemon_client.send_message({"type": "thread_list"})

        response = await daemon_client.read_event()
        assert response is not None
        assert response.get("type") == "thread_list_response"

        threads = response.get("threads", [])
        assert isinstance(threads, list)
        assert len(threads) >= 3

        # Verify thread structure
        for thread in threads:
            assert "thread_id" in thread
            assert "status" in thread
            assert "metadata" in thread

    async def test_thread_list_with_filter(self, daemon_client):
        """Test listing threads with filter."""
        # Create threads with different priorities
        await daemon_client.send_message(
            {
                "type": "thread_create",
                "metadata": {"tags": ["research"], "priority": "high"},
            }
        )
        await daemon_client.read_event()

        await daemon_client.send_message(
            {
                "type": "thread_create",
                "metadata": {"tags": ["analysis"], "priority": "low"},
            }
        )
        await daemon_client.read_event()

        # Filter by priority
        await daemon_client.send_message(
            {
                "type": "thread_list",
                "filter": {"priority": "high"},
            }
        )

        response = await daemon_client.read_event()
        assert response is not None

        threads = response.get("threads", [])
        assert all(t.get("metadata", {}).get("priority") == "high" for t in threads)

    async def test_thread_list_with_stats(self, daemon_client):
        """Test listing threads with statistics."""
        # Create a thread
        await daemon_client.send_message(
            {
                "type": "thread_create",
                "metadata": {"tags": ["test"]},
            }
        )
        await daemon_client.read_event()

        # List with stats
        await daemon_client.send_message(
            {
                "type": "thread_list",
                "include_stats": True,
            }
        )

        response = await daemon_client.read_event()
        assert response is not None

        threads = response.get("threads", [])
        assert len(threads) > 0

        # Check that stats are included
        for thread in threads:
            assert "stats" in thread
            stats = thread.get("stats", {})
            assert "message_count" in stats
            assert "event_count" in stats
            assert "artifact_count" in stats

    async def test_thread_archive(self, daemon_client):
        """Test archiving a thread via daemon protocol."""
        # Create a thread
        await daemon_client.send_message(
            {
                "type": "thread_create",
                "metadata": {"tags": ["test"]},
            }
        )

        response = await daemon_client.read_event()
        thread_id = response["thread_id"]

        # Archive thread
        await daemon_client.send_message({"type": "thread_archive", "thread_id": thread_id})

        response = await daemon_client.read_event()
        assert response is not None
        assert response.get("type") == "thread_operation_ack"
        assert response.get("operation") == "archive"
        assert response.get("thread_id") == thread_id
        assert response.get("success") is True

        # Verify thread is archived
        await daemon_client.send_message({"type": "thread_get", "thread_id": thread_id})

        response = await daemon_client.read_event()
        thread = response.get("thread")
        assert thread.get("status") == "archived"

    async def test_thread_archive_not_found(self, daemon_client):
        """Test archiving non-existent thread returns error."""
        await daemon_client.send_message({"type": "thread_archive", "thread_id": "nonexistent"})

        response = await daemon_client.read_event()
        assert response is not None
        assert response.get("type") == "thread_operation_ack"
        assert response.get("success") is False

    async def test_thread_delete(self, daemon_client):
        """Test deleting a thread via daemon protocol."""
        # Create a thread
        await daemon_client.send_message(
            {
                "type": "thread_create",
                "metadata": {"tags": ["test"]},
            }
        )

        response = await daemon_client.read_event()
        thread_id = response["thread_id"]

        # Delete thread
        await daemon_client.send_message({"type": "thread_delete", "thread_id": thread_id})

        response = await daemon_client.read_event()
        assert response is not None
        assert response.get("type") == "thread_operation_ack"
        assert response.get("operation") == "delete"
        assert response.get("thread_id") == thread_id
        assert response.get("success") is True

        # Verify thread no longer exists
        await daemon_client.send_message({"type": "thread_get", "thread_id": thread_id})

        response = await daemon_client.read_event()
        assert response.get("type") == "error"

    async def test_thread_messages(self, daemon_client):
        """Test getting thread messages via daemon protocol."""
        # Create a thread
        await daemon_client.send_message(
            {
                "type": "thread_create",
                "metadata": {"tags": ["test"]},
            }
        )

        response = await daemon_client.read_event()
        thread_id = response["thread_id"]

        # Get messages (should be empty for new thread)
        await daemon_client.send_message(
            {
                "type": "thread_messages",
                "thread_id": thread_id,
                "limit": 100,
                "offset": 0,
            }
        )

        response = await daemon_client.read_event()
        assert response is not None
        assert response.get("type") == "thread_messages_response"
        assert response.get("thread_id") == thread_id
        assert "messages" in response
        assert isinstance(response.get("messages"), list)

    async def test_thread_artifacts(self, daemon_client):
        """Test getting thread artifacts via daemon protocol."""
        # Create a thread
        await daemon_client.send_message(
            {
                "type": "thread_create",
                "metadata": {"tags": ["test"]},
            }
        )

        response = await daemon_client.read_event()
        thread_id = response["thread_id"]

        # Get artifacts (should be empty for new thread)
        await daemon_client.send_message({"type": "thread_artifacts", "thread_id": thread_id})

        response = await daemon_client.read_event()
        assert response is not None
        assert response.get("type") == "thread_artifacts_response"
        assert response.get("thread_id") == thread_id
        assert "artifacts" in response
        assert isinstance(response.get("artifacts"), list)

    async def test_thread_lifecycle_full(self, daemon_client):
        """Test complete thread lifecycle: create → get → update → archive."""
        # 1. Create thread
        await daemon_client.send_message(
            {
                "type": "thread_create",
                "metadata": {
                    "tags": ["lifecycle", "test"],
                    "priority": "high",
                    "category": "integration-test",
                },
            }
        )

        response = await daemon_client.read_event()
        assert response.get("type") == "thread_created"
        thread_id = response["thread_id"]

        # 2. Get thread details
        await daemon_client.send_message({"type": "thread_get", "thread_id": thread_id})

        response = await daemon_client.read_event()
        assert response.get("type") == "thread_get_response"
        thread = response.get("thread")
        assert thread.get("metadata", {}).get("priority") == "high"

        # 3. Archive thread
        await daemon_client.send_message({"type": "thread_archive", "thread_id": thread_id})

        response = await daemon_client.read_event()
        assert response.get("type") == "thread_operation_ack"
        assert response.get("success") is True

        # 4. Verify archived status
        await daemon_client.send_message({"type": "thread_get", "thread_id": thread_id})

        response = await daemon_client.read_event()
        thread = response.get("thread")
        assert thread.get("status") == "archived"


@pytest.mark.asyncio
class TestThreadManagerDirect:
    """Test ThreadContextManager directly (not via daemon)."""

    async def test_create_thread(self, tmp_path):
        """Test thread creation with ThreadContextManager."""
        config = SootheConfig(persistence={"persist_dir": str(tmp_path)})
        durability = JsonDurability(str(tmp_path))
        manager = ThreadContextManager(durability, config)

        thread_info = await manager.create_thread(metadata={"tags": ["test"], "priority": "high"})

        assert thread_info.thread_id is not None
        assert thread_info.status in ("idle", "active")
        assert "test" in thread_info.metadata.tags

    async def test_update_metadata(self, tmp_path):
        """Test updating thread metadata."""
        config = SootheConfig(persistence={"persist_dir": str(tmp_path)})
        durability = JsonDurability(str(tmp_path))
        manager = ThreadContextManager(durability, config)

        # Create thread
        thread = await manager.create_thread(metadata={"tags": ["initial"], "priority": "normal"})

        # Update metadata
        await durability.update_thread_metadata(
            thread.thread_id,
            {"tags": ["updated"], "priority": "high"},
        )

        # Verify update
        enhanced = await manager.get_thread(thread.thread_id)
        assert "updated" in enhanced.metadata.tags
        assert enhanced.metadata.priority == "high"

    async def test_get_thread_stats(self, tmp_path):
        """Test getting thread statistics."""
        config = SootheConfig(persistence={"persist_dir": str(tmp_path)})
        durability = JsonDurability(str(tmp_path))
        manager = ThreadContextManager(durability, config)

        # Create thread
        thread = await manager.create_thread()

        # Get stats
        stats = await manager.get_thread_stats(thread.thread_id)

        assert stats.message_count >= 0
        assert stats.event_count >= 0
        assert stats.artifact_count >= 0
        assert stats.error_count >= 0
