"""Tests for durability implementation (InMemoryDurability)."""

from datetime import UTC, datetime, timedelta

import pytest

from soothe.durability.in_memory import InMemoryDurability
from soothe.protocols.durability import ThreadFilter, ThreadMetadata


class TestInMemoryDurability:
    """Unit tests for InMemoryDurability."""

    def test_initialization(self):
        """Test initialization creates empty storage."""
        durability = InMemoryDurability()

        assert durability._threads == {}
        assert durability._state == {}

    @pytest.mark.asyncio
    async def test_create_thread(self):
        """Test creating a new thread."""
        durability = InMemoryDurability()

        metadata = ThreadMetadata(tags=["test"], plan_summary="Test Thread")
        thread = await durability.create_thread(metadata)

        assert thread.thread_id is not None
        assert thread.status == "active"
        assert thread.metadata.plan_summary == "Test Thread"
        assert thread.metadata.tags == ["test"]
        assert thread.created_at is not None
        assert thread.updated_at is not None

    @pytest.mark.asyncio
    async def test_create_thread_generates_unique_ids(self):
        """Test that each thread gets a unique ID."""
        durability = InMemoryDurability()

        metadata = ThreadMetadata(plan_summary="Test")
        thread1 = await durability.create_thread(metadata)
        thread2 = await durability.create_thread(metadata)

        assert thread1.thread_id != thread2.thread_id

    @pytest.mark.asyncio
    async def test_resume_existing_thread(self):
        """Test resuming an existing thread."""
        durability = InMemoryDurability()

        metadata = ThreadMetadata(plan_summary="Test Thread")
        thread = await durability.create_thread(metadata)

        # Suspend the thread
        await durability.suspend_thread(thread.thread_id)

        # Resume it
        resumed = await durability.resume_thread(thread.thread_id)

        assert resumed.status == "active"
        assert resumed.thread_id == thread.thread_id

    @pytest.mark.asyncio
    async def test_resume_nonexistent_thread_raises_error(self):
        """Test that resuming nonexistent thread raises KeyError."""
        durability = InMemoryDurability()

        with pytest.raises(KeyError, match="not found"):
            await durability.resume_thread("nonexistent_id")

    @pytest.mark.asyncio
    async def test_suspend_thread(self):
        """Test suspending a thread."""
        durability = InMemoryDurability()

        metadata = ThreadMetadata(plan_summary="Test Thread")
        thread = await durability.create_thread(metadata)

        await durability.suspend_thread(thread.thread_id)

        # Check the thread is suspended
        threads = await durability.list_threads()
        suspended_thread = next(t for t in threads if t.thread_id == thread.thread_id)
        assert suspended_thread.status == "suspended"

    @pytest.mark.asyncio
    async def test_suspend_nonexistent_thread_no_error(self):
        """Test that suspending nonexistent thread doesn't raise error."""
        durability = InMemoryDurability()

        # Should not raise an error
        await durability.suspend_thread("nonexistent_id")

    @pytest.mark.asyncio
    async def test_archive_thread(self):
        """Test archiving a thread."""
        durability = InMemoryDurability()

        metadata = ThreadMetadata(plan_summary="Test Thread")
        thread = await durability.create_thread(metadata)

        await durability.archive_thread(thread.thread_id)

        # Check the thread is archived
        threads = await durability.list_threads()
        archived_thread = next(t for t in threads if t.thread_id == thread.thread_id)
        assert archived_thread.status == "archived"

    @pytest.mark.asyncio
    async def test_archive_nonexistent_thread_no_error(self):
        """Test that archiving nonexistent thread doesn't raise error."""
        durability = InMemoryDurability()

        # Should not raise an error
        await durability.archive_thread("nonexistent_id")

    @pytest.mark.asyncio
    async def test_list_threads_no_filter(self):
        """Test listing all threads without filter."""
        durability = InMemoryDurability()

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
    async def test_list_threads_filter_by_status(self):
        """Test listing threads filtered by status."""
        durability = InMemoryDurability()

        metadata1 = ThreadMetadata(plan_summary="Thread 1")
        metadata2 = ThreadMetadata(plan_summary="Thread 2")

        thread1 = await durability.create_thread(metadata1)
        thread2 = await durability.create_thread(metadata2)

        # Suspend one thread
        await durability.suspend_thread(thread2.thread_id)

        # Filter by active status
        filter_active = ThreadFilter(status="active")
        active_threads = await durability.list_threads(filter=filter_active)

        assert len(active_threads) == 1
        assert active_threads[0].thread_id == thread1.thread_id

        # Filter by suspended status
        filter_suspended = ThreadFilter(status="suspended")
        suspended_threads = await durability.list_threads(filter=filter_suspended)

        assert len(suspended_threads) == 1
        assert suspended_threads[0].thread_id == thread2.thread_id

    @pytest.mark.asyncio
    async def test_list_threads_filter_by_tags(self):
        """Test listing threads filtered by tags."""
        durability = InMemoryDurability()

        metadata1 = ThreadMetadata(plan_summary="Thread 1", tags=["python", "test"])
        metadata2 = ThreadMetadata(plan_summary="Thread 2", tags=["java", "test"])

        thread1 = await durability.create_thread(metadata1)
        thread2 = await durability.create_thread(metadata2)

        # Filter by tag
        filter_tags = ThreadFilter(tags=["python"])
        python_threads = await durability.list_threads(filter=filter_tags)

        assert len(python_threads) == 1
        assert python_threads[0].thread_id == thread1.thread_id

    @pytest.mark.asyncio
    async def test_list_threads_filter_by_date_range(self):
        """Test listing threads filtered by creation date."""
        durability = InMemoryDurability()

        metadata = ThreadMetadata(plan_summary="Test")
        thread = await durability.create_thread(metadata)

        # Filter after creation (using timezone-aware datetime)
        filter_after = ThreadFilter(created_after=datetime.now(UTC) - timedelta(hours=1))
        recent_threads = await durability.list_threads(filter=filter_after)

        assert len(recent_threads) == 1

        # Filter before creation
        filter_before = ThreadFilter(created_before=datetime.now(UTC) - timedelta(hours=1))
        old_threads = await durability.list_threads(filter=filter_before)

        assert len(old_threads) == 0

    @pytest.mark.asyncio
    async def test_list_threads_combined_filters(self):
        """Test listing threads with combined filters."""
        durability = InMemoryDurability()

        metadata1 = ThreadMetadata(plan_summary="Thread 1", tags=["python"])
        metadata2 = ThreadMetadata(plan_summary="Thread 2", tags=["java"])

        thread1 = await durability.create_thread(metadata1)
        thread2 = await durability.create_thread(metadata2)

        # Suspend one
        await durability.suspend_thread(thread2.thread_id)

        # Combined filter
        combined_filter = ThreadFilter(status="active", tags=["python"])
        filtered_threads = await durability.list_threads(filter=combined_filter)

        assert len(filtered_threads) == 1
        assert filtered_threads[0].thread_id == thread1.thread_id

    @pytest.mark.asyncio
    async def test_save_and_load_state(self):
        """Test saving and loading thread state."""
        durability = InMemoryDurability()

        metadata = ThreadMetadata(plan_summary="Test Thread")
        thread = await durability.create_thread(metadata)

        state = {"step": 1, "data": "test data"}
        await durability.save_state(thread.thread_id, state)

        loaded_state = await durability.load_state(thread.thread_id)

        assert loaded_state == state

    @pytest.mark.asyncio
    async def test_load_state_nonexistent_thread(self):
        """Test loading state for nonexistent thread returns None."""
        durability = InMemoryDurability()

        state = await durability.load_state("nonexistent_id")

        assert state is None

    @pytest.mark.asyncio
    async def test_save_state_overwrites(self):
        """Test that saving state overwrites previous state."""
        durability = InMemoryDurability()

        metadata = ThreadMetadata(plan_summary="Test Thread")
        thread = await durability.create_thread(metadata)

        state1 = {"version": 1}
        state2 = {"version": 2}

        await durability.save_state(thread.thread_id, state1)
        await durability.save_state(thread.thread_id, state2)

        loaded_state = await durability.load_state(thread.thread_id)

        assert loaded_state == state2

    @pytest.mark.asyncio
    async def test_thread_updated_at_changes(self):
        """Test that updated_at timestamp changes on modifications."""
        durability = InMemoryDurability()

        metadata = ThreadMetadata(plan_summary="Test Thread")
        thread = await durability.create_thread(metadata)
        original_updated_at = thread.updated_at

        # Suspend and resume
        await durability.suspend_thread(thread.thread_id)
        resumed = await durability.resume_thread(thread.thread_id)

        assert resumed.updated_at > original_updated_at
