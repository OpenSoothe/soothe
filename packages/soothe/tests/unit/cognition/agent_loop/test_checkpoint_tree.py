"""Unit tests for AgentLoop checkpoint tree architecture.

Tests for:
- Checkpoint anchor capture (iteration start/end)
- Failed branch creation (failure detection)
- Failure analysis (LLM insights)
- Smart retry (checkpoint restoration)
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.cognition.agent_loop.anchor_manager import CheckpointAnchorManager
from soothe.cognition.agent_loop.branch_manager import FailedBranchManager
from soothe.cognition.agent_loop.failure_analyzer import (
    FailureAnalyzer,
    extract_failure_context_from_exception,
)
from soothe.cognition.agent_loop.smart_retry_manager import SmartRetryManager


@pytest.mark.asyncio
async def test_checkpoint_anchor_manager_capture_start_anchor(tmp_path):
    """Test checkpoint anchor manager captures iteration start anchor."""

    import soothe.config as config

    original_home = config.SOOTHE_HOME
    config.SOOTHE_HOME = str(tmp_path)

    try:
        from soothe.cognition.agent_loop.persistence.directory_manager import (
            PersistenceDirectoryManager,
        )
        from soothe.cognition.agent_loop.persistence.manager import (
            AgentLoopCheckpointPersistenceManager,
        )

        PersistenceDirectoryManager.ensure_directories_exist()

        # Register loop first (required for FK constraint)
        persistence_manager = AgentLoopCheckpointPersistenceManager(None)
        await persistence_manager.register_loop(
            loop_id="test_loop",
            thread_ids=["thread_001"],
            current_thread_id="thread_001",
        )

        # Mock checkpointer
        mock_checkpointer = AsyncMock()
        mock_checkpointer.aget_tuple = AsyncMock(
            return_value=MagicMock(
                config={
                    "configurable": {
                        "thread_id": "thread_001",
                        "checkpoint_id": "checkpoint_abc",
                        "checkpoint_ns": "",
                    }
                }
            )
        )

        # Create anchor manager (uses same persistence manager)
        anchor_manager = CheckpointAnchorManager("test_loop")

        # Capture iteration start anchor
        await anchor_manager.capture_iteration_start_anchor(
            iteration=0,
            thread_id="thread_001",
            checkpointer=mock_checkpointer,
        )

        # Verify checkpointer called
        assert mock_checkpointer.aget_tuple.called

    finally:
        config.SOOTHE_HOME = original_home


@pytest.mark.asyncio
async def test_checkpoint_anchor_manager_capture_end_anchor_with_summary(tmp_path):
    """Test checkpoint anchor manager captures iteration end anchor with execution summary."""

    import soothe.config as config

    original_home = config.SOOTHE_HOME
    config.SOOTHE_HOME = str(tmp_path)

    try:
        from soothe.cognition.agent_loop.persistence.directory_manager import (
            PersistenceDirectoryManager,
        )
        from soothe.cognition.agent_loop.persistence.manager import (
            AgentLoopCheckpointPersistenceManager,
        )

        PersistenceDirectoryManager.ensure_directories_exist()

        # Register loop first (required for FK constraint)
        persistence_manager = AgentLoopCheckpointPersistenceManager(None)
        await persistence_manager.register_loop(
            loop_id="test_loop",
            thread_ids=["thread_001"],
            current_thread_id="thread_001",
        )

        # Mock checkpointer
        mock_checkpointer = AsyncMock()
        mock_checkpointer.aget_tuple = AsyncMock(
            return_value=MagicMock(
                config={
                    "configurable": {"thread_id": "thread_001", "checkpoint_id": "checkpoint_def"}
                }
            )
        )

        anchor_manager = CheckpointAnchorManager("test_loop")

        execution_summary = {
            "status": "success",
            "next_action_summary": "Continue to next iteration",
            "tools_executed": ["execute(ls)", "execute(read_file)"],
            "reasoning_decision": "Analyze project structure",
        }

        await anchor_manager.capture_iteration_end_anchor(
            iteration=0,
            thread_id="thread_001",
            checkpointer=mock_checkpointer,
            execution_summary=execution_summary,
        )

        # Verify checkpointer called
        assert mock_checkpointer.aget_tuple.called

    finally:
        config.SOOTHE_HOME = original_home


@pytest.mark.asyncio
async def test_failed_branch_manager_detect_failure(tmp_path):
    """Test failed branch manager detects iteration failure and creates branch."""

    import soothe.config as config

    original_home = config.SOOTHE_HOME
    config.SOOTHE_HOME = str(tmp_path)

    try:
        from soothe.cognition.agent_loop.persistence.directory_manager import (
            PersistenceDirectoryManager,
        )
        from soothe.cognition.agent_loop.persistence.manager import (
            AgentLoopCheckpointPersistenceManager,
        )

        PersistenceDirectoryManager.ensure_directories_exist()

        # Register loop first (required for FK constraint)
        persistence_manager = AgentLoopCheckpointPersistenceManager(None)
        await persistence_manager.register_loop(
            loop_id="test_loop",
            thread_ids=["thread_001"],
            current_thread_id="thread_001",
        )

        # Mock checkpointer
        mock_checkpointer = AsyncMock()
        mock_checkpointer.aget_tuple = AsyncMock(
            return_value=MagicMock(
                config={
                    "configurable": {
                        "thread_id": "thread_001",
                        "checkpoint_id": "checkpoint_failure",
                    }
                }
            )
        )

        # Create anchor manager and capture previous anchor
        anchor_manager = CheckpointAnchorManager("test_loop")
        mock_checkpointer_prev = AsyncMock()
        mock_checkpointer_prev.aget_tuple = AsyncMock(
            return_value=MagicMock(
                config={
                    "configurable": {"thread_id": "thread_001", "checkpoint_id": "checkpoint_root"}
                }
            )
        )

        await anchor_manager.capture_iteration_end_anchor(
            iteration=2,
            thread_id="thread_001",
            checkpointer=mock_checkpointer_prev,
            execution_summary={"status": "success"},
        )

        # Create branch manager
        branch_manager = FailedBranchManager("test_loop")

        # Detect failure
        failed_branch = await branch_manager.detect_iteration_failure(
            iteration=3,
            thread_id="thread_001",
            failure_reason="Tool execution timeout",
            checkpointer=mock_checkpointer,
        )

        # Verify branch created
        assert failed_branch is not None
        assert "branch_id" in failed_branch
        assert failed_branch["iteration"] == 3
        assert failed_branch["thread_id"] == "thread_001"
        assert failed_branch["failure_reason"] == "Tool execution timeout"
        assert failed_branch["failure_checkpoint_id"] == "checkpoint_failure"

    finally:
        config.SOOTHE_HOME = original_home


@pytest.mark.asyncio
async def test_failure_analyzer_analyze_failure(tmp_path):
    """Test failure analyzer computes learning insights."""

    import soothe.config as config_module

    original_home = config_module.SOOTHE_HOME
    config_module.SOOTHE_HOME = str(tmp_path)

    try:
        from soothe.cognition.agent_loop.persistence.directory_manager import (
            PersistenceDirectoryManager,
        )
        from soothe.cognition.agent_loop.persistence.sqlite_backend import (
            SQLitePersistenceBackend,
        )

        PersistenceDirectoryManager.ensure_directories_exist()

        # Initialize database for test_loop
        loop_dir = PersistenceDirectoryManager.get_loop_directory("test_loop")
        db_path = loop_dir / "checkpoint.db"
        await SQLitePersistenceBackend.initialize_database(db_path)

        # Create a failed branch record in database
        import aiosqlite

        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                """
                INSERT INTO failed_branches
                (branch_id, loop_id, iteration, thread_id,
                 root_checkpoint_id, failure_checkpoint_id,
                 failure_reason, execution_path, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "branch_abc",
                    "test_loop",
                    3,
                    "test_thread",
                    "checkpoint_root_123",
                    "checkpoint_failure_456",
                    "Tool execution timeout",
                    "step1->step2->step3",
                    datetime.now(UTC).isoformat(),
                ),
            )
            await db.commit()

        # Create a mock config object (not SootheConfig instance since we need to set methods)
        from unittest.mock import MagicMock

        mock_config = MagicMock()

        # Mock LLM model
        mock_model = AsyncMock()
        mock_model.ainvoke = AsyncMock(
            return_value=MagicMock(
                content='```json\n{"root_cause": "Subagent timeout", "context": "Large file analysis", "patterns": ["Avoid large files"], "suggestions": ["Use streaming"]}\n```'
            )
        )
        mock_config.create_chat_model = MagicMock(return_value=mock_model)

        analyzer = FailureAnalyzer(mock_config)

        # Create branch (simplified)
        branch = {
            "branch_id": "branch_abc",
            "loop_id": "test_loop",
            "iteration": 3,
            "failure_reason": "Tool execution timeout",
        }

        failure_context = (
            "Exception Type: TimeoutError\nException Message: Operation timed out after 30s"
        )

        # Analyze failure
        analyzed_branch = await analyzer.analyze_failure(branch, failure_context)

        # Verify analysis
        assert "failure_insights" in analyzed_branch
        assert analyzed_branch["failure_insights"]["root_cause"] == "Subagent timeout"
        assert analyzed_branch["avoid_patterns"] == ["Avoid large files"]
        assert analyzed_branch["suggested_adjustments"] == ["Use streaming"]
        assert analyzed_branch["analyzed_at"] is not None

    finally:
        config_module.SOOTHE_HOME = original_home


