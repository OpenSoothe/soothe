"""Tests for ThreadContextManager (RFC-0017)."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe.core.thread import (
    EnhancedThreadInfo,
    ThreadContextManager,
    ThreadFilter,
    ThreadStats,
)
from soothe.protocols.durability import ThreadInfo, ThreadMetadata


@pytest.fixture
def mock_durability():
    """Create mock DurabilityProtocol."""
    from unittest.mock import AsyncMock

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
async def test_resume_thread_recovers_missing_metadata(mock_durability, mock_config, tmp_path):
    """If durability misses metadata but run artifacts exist, recover thread metadata."""
    from pathlib import Path
    from types import SimpleNamespace

    mock_durability.resume_thread = AsyncMock(side_effect=KeyError("missing"))
    mock_store = SimpleNamespace(save=MagicMock())
    mock_durability._store = mock_store  # noqa: SLF001
    mock_durability._update_thread_index = MagicMock()  # noqa: SLF001

    run_dir = tmp_path / "runs" / "recover-123"
    run_dir.mkdir(parents=True)
    (run_dir / "checkpoint.json").write_text("{}", encoding="utf-8")

    manager = ThreadContextManager(mock_durability, mock_config)
    with patch("soothe.core.thread.manager.SOOTHE_HOME", str(tmp_path)):
        recovered = await manager.resume_thread("recover-123")

    assert recovered.thread_id == "recover-123"
    assert recovered.status == "active"
    mock_store.save.assert_called_once()
    mock_durability._update_thread_index.assert_called_once_with("recover-123", action="add")


@pytest.mark.asyncio
async def test_list_threads_with_filter(mock_durability, mock_config):
    """Test thread filtering."""
    from soothe.protocols.durability import ThreadMetadata

    mock_durability.list_threads = AsyncMock(
        return_value=[
            ThreadInfo(
                thread_id="thread1",
                status="active",
                created_at=datetime(2026, 3, 22, 10, 0, 0, tzinfo=UTC),
                updated_at=datetime(2026, 3, 22, 12, 0, 0, tzinfo=UTC),
                metadata=ThreadMetadata(tags=["research"]),
            ),
            ThreadInfo(
                thread_id="thread2",
                status="active",
                created_at=datetime(2026, 3, 22, 11, 0, 0, tzinfo=UTC),
                updated_at=datetime(2026, 3, 22, 13, 0, 0, tzinfo=UTC),
                metadata=ThreadMetadata(tags=["analysis"]),
            ),
        ]
    )

    manager = ThreadContextManager(mock_durability, mock_config)

    thread_filter = ThreadFilter(tags=["research"])
    threads = await manager.list_threads(thread_filter=thread_filter)

    assert len(threads) == 1
    assert threads[0].thread_id == "thread1"


@pytest.mark.asyncio
async def test_get_thread_stats(mock_durability, mock_config):
    """Test statistics calculation."""
    from soothe.protocols.durability import ThreadMetadata

    mock_durability.list_threads = AsyncMock(
        return_value=[
            ThreadInfo(
                thread_id="test123",
                status="active",
                created_at=datetime(2026, 3, 22, 10, 0, 0, tzinfo=UTC),
                updated_at=datetime(2026, 3, 22, 12, 0, 0, tzinfo=UTC),
                metadata=ThreadMetadata(),
            ),
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
    from types import SimpleNamespace

    # Create a mock run directory
    run_dir = tmp_path / "runs" / "test123"
    run_dir.mkdir(parents=True)
    (run_dir / "test.txt").write_text("test")

    # Mock the internal store and its methods
    mock_store = SimpleNamespace(
        load=MagicMock(return_value={"thread_id": "test123", "status": "active"}),
        delete=MagicMock(),
    )
    mock_durability._store = mock_store  # noqa: SLF001
    mock_durability._update_thread_index = MagicMock()  # noqa: SLF001

    manager = ThreadContextManager(mock_durability, mock_config)

    with patch("soothe.core.thread.manager.SOOTHE_HOME", str(tmp_path)):
        await manager.delete_thread("test123")

    # Verify store.delete was called for thread and state
    assert mock_store.delete.call_count == 2
    mock_durability._update_thread_index.assert_called_once_with("test123", action="remove")
    assert not run_dir.exists()


@pytest.mark.asyncio
async def test_thread_filter_by_status(mock_durability, mock_config):
    """Test filtering threads by status."""
    from soothe.protocols.durability import ThreadMetadata

    mock_durability.list_threads = AsyncMock(
        return_value=[
            ThreadInfo(
                thread_id="t1",
                status="active",
                created_at=datetime(2026, 3, 22, 10, 0, 0, tzinfo=UTC),
                updated_at=datetime(2026, 3, 22, 11, 0, 0, tzinfo=UTC),
                metadata=ThreadMetadata(),
            ),
            ThreadInfo(
                thread_id="t2",
                status="suspended",
                created_at=datetime(2026, 3, 22, 10, 0, 0, tzinfo=UTC),
                updated_at=datetime(2026, 3, 22, 11, 0, 0, tzinfo=UTC),
                metadata=ThreadMetadata(),
            ),
            ThreadInfo(
                thread_id="t3",
                status="active",
                created_at=datetime(2026, 3, 22, 10, 0, 0, tzinfo=UTC),
                updated_at=datetime(2026, 3, 22, 11, 0, 0, tzinfo=UTC),
                metadata=ThreadMetadata(),
            ),
        ]
    )

    manager = ThreadContextManager(mock_durability, mock_config)

    # Note: ThreadInfo has "active" status, but EnhancedThreadInfo maps it to "idle"
    thread_filter = ThreadFilter(status="idle")
    threads = await manager.list_threads(thread_filter=thread_filter)

    assert len(threads) == 2
    assert all(t.status == "idle" for t in threads)


@pytest.mark.asyncio
async def test_thread_filter_by_date_range(mock_durability, mock_config):
    """Test filtering threads by date range."""
    from soothe.protocols.durability import ThreadMetadata

    mock_durability.list_threads = AsyncMock(
        return_value=[
            ThreadInfo(
                thread_id="t1",
                status="active",
                created_at=datetime(2026, 3, 20, 10, 0, 0, tzinfo=UTC),
                updated_at=datetime(2026, 3, 20, 11, 0, 0, tzinfo=UTC),
                metadata=ThreadMetadata(),
            ),
            ThreadInfo(
                thread_id="t2",
                status="active",
                created_at=datetime(2026, 3, 22, 10, 0, 0, tzinfo=UTC),
                updated_at=datetime(2026, 3, 22, 11, 0, 0, tzinfo=UTC),
                metadata=ThreadMetadata(),
            ),
            ThreadInfo(
                thread_id="t3",
                status="active",
                created_at=datetime(2026, 3, 24, 10, 0, 0, tzinfo=UTC),
                updated_at=datetime(2026, 3, 24, 11, 0, 0, tzinfo=UTC),
                metadata=ThreadMetadata(),
            ),
        ]
    )

    manager = ThreadContextManager(mock_durability, mock_config)

    thread_filter = ThreadFilter(
        created_after=datetime(2026, 3, 21, 0, 0, tzinfo=UTC),
        created_before=datetime(2026, 3, 23, 23, 59, tzinfo=UTC),
    )
    threads = await manager.list_threads(thread_filter=thread_filter)

    assert len(threads) == 1
    assert threads[0].thread_id == "t2"
