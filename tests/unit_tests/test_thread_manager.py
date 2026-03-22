"""Tests for ThreadContextManager (RFC-0017)."""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from soothe.core.thread import (
    ThreadContextManager,
    ThreadFilter,
    ThreadStats,
    EnhancedThreadInfo,
)
from soothe.protocols.durability import ThreadMetadata


@pytest.fixture
def mock_durability():
    """Create mock DurabilityProtocol."""
    from unittest.mock import AsyncMock, MagicMock

    durability = MagicMock()
    durability.create_thread = AsyncMock(
        return_value=MagicMock(
            thread_id="test123",
            status="idle",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            metadata=ThreadMetadata(),
        )
    )
    durability.resume_thread = AsyncMock(
        return_value=MagicMock(
            thread_id="test123",
            status="idle",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            metadata=ThreadMetadata(),
        )
    )
    durability.list_threads = AsyncMock(return_value=[])
    durability.archive_thread = AsyncMock()
    return durability


@pytest.fixture
def mock_config():
    """Create mock SootheConfig."""
    from unittest.mock import MagicMock

    config = MagicMock()
    config.persistence = MagicMock()
    config.persistence.persist_dir = "/tmp/test_soothe"
    return config


@pytest.mark.asyncio
async def test_create_thread(mock_durability, mock_config):
    """Test thread creation."""
    manager = ThreadContextManager(mock_durability, mock_config)

    thread_info = await manager.create_thread()

    assert thread_info.thread_id == "test123"
    assert thread_info.status == "idle"
    mock_durability.create_thread.assert_called_once()


@pytest.mark.asyncio
async def test_create_thread_with_metadata(mock_durability, mock_config):
    """Test thread creation with metadata."""
    manager = ThreadContextManager(mock_durability, mock_config)

    metadata = {"tags": ["research"], "priority": "high"}
    thread_info = await manager.create_thread(metadata=metadata)

    assert thread_info.thread_id == "test123"
    mock_durability.create_thread.assert_called_once()


@pytest.mark.asyncio
async def test_resume_thread(mock_durability, mock_config):
    """Test thread resume loads history."""
    manager = ThreadContextManager(mock_durability, mock_config)

    resumed = await manager.resume_thread("test123")

    assert resumed.thread_id == "test123"
    mock_durability.resume_thread.assert_called_once_with("test123")


@pytest.mark.asyncio
async def test_list_threads_with_filter(mock_durability, mock_config):
    """Test thread filtering."""
    mock_durability.list_threads = AsyncMock(
        return_value=[
            {
                "thread_id": "thread1",
                "status": "idle",
                "created_at": "2026-03-22T10:00:00",
                "updated_at": "2026-03-22T12:00:00",
                "metadata": {"tags": ["research"]},
            },
            {
                "thread_id": "thread2",
                "status": "idle",
                "created_at": "2026-03-22T11:00:00",
                "updated_at": "2026-03-22T13:00:00",
                "metadata": {"tags": ["analysis"]},
            },
        ]
    )

    manager = ThreadContextManager(mock_durability, mock_config)

    filter = ThreadFilter(tags=["research"])
    threads = await manager.list_threads(filter=filter)

    assert len(threads) == 1
    assert threads[0].thread_id == "thread1"


@pytest.mark.asyncio
async def test_get_thread_stats(mock_durability, mock_config):
    """Test statistics calculation."""
    from unittest.mock import MagicMock, patch

    mock_durability.list_threads = AsyncMock(
        return_value=[
            {
                "thread_id": "test123",
                "status": "idle",
                "created_at": "2026-03-22T10:00:00",
                "updated_at": "2026-03-22T12:00:00",
                "metadata": {},
            },
        ]
    )

    manager = ThreadContextManager(mock_durability, mock_config)

    # Mock ThreadLogger
    with patch("soothe.core.thread.manager.ThreadLogger") as mock_logger_class:
        mock_logger = MagicMock()
        mock_logger.read_recent_records.return_value = [
            {"kind": "conversation", "text": "Hello"},
            {"kind": "event", "data": {}},
        ]
        mock_logger_class.return_value = mock_logger

        stats = await manager.get_thread_stats("test123")

    assert stats.message_count == 1
    assert stats.event_count == 1
    assert stats.artifact_count == 0
    assert stats.error_count == 0


@pytest.mark.asyncio
async def test_archive_thread(mock_durability, mock_config):
    """Test thread archival."""
    manager = ThreadContextManager(mock_durability, mock_config)

    await manager.archive_thread("test123")

    mock_durability.archive_thread.assert_called_once_with("test123")


@pytest.mark.asyncio
async def test_delete_thread(mock_durability, mock_config, tmp_path):
    """Test thread deletion cleans up all data."""
    from unittest.mock import patch

    # Create a mock run directory
    run_dir = tmp_path / "runs" / "test123"
    run_dir.mkdir(parents=True)
    (run_dir / "test.txt").write_text("test")

    manager = ThreadContextManager(mock_durability, mock_config)

    with patch("soothe.core.thread.manager.SOOTHE_HOME", str(tmp_path)):
        await manager.delete_thread("test123")

    mock_durability.archive_thread.assert_called_once_with("test123")
    assert not run_dir.exists()


@pytest.mark.asyncio
async def test_thread_filter_by_status(mock_durability, mock_config):
    """Test filtering threads by status."""
    mock_durability.list_threads = AsyncMock(
        return_value=[
            {
                "thread_id": "t1",
                "status": "idle",
                "created_at": "2026-03-22T10:00:00",
                "updated_at": "2026-03-22T11:00:00",
                "metadata": {},
            },
            {
                "thread_id": "t2",
                "status": "running",
                "created_at": "2026-03-22T10:00:00",
                "updated_at": "2026-03-22T11:00:00",
                "metadata": {},
            },
            {
                "thread_id": "t3",
                "status": "idle",
                "created_at": "2026-03-22T10:00:00",
                "updated_at": "2026-03-22T11:00:00",
                "metadata": {},
            },
        ]
    )

    manager = ThreadContextManager(mock_durability, mock_config)

    filter = ThreadFilter(status="idle")
    threads = await manager.list_threads(filter=filter)

    assert len(threads) == 2
    assert all(t.status == "idle" for t in threads)


@pytest.mark.asyncio
async def test_thread_filter_by_date_range(mock_durability, mock_config):
    """Test filtering threads by date range."""
    mock_durability.list_threads = AsyncMock(
        return_value=[
            {
                "thread_id": "t1",
                "status": "idle",
                "created_at": "2026-03-20T10:00:00",
                "updated_at": "2026-03-20T11:00:00",
                "metadata": {},
            },
            {
                "thread_id": "t2",
                "status": "idle",
                "created_at": "2026-03-22T10:00:00",
                "updated_at": "2026-03-22T11:00:00",
                "metadata": {},
            },
            {
                "thread_id": "t3",
                "status": "idle",
                "created_at": "2026-03-24T10:00:00",
                "updated_at": "2026-03-24T11:00:00",
                "metadata": {},
            },
        ]
    )

    manager = ThreadContextManager(mock_durability, mock_config)

    filter = ThreadFilter(
        created_after=datetime(2026, 3, 21, 0, 0),
        created_before=datetime(2026, 3, 23, 23, 59),
    )
    threads = await manager.list_threads(filter=filter)

    assert len(threads) == 1
    assert threads[0].thread_id == "t2"
