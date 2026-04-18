"""Tests for durability implementations (JsonDurability)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from soothe.backends.durability.json import JsonDurability
from soothe.protocols.durability import ThreadFilter, ThreadMetadata


class TestJsonDurability:
    """Unit tests for JsonDurability."""

    @pytest.mark.asyncio
    async def test_initialization(self, tmp_path: Path) -> None:
        """Test initialization creates empty storage."""
        persist_dir = str(tmp_path)
        durability = JsonDurability(persist_dir=persist_dir)

        # Test public interface instead of internal implementation
        threads = await durability.list_threads()
        assert threads == []

    @pytest.mark.asyncio
    async def test_create_thread(self, tmp_path: Path) -> None:
        """Test creating a new thread."""
        persist_dir = str(tmp_path)
        durability = JsonDurability(persist_dir=persist_dir)

        metadata = ThreadMetadata(tags=["test"], plan_summary="Test Thread")
        thread = await durability.create_thread(metadata)

        assert thread.thread_id is not None
        assert thread.status == "active"
        assert thread.metadata.plan_summary == "Test Thread"
        assert thread.metadata.tags == ["test"]
        assert thread.created_at is not None
        assert thread.updated_at is not None

    @pytest.mark.asyncio
    async def test_get_thread_read_only(self, tmp_path: Path) -> None:
        """get_thread loads info without changing lifecycle status."""
        persist_dir = str(tmp_path)
        durability = JsonDurability(persist_dir=persist_dir)

        metadata = ThreadMetadata(plan_summary="Read Test")
        created = await durability.create_thread(metadata)
        await durability.suspend_thread(created.thread_id)

        loaded = await durability.get_thread(created.thread_id)
        assert loaded is not None
        assert loaded.thread_id == created.thread_id
        assert loaded.status == "suspended"

        again = await durability.list_threads()
        still = next(t for t in again if t.thread_id == created.thread_id)
        assert still.status == "suspended"

    @pytest.mark.asyncio
    async def test_get_thread_missing_returns_none(self, tmp_path: Path) -> None:
        """get_thread returns None when thread id is unknown."""
        persist_dir = str(tmp_path)
        durability = JsonDurability(persist_dir=persist_dir)
        assert await durability.get_thread("no-such-thread") is None

    @pytest.mark.asyncio
    async def test_create_thread_generates_unique_ids(self, tmp_path: Path) -> None:
        """Test that each thread gets a unique ID."""
        persist_dir = str(tmp_path)
        durability = JsonDurability(persist_dir=persist_dir)

        metadata = ThreadMetadata(plan_summary="Test")
        thread1 = await durability.create_thread(metadata)
        thread2 = await durability.create_thread(metadata)

        assert thread1.thread_id != thread2.thread_id

    @pytest.mark.asyncio
    async def test_resume_existing_thread(self, tmp_path: Path) -> None:
        """Test resuming an existing thread."""
        persist_dir = str(tmp_path)
        durability = JsonDurability(persist_dir=persist_dir)

        metadata = ThreadMetadata(plan_summary="Test Thread")
        thread = await durability.create_thread(metadata)

        # Suspend the thread
        await durability.suspend_thread(thread.thread_id)

        # Resume it
        resumed = await durability.resume_thread(thread.thread_id)

        assert resumed.status == "active"
        assert resumed.thread_id == thread.thread_id

    @pytest.mark.asyncio
    async def test_resume_nonexistent_thread_raises_error(self, tmp_path: Path) -> None:
        """Test that resuming nonexistent thread raises KeyError."""
        persist_dir = str(tmp_path)
        durability = JsonDurability(persist_dir=persist_dir)

        with pytest.raises(KeyError, match="not found"):
            await durability.resume_thread("nonexistent_id")

    @pytest.mark.asyncio
    async def test_suspend_thread(self, tmp_path: Path) -> None:
        """Test suspending a thread."""
        persist_dir = str(tmp_path)
        durability = JsonDurability(persist_dir=persist_dir)

        metadata = ThreadMetadata(plan_summary="Test Thread")
        thread = await durability.create_thread(metadata)

        await durability.suspend_thread(thread.thread_id)

        # Check the thread is suspended
        threads = await durability.list_threads()
        suspended_thread = next(t for t in threads if t.thread_id == thread.thread_id)
        assert suspended_thread.status == "suspended"

    @pytest.mark.asyncio
    async def test_suspend_nonexistent_thread_no_error(self, tmp_path: Path) -> None:
        """Test that suspending nonexistent thread doesn't raise error."""
        persist_dir = str(tmp_path)
        durability = JsonDurability(persist_dir=persist_dir)

        # Should not raise an error
        await durability.suspend_thread("nonexistent_id")

    @pytest.mark.asyncio
    async def test_archive_thread(self, tmp_path: Path) -> None:
        """Test archiving a thread."""
        persist_dir = str(tmp_path)
        durability = JsonDurability(persist_dir=persist_dir)

        metadata = ThreadMetadata(plan_summary="Test Thread")
        thread = await durability.create_thread(metadata)

        await durability.archive_thread(thread.thread_id)

        # Check the thread is archived
        threads = await durability.list_threads()
        archived_thread = next(t for t in threads if t.thread_id == thread.thread_id)
        assert archived_thread.status == "archived"

    @pytest.mark.asyncio
    async def test_archive_nonexistent_thread_no_error(self, tmp_path: Path) -> None:
        """Test that archiving nonexistent thread doesn't raise error."""
        persist_dir = str(tmp_path)
        durability = JsonDurability(persist_dir=persist_dir)

        # Should not raise an error
        await durability.archive_thread("nonexistent_id")

    @pytest.mark.asyncio
    async def test_list_threads_no_filter(self, tmp_path: Path) -> None:
        """Test listing all threads without filter."""
        persist_dir = str(tmp_path)
        durability = JsonDurability(persist_dir=persist_dir)

        metadata1 = ThreadMetadata(plan_summary="Thread 1")
        metadata2 = ThreadMetadata(plan_summary="Thread 2")

        thread1 = await durability.create_thread(metadata1)
        thread2 = await durability.create_thread(metadata2)

        threads = await durability.list_threads()

        assert len(threads) == 2
        thread_ids = {t.thread_id for t in threads}
        assert thread1.thread_id in thread_ids
        assert thread2.thread_id in thread_ids

    @pytest.mark.asyncio
    async def test_list_threads_filter_by_status(self, tmp_path: Path) -> None:
        """Test listing threads filtered by status."""
        persist_dir = str(tmp_path)
        durability = JsonDurability(persist_dir=persist_dir)

        metadata1 = ThreadMetadata(plan_summary="Thread 1")
        metadata2 = ThreadMetadata(plan_summary="Thread 2")

        thread1 = await durability.create_thread(metadata1)
        thread2 = await durability.create_thread(metadata2)

        # Suspend one thread
        await durability.suspend_thread(thread2.thread_id)

        # Filter by active status
        filter_active = ThreadFilter(status="active")
        active_threads = await durability.list_threads(thread_filter=filter_active)

        assert len(active_threads) == 1
        assert active_threads[0].thread_id == thread1.thread_id

        # Filter by suspended status
        filter_suspended = ThreadFilter(status="suspended")
        suspended_threads = await durability.list_threads(thread_filter=filter_suspended)

        assert len(suspended_threads) == 1
        assert suspended_threads[0].thread_id == thread2.thread_id

    @pytest.mark.asyncio
    async def test_list_threads_filter_by_tags(self, tmp_path: Path) -> None:
        """Test listing threads filtered by tags."""
        persist_dir = str(tmp_path)
        durability = JsonDurability(persist_dir=persist_dir)

        metadata1 = ThreadMetadata(plan_summary="Thread 1", tags=["python", "test"])
        metadata2 = ThreadMetadata(plan_summary="Thread 2", tags=["java", "test"])

        thread1 = await durability.create_thread(metadata1)
        await durability.create_thread(metadata2)

        # Filter by tag
        filter_tags = ThreadFilter(tags=["python"])
        python_threads = await durability.list_threads(thread_filter=filter_tags)

        assert len(python_threads) == 1
        assert python_threads[0].thread_id == thread1.thread_id

    @pytest.mark.asyncio
    async def test_list_threads_filter_by_date_range(self, tmp_path: Path) -> None:
        """Test listing threads filtered by creation date."""
        persist_dir = str(tmp_path)
        durability = JsonDurability(persist_dir=persist_dir)

        metadata = ThreadMetadata(plan_summary="Test")
        await durability.create_thread(metadata)

        # Filter after creation (using timezone-aware datetime)
        filter_after = ThreadFilter(created_after=datetime.now(UTC) - timedelta(hours=1))
        recent_threads = await durability.list_threads(thread_filter=filter_after)

        assert len(recent_threads) == 1

        # Filter before creation
        filter_before = ThreadFilter(created_before=datetime.now(UTC) - timedelta(hours=1))
        old_threads = await durability.list_threads(thread_filter=filter_before)

        assert len(old_threads) == 0

    @pytest.mark.asyncio
    async def test_list_threads_combined_filters(self, tmp_path: Path) -> None:
        """Test listing threads with combined filters."""
        persist_dir = str(tmp_path)
        durability = JsonDurability(persist_dir=persist_dir)

        metadata1 = ThreadMetadata(plan_summary="Thread 1", tags=["python"])
        metadata2 = ThreadMetadata(plan_summary="Thread 2", tags=["java"])

        thread1 = await durability.create_thread(metadata1)
        thread2 = await durability.create_thread(metadata2)

        # Suspend one
        await durability.suspend_thread(thread2.thread_id)

        # Combined filter
        combined_filter = ThreadFilter(status="active", tags=["python"])
        filtered_threads = await durability.list_threads(thread_filter=combined_filter)

        assert len(filtered_threads) == 1
        assert filtered_threads[0].thread_id == thread1.thread_id

    @pytest.mark.asyncio
    async def test_thread_updated_at_changes(self, tmp_path: Path) -> None:
        """Test that updated_at timestamp changes on modifications."""
        persist_dir = str(tmp_path)
        durability = JsonDurability(persist_dir=persist_dir)

        metadata = ThreadMetadata(plan_summary="Test Thread")
        thread = await durability.create_thread(metadata)
        original_updated_at = thread.updated_at

        # Suspend and resume
        await durability.suspend_thread(thread.thread_id)
        resumed = await durability.resume_thread(thread.thread_id)

        assert resumed.updated_at > original_updated_at

    @pytest.mark.asyncio
    async def test_persistence_across_restarts(self, tmp_path: Path) -> None:
        """Test that data persists across durability restarts."""
        persist_dir = str(tmp_path)

        # Create thread with first instance
        durability1 = JsonDurability(persist_dir=persist_dir)
        metadata = ThreadMetadata(plan_summary="Persistent Thread", tags=["test"])
        thread1 = await durability1.create_thread(metadata)

        # Create new instance with same path
        durability2 = JsonDurability(persist_dir=persist_dir)
        threads = await durability2.list_threads()

        assert len(threads) == 1
        assert threads[0].thread_id == thread1.thread_id
        assert threads[0].metadata.plan_summary == "Persistent Thread"
