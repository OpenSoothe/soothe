"""Unit tests for AgentLoop persistence manager.

Tests for:
- Directory manager (thread/loop isolation)
- SQLite backend (schema initialization)
- Persistence manager (anchor/branch operations)
"""

import uuid

import pytest

from soothe.cognition.agent_loop.persistence.directory_manager import PersistenceDirectoryManager
from soothe.cognition.agent_loop.persistence.manager import AgentLoopCheckpointPersistenceManager
from soothe.cognition.agent_loop.persistence.sqlite_backend import SQLitePersistenceBackend


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

    import soothe_sdk.client.config as sdk_config

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

        thread_checkpoint = PersistenceDirectoryManager.get_thread_checkpoint_path("thread_001")
        assert thread_checkpoint == tmp_path / "data" / "threads" / "thread_001" / "checkpoint.db"

        # Loop paths (now global database)
        loop_dir = PersistenceDirectoryManager.get_loop_directory("loop_abc")
        assert loop_dir == tmp_path / "data" / "loops" / "loop_abc"

        loop_checkpoint = PersistenceDirectoryManager.get_loop_checkpoint_path()
        assert loop_checkpoint == tmp_path / "data" / "loop_checkpoints.db"

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

        # Check checkpoint_anchors table
        async with db.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='checkpoint_anchors'
        """) as cursor:
            table = await cursor.fetchone()
            assert table is not None

        # Check failed_branches table
        async with db.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='failed_branches'
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


@pytest.mark.asyncio
async def test_persistence_manager_save_checkpoint_anchor(tmp_path):
    """Test persistence manager saves checkpoint anchor."""

    import soothe_sdk.client.config as sdk_config

    import soothe.config as config

    original_home = config.SOOTHE_HOME
    original_data_dir = sdk_config.SOOTHE_DATA_DIR
    config.SOOTHE_HOME = str(tmp_path)
    sdk_config.SOOTHE_DATA_DIR = str(tmp_path / "data")

    try:
        PersistenceDirectoryManager.ensure_directories_exist()

        manager = AgentLoopCheckpointPersistenceManager("sqlite")

        # Use unique loop_id to avoid global database conflicts
        unique_loop_id = f"test_loop_{uuid.uuid4().hex[:8]}"

        # Save checkpoint anchor
        await manager.save_checkpoint_anchor(
            loop_id=unique_loop_id,
            iteration=0,
            thread_id="thread_001",
            checkpoint_id="checkpoint_abc",
            anchor_type="iteration_start",
        )

        # Verify anchor saved
        anchors = await manager.get_checkpoint_anchors_for_range(unique_loop_id, 0, 0)

        assert len(anchors) == 1
        assert anchors[0]["iteration"] == 0
        assert anchors[0]["thread_id"] == "thread_001"
        assert anchors[0]["checkpoint_id"] == "checkpoint_abc"

        # Close manager to cleanup connection
        await manager.close()
        assert anchors[0]["anchor_type"] == "iteration_start"

    finally:
        config.SOOTHE_HOME = original_home
        sdk_config.SOOTHE_DATA_DIR = original_data_dir


@pytest.mark.asyncio
async def test_persistence_manager_save_checkpoint_anchor_with_summary(tmp_path):
    """Test persistence manager saves checkpoint anchor with execution summary."""

    import soothe_sdk.client.config as sdk_config

    import soothe.config as config

    original_home = config.SOOTHE_HOME
    original_data_dir = sdk_config.SOOTHE_DATA_DIR
    config.SOOTHE_HOME = str(tmp_path)
    sdk_config.SOOTHE_DATA_DIR = str(tmp_path / "data")

    try:
        PersistenceDirectoryManager.ensure_directories_exist()

        manager = AgentLoopCheckpointPersistenceManager("sqlite")

        execution_summary = {
            "status": "success",
            "next_action_summary": "Continue to next iteration",
            "tools_executed": ["execute(ls)", "execute(read_file)"],
            "reasoning_decision": "Analyze project structure",
        }

        # Use unique loop_id to avoid conflicts across tests
        unique_loop_id = f"test_loop_summary_{uuid.uuid4().hex[:8]}"

        await manager.save_checkpoint_anchor(
            loop_id=unique_loop_id,
            iteration=0,
            thread_id="thread_001",
            checkpoint_id="checkpoint_def",
            anchor_type="iteration_end",
            execution_summary=execution_summary,
        )

        # Verify anchor with summary
        anchors = await manager.get_checkpoint_anchors_for_range(unique_loop_id, 0, 0)

        assert len(anchors) == 1
        assert anchors[0]["iteration_status"] == "success"
        assert anchors[0]["next_action_summary"] == "Continue to next iteration"
        assert anchors[0]["tools_executed"] == ["execute(ls)", "execute(read_file)"]
        assert anchors[0]["reasoning_decision"] == "Analyze project structure"

        # Close manager to cleanup connection
        await manager.close()

    finally:
        config.SOOTHE_HOME = original_home
        sdk_config.SOOTHE_DATA_DIR = original_data_dir


@pytest.mark.asyncio
async def test_persistence_manager_save_failed_branch(tmp_path):
    """Test persistence manager saves failed branch."""

    import soothe_sdk.client.config as sdk_config

    import soothe.config as config

    original_home = config.SOOTHE_HOME
    original_data_dir = sdk_config.SOOTHE_DATA_DIR
    config.SOOTHE_HOME = str(tmp_path)
    sdk_config.SOOTHE_DATA_DIR = str(tmp_path / "data")

    try:
        PersistenceDirectoryManager.ensure_directories_exist()

        manager = AgentLoopCheckpointPersistenceManager("sqlite")

        # Use unique IDs to avoid global database conflicts
        unique_id = uuid.uuid4().hex[:8]
        branch_id = f"branch_abc_{unique_id}"
        loop_id = f"test_loop_{unique_id}"

        await manager.save_failed_branch(
            branch_id=branch_id,
            loop_id=loop_id,
            iteration=3,
            thread_id="thread_001",
            root_checkpoint_id="checkpoint_root",
            failure_checkpoint_id="checkpoint_failure",
            failure_reason="Tool execution timeout",
            execution_path=["checkpoint_root", "checkpoint_1", "checkpoint_failure"],
        )

        # Verify branch saved
        branches = await manager.get_failed_branches_for_loop(loop_id)

        assert len(branches) == 1
        assert branches[0]["branch_id"] == branch_id
        assert branches[0]["iteration"] == 3
        assert branches[0]["thread_id"] == "thread_001"
        assert branches[0]["failure_reason"] == "Tool execution timeout"
        assert branches[0]["execution_path"] == [
            "checkpoint_root",
            "checkpoint_1",
            "checkpoint_failure",
        ]

        # Close manager to cleanup connection
        await manager.close()

    finally:
        config.SOOTHE_HOME = original_home
        sdk_config.SOOTHE_DATA_DIR = original_data_dir


@pytest.mark.asyncio
async def test_persistence_manager_update_branch_analysis(tmp_path):
    """Test persistence manager updates branch with analysis."""

    import soothe_sdk.client.config as sdk_config

    import soothe.config as config

    original_home = config.SOOTHE_HOME
    original_data_dir = sdk_config.SOOTHE_DATA_DIR
    config.SOOTHE_HOME = str(tmp_path)
    sdk_config.SOOTHE_DATA_DIR = str(tmp_path / "data")

    try:
        PersistenceDirectoryManager.ensure_directories_exist()

        manager = AgentLoopCheckpointPersistenceManager("sqlite")

        # Use unique IDs to avoid conflicts across tests
        unique_id = uuid.uuid4().hex[:8]
        branch_id = f"branch_analysis_test_{unique_id}"
        loop_id = f"test_loop_analysis_{unique_id}"

        # Create branch first
        await manager.save_failed_branch(
            branch_id=branch_id,
            loop_id=loop_id,
            iteration=3,
            thread_id="thread_001",
            root_checkpoint_id="checkpoint_root",
            failure_checkpoint_id="checkpoint_failure",
            failure_reason="Tool execution timeout",
            execution_path=["checkpoint_root", "checkpoint_failure"],
        )

        # Update with analysis
        failure_insights = {
            "root_cause": "Subagent timeout after 30s",
            "context": "Large file analysis exceeded threshold",
        }
        avoid_patterns = [
            "Do not use claude subagent for files > 500KB without streaming",
            "Avoid sequential file reads in single iteration",
        ]
        suggested_adjustments = [
            "Use streaming mode for large file analysis",
            "Split file into chunks, analyze in parallel",
        ]

        await manager.update_branch_analysis(
            branch_id=branch_id,
            loop_id=loop_id,
            failure_insights=failure_insights,
            avoid_patterns=avoid_patterns,
            suggested_adjustments=suggested_adjustments,
        )

        # Verify analysis updated
        branches = await manager.get_failed_branches_for_loop(loop_id)

        assert len(branches) == 1
        assert branches[0]["failure_insights"]["root_cause"] == "Subagent timeout after 30s"
        assert branches[0]["avoid_patterns"] == avoid_patterns
        assert branches[0]["suggested_adjustments"] == suggested_adjustments
        assert branches[0]["analyzed_at"] is not None

        # Close manager to cleanup connection
        await manager.close()

    finally:
        config.SOOTHE_HOME = original_home
        sdk_config.SOOTHE_DATA_DIR = original_data_dir


@pytest.mark.asyncio
async def test_persistence_manager_get_thread_checkpoints_for_loop(tmp_path):
    """Test persistence manager gets thread checkpoint cross-reference."""

    import soothe_sdk.client.config as sdk_config

    import soothe.config as config

    original_home = config.SOOTHE_HOME
    original_data_dir = sdk_config.SOOTHE_DATA_DIR
    config.SOOTHE_HOME = str(tmp_path)
    sdk_config.SOOTHE_DATA_DIR = str(tmp_path / "data")

    try:
        PersistenceDirectoryManager.ensure_directories_exist()

        manager = AgentLoopCheckpointPersistenceManager("sqlite")

        # Use unique loop_id to avoid global database conflicts
        unique_loop_id = f"test_loop_threads_{uuid.uuid4().hex[:8]}"

        # Save anchors for multiple threads
        await manager.save_checkpoint_anchor(
            loop_id=unique_loop_id,
            iteration=0,
            thread_id="thread_001",
            checkpoint_id="checkpoint_a",
            anchor_type="iteration_start",
        )
        await manager.save_checkpoint_anchor(
            loop_id=unique_loop_id,
            iteration=0,
            thread_id="thread_001",
            checkpoint_id="checkpoint_b",
            anchor_type="iteration_end",
        )
        await manager.save_checkpoint_anchor(
            loop_id=unique_loop_id,
            iteration=1,
            thread_id="thread_002",
            checkpoint_id="checkpoint_c",
            anchor_type="iteration_start",
        )

        # Get thread checkpoints map
        thread_checkpoints = await manager.get_thread_checkpoints_for_loop(unique_loop_id)

        assert "thread_001" in thread_checkpoints
        assert "thread_002" in thread_checkpoints
        assert len(thread_checkpoints["thread_001"]) == 2
        assert len(thread_checkpoints["thread_002"]) == 1
        assert "checkpoint_a" in thread_checkpoints["thread_001"]
        assert "checkpoint_c" in thread_checkpoints["thread_002"]

        # Close manager to cleanup connection
        await manager.close()

    finally:
        config.SOOTHE_HOME = original_home
        sdk_config.SOOTHE_DATA_DIR = original_data_dir
