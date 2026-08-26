"""Unit tests for StrangeLoop persistence manager.

Tests for:
- Directory manager (thread/loop isolation)
- SQLite backend (schema initialization)
- Persistence manager (goal record operations)
"""

import pytest

from soothe.sloop.checkpoints.directory_manager import (
    PersistenceDirectoryManager,
)
from soothe.sloop.checkpoints.sqlite_backend import SQLitePersistenceBackend


@pytest.mark.asyncio
async def test_directory_manager_creates_directories(tmp_path):
    """Test that directory manager creates isolated directories."""

    # Mock SOOTHE_HOME to temp directory
    import soothe.config as config

    original_home = config.SOOTHE_HOME
    config.SOOTHE_HOME = str(tmp_path)

    try:
        # Ensure directories exist
        PersistenceDirectoryManager.ensure_directories_exist()

        # Verify directories created
        threads_dir = tmp_path / "data" / "threads"
        loops_dir = tmp_path / "data" / "loops"

        assert threads_dir.exists()
        assert loops_dir.exists()

    finally:
        # Restore original SOOTHE_HOME
        config.SOOTHE_HOME = original_home


@pytest.mark.asyncio
async def test_directory_manager_paths(tmp_path):
    """Test directory manager returns correct paths."""

    import soothe_sdk.paths as sdk_config

    import soothe.config as config

    original_home = config.SOOTHE_HOME
    original_data_dir = sdk_config.SOOTHE_DATA_DIR
    config.SOOTHE_HOME = str(tmp_path)
    sdk_config.SOOTHE_DATA_DIR = str(tmp_path / "data")

    try:
        PersistenceDirectoryManager.ensure_directories_exist()

        # Thread paths
        thread_dir = PersistenceDirectoryManager.get_thread_directory("thread_001")
        assert thread_dir == tmp_path / "data" / "threads" / "thread_001"

        # Loop paths (process-wide databases/checkpoints.db)
        loop_dir = PersistenceDirectoryManager.get_loop_directory("loop_abc")
        assert loop_dir == tmp_path / "data" / "loops" / "loop_abc"

        loop_checkpoint = PersistenceDirectoryManager.get_loop_checkpoint_path()
        assert loop_checkpoint == tmp_path / "data" / "databases" / "checkpoints.db"

    finally:
        config.SOOTHE_HOME = original_home
        sdk_config.SOOTHE_DATA_DIR = original_data_dir


@pytest.mark.asyncio
async def test_sqlite_backend_initialize_database(tmp_path):
    """Test SQLite backend initializes database schema."""

    db_path = tmp_path / "loop_checkpoints.db"

    # Use synchronous initialization
    SQLitePersistenceBackend.initialize_database_sync(db_path)

    # Verify database created
    assert db_path.exists()

    # Verify tables created
    import aiosqlite

    async with aiosqlite.connect(db_path) as db:
        # Check agentloop_loops table
        async with db.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='agentloop_loops'
        """) as cursor:
            table = await cursor.fetchone()
            assert table is not None

        # Check goal_records table
        async with db.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='goal_records'
        """) as cursor:
            table = await cursor.fetchone()
            assert table is not None
