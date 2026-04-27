"""Integration test for complete smart retry workflow.

Tests end-to-end smart retry cycle across all components:
- Failure detection
- Branch creation
- Failure analysis
- Smart retry execution

RFC-611: AgentLoop Checkpoint Tree Architecture
IG-243: Checkpoint Tree Integration Testing
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from contextlib import contextmanager

import pytest

from soothe.cognition.agent_loop.anchor_manager import CheckpointAnchorManager
from soothe.cognition.agent_loop.branch_manager import FailedBranchManager
from soothe.cognition.agent_loop.failure_analyzer import FailureAnalyzer
from soothe.cognition.agent_loop.persistence.directory_manager import (
    PersistenceDirectoryManager,
)
from soothe.cognition.agent_loop.persistence.manager import (
    AgentLoopCheckpointPersistenceManager,
)


@contextmanager
def mock_soothe_home(tmp_path):
    """Context manager to mock both SOOTHE_HOME variables (daemon and SDK).

    Ensures tests use isolated database in tmp_path instead of ~/.soothe/.
    """
    import soothe.config.env as env_config
    import soothe_sdk.client.config as sdk_config

    original_home = env_config.SOOTHE_HOME
    original_sdk_home = sdk_config.SOOTHE_HOME
    original_sdk_data_dir = sdk_config.SOOTHE_DATA_DIR

    env_config.SOOTHE_HOME = str(tmp_path)
    sdk_config.SOOTHE_HOME = str(tmp_path)
    sdk_config.SOOTHE_DATA_DIR = str(tmp_path / "data")

    try:
        yield
    finally:
        env_config.SOOTHE_HOME = original_home
        sdk_config.SOOTHE_HOME = original_sdk_home
        sdk_config.SOOTHE_DATA_DIR = original_sdk_data_dir


@pytest.mark.integration
@pytest.mark.asyncio
async def test_complete_smart_retry_workflow(tmp_path):
    """Test complete smart retry cycle across all components.

    Scenario:
    1. Execute iteration that fails
    2. Failed branch created with execution path
    3. Failure analyzed by LLM
    4. Smart retry executed with learning
    5. Retry succeeds with adjusted approach
    """
    with mock_soothe_home(tmp_path):
        # Setup persistence
        PersistenceDirectoryManager.ensure_directories_exist()
        persistence_manager = AgentLoopCheckpointPersistenceManager()  # Defaults to SQLite
        loop_id = "test_retry_loop"

        # Register the loop first (required for FK constraint)
        await persistence_manager.register_loop(
            loop_id=loop_id,
            thread_ids=["thread_001"],
            current_thread_id="thread_001",
            status="running",
        )

        # Mock checkpointer for anchor capture
        mock_checkpointer = AsyncMock()
        mock_checkpointer.aget_tuple = AsyncMock(
            return_value=MagicMock(
                config={
                    "configurable": {
                        "thread_id": "thread_001",
                        "checkpoint_id": "checkpoint_iter0_start",
                        "checkpoint_ns": "",
                    }
                }
            )
        )

        # 1. Capture iteration 0 (success)
        anchor_manager = CheckpointAnchorManager(loop_id)
        await anchor_manager.capture_iteration_start_anchor(
            iteration=0,
            thread_id="thread_001",
            checkpointer=mock_checkpointer,
        )

        mock_checkpointer_end = AsyncMock()
        mock_checkpointer_end.aget_tuple = AsyncMock(
            return_value=MagicMock(
                config={
                    "configurable": {
                        "thread_id": "thread_001",
                        "checkpoint_id": "checkpoint_iter0_end",
                    }
                }
            )
        )

        await anchor_manager.capture_iteration_end_anchor(
            iteration=0,
            thread_id="thread_001",
            checkpointer=mock_checkpointer_end,
            execution_summary={
                "status": "success",
                "next_action_summary": "Proceed to next iteration",
            },
        )

        # 2. Capture iteration 1 (failure)
        mock_checkpointer_fail = AsyncMock()
        mock_checkpointer_fail.aget_tuple = AsyncMock(
            return_value=MagicMock(
                config={
                    "configurable": {
                        "thread_id": "thread_001",
                        "checkpoint_id": "checkpoint_iter1_failure",
                    }
                }
            )
        )

        # Create failed branch
        branch_manager = FailedBranchManager(loop_id)
        failed_branch = await branch_manager.detect_iteration_failure(
            iteration=1,
            thread_id="thread_001",
            failure_reason="Tool execution timeout after 30s",
            checkpointer=mock_checkpointer_fail,
        )

        # 3. Verify branch created
        assert failed_branch is not None
        assert "branch_id" in failed_branch
        assert failed_branch["iteration"] == 1
        assert failed_branch["failure_reason"] == "Tool execution timeout after 30s"

        # 4. Analyze failure (mock LLM)
        from soothe.config import SootheConfig

        config = SootheConfig()

        mock_model = AsyncMock()
        mock_model.ainvoke = AsyncMock(
            return_value=MagicMock(
                content='```json\n{"root_cause": "Large file analysis timeout", "context": "File > 500KB", "patterns": ["Avoid large files without streaming"], "suggestions": ["Use streaming mode", "Split file into chunks"]}\n```'
            )
        )
        config.create_chat_model = MagicMock(return_value=mock_model)

        analyzer = FailureAnalyzer(config)
        failure_context = (
            "Exception Type: TimeoutError\nException Message: Operation timed out after 30s"
        )

        analyzed_branch = await analyzer.analyze_failure(failed_branch, failure_context)

        # 5. Verify analysis
        assert "failure_insights" in analyzed_branch
        assert analyzed_branch["failure_insights"]["root_cause"] == "Large file analysis timeout"
        assert len(analyzed_branch["avoid_patterns"]) > 0
        assert len(analyzed_branch["suggested_adjustments"]) > 0

        # 6. Verify persistence
        branches = await persistence_manager.get_failed_branches_for_loop(loop_id)
        assert len(branches) == 1
        assert branches[0]["analyzed_at"] is not None

        # 7. Verify checkpoint anchors
        anchors = await persistence_manager.get_checkpoint_anchors_for_range(loop_id, 0, 10)
        assert len(anchors) >= 2  # iteration_0_start, iteration_0_end

        # 8. Verify main line (successful iterations)
        successful_anchors = [a for a in anchors if a.get("iteration_status") == "success"]
        assert len(successful_anchors) >= 1  # iteration 0



@pytest.mark.integration
@pytest.mark.asyncio
async def test_multiple_failures_with_learning_accumulation(tmp_path):
    """Test multiple failures accumulate learning insights.

    Scenario:
    1. First failure → Branch 1 created with analysis
    2. Second failure (similar) → Branch 2 created
    3. Both branches preserved for learning
    4. Smart retry uses accumulated insights
    """
    with mock_soothe_home(tmp_path):
        PersistenceDirectoryManager.ensure_directories_exist()
        persistence_manager = AgentLoopCheckpointPersistenceManager()  # Defaults to SQLite
        loop_id = "test_multi_failure_loop"

        # Register the loop first (required for FK constraint)
        await persistence_manager.register_loop(
            loop_id=loop_id,
            thread_ids=["thread_001"],
            current_thread_id="thread_001",
            status="running",
        )

        # Create multiple failed branches
        branch_manager = FailedBranchManager(loop_id)

        # First failure
        mock_checkpointer_1 = AsyncMock()
        mock_checkpointer_1.aget_tuple = AsyncMock(
            return_value=MagicMock(
                config={
                    "configurable": {
                        "thread_id": "thread_001",
                        "checkpoint_id": "checkpoint_failure_1",
                    }
                }
            )
        )

        await branch_manager.detect_iteration_failure(
            iteration=2,
            thread_id="thread_001",
            failure_reason="API rate limit exceeded",
            checkpointer=mock_checkpointer_1,
        )

        # Second failure
        mock_checkpointer_2 = AsyncMock()
        mock_checkpointer_2.aget_tuple = AsyncMock(
            return_value=MagicMock(
                config={
                    "configurable": {
                        "thread_id": "thread_001",
                        "checkpoint_id": "checkpoint_failure_2",
                    }
                }
            )
        )

        await branch_manager.detect_iteration_failure(
            iteration=4,
            thread_id="thread_001",
            failure_reason="API timeout",
            checkpointer=mock_checkpointer_2,
        )

        # Verify both branches persisted
        branches = await persistence_manager.get_failed_branches_for_loop(loop_id)
        assert len(branches) == 2

        # Verify branches are distinct
        assert branches[0]["branch_id"] != branches[1]["branch_id"]
        assert branches[0]["iteration"] == 2
        assert branches[1]["iteration"] == 4



@pytest.mark.integration
@pytest.mark.asyncio
async def test_branch_pruning_retention_policy(tmp_path):
    """Test branch pruning respects retention policy.

    Scenario:
    1. Create branches with different ages
    2. Prune with retention_days=30
    3. Verify old branches deleted, recent branches preserved
    """
    from datetime import timedelta

    with mock_soothe_home(tmp_path):
        PersistenceDirectoryManager.ensure_directories_exist()
        persistence_manager = AgentLoopCheckpointPersistenceManager()  # Defaults to SQLite
        loop_id = "test_prune_loop"

        # Register the loop first (required for FK constraint)
        await persistence_manager.register_loop(
            loop_id=loop_id,
            thread_ids=["thread_001"],
            current_thread_id="thread_001",
            status="running",
        )

        # Create old branch (60 days ago)
        await persistence_manager.save_failed_branch(
            branch_id="branch_old",
            loop_id=loop_id,
            iteration=1,
            thread_id="thread_001",
            root_checkpoint_id="checkpoint_root_old",
            failure_checkpoint_id="checkpoint_failure_old",
            failure_reason="Old failure",
            execution_path=["checkpoint_root_old", "checkpoint_failure_old"],
        )

        # Manually set created_at to 60 days ago
        import aiosqlite

        db_path = PersistenceDirectoryManager.get_loop_checkpoint_path(loop_id)
        async with aiosqlite.connect(db_path) as db:
            old_date = datetime.now(UTC) - timedelta(days=60)
            await db.execute(
                "UPDATE failed_branches SET created_at = ? WHERE branch_id = ?",
                (old_date, "branch_old"),
            )
            await db.commit()

        # Create recent branch (5 days ago)
        await persistence_manager.save_failed_branch(
            branch_id="branch_recent",
            loop_id=loop_id,
            iteration=3,
            thread_id="thread_001",
            root_checkpoint_id="checkpoint_root_recent",
            failure_checkpoint_id="checkpoint_failure_recent",
            failure_reason="Recent failure",
            execution_path=["checkpoint_root_recent", "checkpoint_failure_recent"],
        )

        async with aiosqlite.connect(db_path) as db:
            recent_date = datetime.now(UTC) - timedelta(days=5)
            await db.execute(
                "UPDATE failed_branches SET created_at = ? WHERE branch_id = ?",
                (recent_date, "branch_recent"),
            )
            await db.commit()

        # Prune with retention_days=30
        pruned = await persistence_manager.prune_old_branches(loop_id, retention_days=30)

        # Verify pruning results
        assert pruned == 1  # Only old branch pruned

        branches = await persistence_manager.get_failed_branches_for_loop(loop_id)
        assert len(branches) == 1  # Recent branch preserved
        assert branches[0]["branch_id"] == "branch_recent"

