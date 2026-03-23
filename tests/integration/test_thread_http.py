"""Integration tests for RFC-0017 thread management via HTTP REST API."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest
from httpx import AsyncClient

from soothe.config import SootheConfig
from soothe.daemon import SootheDaemon


@pytest.fixture
async def daemon_with_http(tmp_path: Path):
    """Create and start a daemon server with HTTP REST enabled."""
    config = SootheConfig(
        persistence={"persist_dir": str(tmp_path / "persistence")},
        daemon={
            "enabled": True,
            "transports": {
                "unix_socket": {"enabled": True, "path": str(tmp_path / "test.sock")},
                "websocket": {"enabled": False},
                "http_rest": {
                    "enabled": True,
                    "host": "127.0.0.1",
                    "port": 18766,  # Use non-standard port for testing
                    "cors_origins": ["*"],
                    "tls_enabled": False,
                },
            },
        },
    )

    daemon = SootheDaemon(config)
    await daemon.start()

    # Give daemon time to initialize HTTP server
    await asyncio.sleep(1.0)

    yield daemon

    # Cleanup
    try:
        await daemon.stop()
    except Exception:
        pass


@pytest.fixture
async def http_client(daemon_with_http):
    """Create an HTTP client for testing REST API."""
    async with AsyncClient(base_url="http://127.0.0.1:18766", timeout=10.0) as client:
        yield client


@pytest.mark.asyncio
class TestThreadHTTPRest:
    """Test thread management via HTTP REST API (RFC-0017)."""

    async def test_health_check(self, http_client):
        """Test health check endpoint."""
        response = await http_client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "healthy"
        assert data.get("transport") == "http_rest"

    async def test_create_thread(self, http_client):
        """Test thread creation via HTTP POST."""
        response = await http_client.post(
            "/api/v1/threads",
            json={
                "metadata": {
                    "tags": ["test", "http"],
                    "priority": "high",
                    "category": "integration-test",
                }
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "thread_id" in data
        assert "status" in data
        assert "created_at" in data

        thread_id = data["thread_id"]
        assert isinstance(thread_id, str)
        assert len(thread_id) > 0

    async def test_create_thread_with_initial_message(self, http_client):
        """Test thread creation with initial message."""
        response = await http_client.post(
            "/api/v1/threads",
            json={
                "initial_message": "Hello from HTTP REST",
                "metadata": {"tags": ["test"]},
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "thread_id" in data

    async def test_get_thread(self, http_client):
        """Test getting thread details via HTTP GET."""
        # Create a thread first
        create_response = await http_client.post(
            "/api/v1/threads",
            json={"metadata": {"tags": ["test"], "priority": "normal"}},
        )
        thread_id = create_response.json()["thread_id"]

        # Get thread details
        response = await http_client.get(f"/api/v1/threads/{thread_id}")

        assert response.status_code == 200
        data = response.json()
        assert "thread" in data

        thread = data["thread"]
        assert thread.get("thread_id") == thread_id
        assert "status" in thread
        assert "metadata" in thread
        assert "created_at" in thread
        assert "updated_at" in thread
        assert "stats" in thread

    async def test_get_thread_not_found(self, http_client):
        """Test getting non-existent thread returns 404."""
        response = await http_client.get("/api/v1/threads/nonexistent123")

        assert response.status_code == 404
        data = response.json()
        assert "detail" in data

    async def test_list_threads(self, http_client):
        """Test listing threads via HTTP GET."""
        # Create multiple threads
        for i in range(3):
            await http_client.post(
                "/api/v1/threads",
                json={"metadata": {"tags": [f"test{i}"], "priority": "normal"}},
            )

        # List all threads
        response = await http_client.get("/api/v1/threads")

        assert response.status_code == 200
        data = response.json()
        assert "threads" in data
        assert "total" in data
        assert "limit" in data
        assert "offset" in data

        threads = data["threads"]
        assert isinstance(threads, list)
        assert len(threads) >= 3

    async def test_list_threads_with_filter(self, http_client):
        """Test listing threads with query parameters."""
        # Create threads with different priorities
        await http_client.post(
            "/api/v1/threads",
            json={"metadata": {"priority": "high"}},
        )

        await http_client.post(
            "/api/v1/threads",
            json={"metadata": {"priority": "low"}},
        )

        # Filter by priority
        response = await http_client.get("/api/v1/threads?priority=high")

        assert response.status_code == 200
        data = response.json()
        threads = data["threads"]

        assert all(t.get("metadata", {}).get("priority") == "high" for t in threads)

    async def test_list_threads_with_pagination(self, http_client):
        """Test listing threads with pagination."""
        # Create multiple threads
        for i in range(5):
            await http_client.post(
                "/api/v1/threads",
                json={"metadata": {"tags": [f"page{i}"]}},
            )

        # Get first page
        response = await http_client.get("/api/v1/threads?limit=2&offset=0")

        assert response.status_code == 200
        data = response.json()
        assert data["limit"] == 2
        assert data["offset"] == 0
        assert len(data["threads"]) <= 2

    async def test_list_threads_with_stats(self, http_client):
        """Test listing threads with statistics."""
        # Create a thread
        await http_client.post(
            "/api/v1/threads",
            json={"metadata": {"tags": ["test"]}},
        )

        # List with stats
        response = await http_client.get("/api/v1/threads?include_stats=true")

        assert response.status_code == 200
        data = response.json()
        threads = data["threads"]

        assert len(threads) > 0
        for thread in threads:
            assert "stats" in thread
            stats = thread.get("stats", {})
            assert "message_count" in stats
            assert "event_count" in stats

    async def test_archive_thread(self, http_client):
        """Test archiving a thread via HTTP DELETE."""
        # Create a thread
        create_response = await http_client.post(
            "/api/v1/threads",
            json={"metadata": {"tags": ["test"]}},
        )
        thread_id = create_response.json()["thread_id"]

        # Archive thread
        response = await http_client.delete(f"/api/v1/threads/{thread_id}?archive=true")

        assert response.status_code == 200
        data = response.json()
        assert data.get("thread_id") == thread_id
        assert data.get("status") == "archived"

        # Verify thread is archived
        get_response = await http_client.get(f"/api/v1/threads/{thread_id}")
        thread = get_response.json()["thread"]
        assert thread.get("status") == "archived"

    async def test_delete_thread(self, http_client):
        """Test permanently deleting a thread via HTTP DELETE."""
        # Create a thread
        create_response = await http_client.post(
            "/api/v1/threads",
            json={"metadata": {"tags": ["test"]}},
        )
        thread_id = create_response.json()["thread_id"]

        # Delete thread (not archive)
        response = await http_client.delete(f"/api/v1/threads/{thread_id}?archive=false")

        assert response.status_code == 200
        data = response.json()
        assert data.get("thread_id") == thread_id
        assert data.get("status") == "deleted"

        # Verify thread no longer exists
        get_response = await http_client.get(f"/api/v1/threads/{thread_id}")
        assert get_response.status_code == 404

    async def test_get_thread_messages(self, http_client):
        """Test getting thread messages via HTTP GET."""
        # Create a thread
        create_response = await http_client.post(
            "/api/v1/threads",
            json={"metadata": {"tags": ["test"]}},
        )
        thread_id = create_response.json()["thread_id"]

        # Get messages
        response = await http_client.get(f"/api/v1/threads/{thread_id}/messages?limit=100&offset=0")

        assert response.status_code == 200
        data = response.json()
        assert data.get("thread_id") == thread_id
        assert "messages" in data
        assert "limit" in data
        assert "offset" in data
        assert isinstance(data.get("messages"), list)

    async def test_get_thread_artifacts(self, http_client):
        """Test getting thread artifacts via HTTP GET."""
        # Create a thread
        create_response = await http_client.post(
            "/api/v1/threads",
            json={"metadata": {"tags": ["test"]}},
        )
        thread_id = create_response.json()["thread_id"]

        # Get artifacts
        response = await http_client.get(f"/api/v1/threads/{thread_id}/artifacts")

        assert response.status_code == 200
        data = response.json()
        assert data.get("thread_id") == thread_id
        assert "artifacts" in data
        assert isinstance(data.get("artifacts"), list)

    async def test_get_thread_stats(self, http_client):
        """Test getting thread statistics via HTTP GET."""
        # Create a thread
        create_response = await http_client.post(
            "/api/v1/threads",
            json={"metadata": {"tags": ["test"]}},
        )
        thread_id = create_response.json()["thread_id"]

        # Get stats
        response = await http_client.get(f"/api/v1/threads/{thread_id}/stats")

        assert response.status_code == 200
        data = response.json()
        assert data.get("thread_id") == thread_id
        assert "stats" in data

        stats = data["stats"]
        assert "message_count" in stats
        assert "event_count" in stats
        assert "artifact_count" in stats
        assert "error_count" in stats

    async def test_thread_lifecycle_full(self, http_client):
        """Test complete thread lifecycle via HTTP REST."""
        # 1. Create thread
        create_response = await http_client.post(
            "/api/v1/threads",
            json={
                "metadata": {
                    "tags": ["lifecycle", "test"],
                    "priority": "high",
                    "category": "integration-test",
                }
            },
        )
        assert create_response.status_code == 200
        thread_id = create_response.json()["thread_id"]

        # 2. Get thread details
        get_response = await http_client.get(f"/api/v1/threads/{thread_id}")
        assert get_response.status_code == 200
        thread = get_response.json()["thread"]
        assert thread.get("metadata", {}).get("priority") == "high"

        # 3. Get thread stats
        stats_response = await http_client.get(f"/api/v1/threads/{thread_id}/stats")
        assert stats_response.status_code == 200
        stats = stats_response.json()["stats"]
        assert "message_count" in stats

        # 4. Get thread messages
        messages_response = await http_client.get(f"/api/v1/threads/{thread_id}/messages")
        assert messages_response.status_code == 200

        # 5. Get thread artifacts
        artifacts_response = await http_client.get(f"/api/v1/threads/{thread_id}/artifacts")
        assert artifacts_response.status_code == 200

        # 6. Archive thread
        archive_response = await http_client.delete(f"/api/v1/threads/{thread_id}?archive=true")
        assert archive_response.status_code == 200
        assert archive_response.json()["status"] == "archived"

        # 7. Verify archived status
        final_response = await http_client.get(f"/api/v1/threads/{thread_id}")
        thread = final_response.json()["thread"]
        assert thread.get("status") == "archived"

    async def test_resume_thread(self, http_client):
        """Test resuming a thread with a new message."""
        # Create a thread
        create_response = await http_client.post(
            "/api/v1/threads",
            json={"metadata": {"tags": ["test"]}},
        )
        thread_id = create_response.json()["thread_id"]

        # Resume thread with message
        response = await http_client.post(
            f"/api/v1/threads/{thread_id}/resume",
            json={"message": "Continue the conversation"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data.get("thread_id") == thread_id
        assert data.get("status") == "resumed"

    async def test_resume_thread_missing_message(self, http_client):
        """Test resuming thread without message returns error."""
        # Create a thread
        create_response = await http_client.post(
            "/api/v1/threads",
            json={"metadata": {"tags": ["test"]}},
        )
        thread_id = create_response.json()["thread_id"]

        # Try to resume without message
        response = await http_client.post(
            f"/api/v1/threads/{thread_id}/resume",
            json={},
        )

        assert response.status_code == 400

    async def test_filter_by_date_range(self, http_client):
        """Test filtering threads by date range."""
        # Create a thread
        await http_client.post(
            "/api/v1/threads",
            json={"metadata": {"tags": ["date-test"]}},
        )

        # Filter by created_after
        response = await http_client.get("/api/v1/threads?created_after=2020-01-01T00:00:00")

        assert response.status_code == 200
        data = response.json()
        assert "threads" in data

    async def test_filter_by_tags(self, http_client):
        """Test filtering threads by tags."""
        # Create threads with specific tags
        await http_client.post(
            "/api/v1/threads",
            json={"metadata": {"tags": ["research", "ai"]}},
        )

        await http_client.post(
            "/api/v1/threads",
            json={"metadata": {"tags": ["analysis", "data"]}},
        )

        # Filter by tag
        response = await http_client.get("/api/v1/threads?tags=research")

        assert response.status_code == 200
        data = response.json()

        # All returned threads should have "research" tag
        for thread in data["threads"]:
            tags = thread.get("metadata", {}).get("tags", [])
            assert "research" in tags

    async def test_filter_by_labels(self, http_client):
        """Test filtering threads by labels."""
        # Create thread with labels
        await http_client.post(
            "/api/v1/threads",
            json={"metadata": {"labels": ["important", "urgent"]}},
        )

        # Filter by label
        response = await http_client.get("/api/v1/threads?labels=important")

        assert response.status_code == 200
        data = response.json()

        # All returned threads should have "important" label
        for thread in data["threads"]:
            labels = thread.get("metadata", {}).get("labels", [])
            assert "important" in labels

    async def test_filter_by_category(self, http_client):
        """Test filtering threads by category."""
        # Create threads with different categories
        await http_client.post(
            "/api/v1/threads",
            json={"metadata": {"category": "code-review"}},
        )

        await http_client.post(
            "/api/v1/threads",
            json={"metadata": {"category": "research"}},
        )

        # Filter by category
        response = await http_client.get("/api/v1/threads?category=code-review")

        assert response.status_code == 200
        data = response.json()

        # All returned threads should have "code-review" category
        for thread in data["threads"]:
            category = thread.get("metadata", {}).get("category")
            assert category == "code-review"

    async def test_combined_filters(self, http_client):
        """Test combining multiple filters."""
        # Create threads with various metadata
        await http_client.post(
            "/api/v1/threads",
            json={
                "metadata": {
                    "tags": ["research"],
                    "priority": "high",
                    "category": "analysis",
                }
            },
        )

        await http_client.post(
            "/api/v1/threads",
            json={
                "metadata": {
                    "tags": ["research"],
                    "priority": "low",
                    "category": "analysis",
                }
            },
        )

        # Filter by multiple criteria
        response = await http_client.get("/api/v1/threads?tags=research&priority=high&category=analysis")

        assert response.status_code == 200
        data = response.json()

        # All returned threads should match all filters
        for thread in data["threads"]:
            metadata = thread.get("metadata", {})
            assert "research" in metadata.get("tags", [])
            assert metadata.get("priority") == "high"
            assert metadata.get("category") == "analysis"