def test_extract_failure_context_from_exception():
    """Test extracting failure context from exception."""

    exception = TimeoutError("Operation timed out after 30s")
    execution_summary = {
        "reasoning_decision": "Analyze large file",
        "tools_executed": ["execute(read_file)"],
        "iteration_status": "running",
    }

    context = extract_failure_context_from_exception(exception, execution_summary)

    assert "Exception Type: TimeoutError" in context
    assert "Exception Message: Operation timed out after 30s" in context
    assert "Reasoning Decision: Analyze large file" in context
    assert "Tools Executed: execute(read_file)" in context
    assert "Iteration Status: running" in context


@pytest.mark.asyncio
async def test_smart_retry_manager_build_retry_context():
    """Test smart retry manager builds retry context."""

    retry_manager = SmartRetryManager("test_loop")

    branch = {
        "branch_id": "branch_abc",
        "failure_reason": "Tool execution timeout",
        "avoid_patterns": ["Avoid large files without streaming"],
        "suggested_adjustments": ["Use streaming mode", "Split file into chunks"],
    }

    retry_context = retry_manager.build_retry_context(branch)

    assert retry_context["retry_mode"] is True
    assert retry_context["previous_failure"]["reason"] == "Tool execution timeout"
    assert retry_context["previous_failure"]["avoid_patterns"] == [
        "Avoid large files without streaming"
    ]
    assert retry_context["previous_failure"]["suggested_adjustments"] == [
        "Use streaming mode",
        "Split file into chunks",
    ]
    assert retry_context["learning_applied"] == ["Use streaming mode", "Split file into chunks"]
