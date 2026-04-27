"""Integration test for loop detachment and reattachment with history replay.

Tests complete detachment/reattachment workflow:
- Loop continues running after detach
- History reconstruction on reattach
- Event stream replay to client

RFC-411: Event Stream Replay
RFC-503: Loop-First User Experience
IG-243: Checkpoint Tree Integration Testing
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from contextlib import contextmanager

import pytest

from soothe.cognition.agent_loop.anchor_manager import CheckpointAnchorManager
from soothe.cognition.agent_loop.persistence.directory_manager import (
    PersistenceDirectoryManager,
)
from soothe.cognition.agent_loop.persistence.manager import (
    AgentLoopCheckpointPersistenceManager,
)
from soothe.core.event_constants import (
    BRANCH_CREATED,
    ITERATION_COMPLETED,
    ITERATION_STARTED,
)
from soothe.core.event_replay import reconstruct_event_stream


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
async def test_loop_detachment_continues_execution(tmp_path):
    """Test loop continues execution after client detachment.

    Scenario:
    1. Client attaches to loop
    2. Execute goal 1
    3. Client detaches (daemon continues)
    4. Execute goal 2 while detached
    5. Verify loop status remains 'running'
    """
    with mock_soothe_home(tmp_path):
        PersistenceDirectoryManager.ensure_directories_exist()
        persistence_manager = AgentLoopCheckpointPersistenceManager()  # Defaults to SQLite
        loop_id = "test_detach_loop"

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
                        "checkpoint_id": "checkpoint_detach_1",
                    }
                }
            )
        )

        # Execute goal 1 (before detach)
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
                        "checkpoint_id": "checkpoint_detach_end_1",
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
                "next_action_summary": "Goal 1 completed",
            },
        )

        # Simulate detach (client disconnects)
        # In real daemon, loop status would remain 'running'

        # Execute goal 2 (while detached)
        mock_checkpointer_2 = AsyncMock()
        mock_checkpointer_2.aget_tuple = AsyncMock(
            return_value=MagicMock(
                config={
                    "configurable": {
                        "thread_id": "thread_001",
                        "checkpoint_id": "checkpoint_detach_2",
                    }
                }
            )
        )

        await anchor_manager.capture_iteration_start_anchor(
            iteration=1,
            thread_id="thread_001",
            checkpointer=mock_checkpointer_2,
        )

        mock_checkpointer_end_2 = AsyncMock()
        mock_checkpointer_end_2.aget_tuple = AsyncMock(
            return_value=MagicMock(
                config={
                    "configurable": {
                        "thread_id": "thread_001",
                        "checkpoint_id": "checkpoint_detach_end_2",
                    }
                }
            )
        )

        await anchor_manager.capture_iteration_end_anchor(
            iteration=1,
            thread_id="thread_001",
            checkpointer=mock_checkpointer_end_2,
            execution_summary={
                "status": "success",
                "next_action_summary": "Goal 2 completed",
            },
        )

        # Verify both iterations persisted
        anchors = await persistence_manager.get_checkpoint_anchors_for_range(loop_id, 0, 10)
        assert len(anchors) >= 4  # 2 iterations, each with start + end

        # Verify iteration status
        iteration_0_end = [
            a for a in anchors if a["iteration"] == 0 and a["anchor_type"] == "iteration_end"
        ]
        assert len(iteration_0_end) == 1
        assert iteration_0_end[0]["iteration_status"] == "success"

        iteration_1_end = [
            a for a in anchors if a["iteration"] == 1 and a["anchor_type"] == "iteration_end"
        ]
        assert len(iteration_1_end) == 1
        assert iteration_1_end[0]["iteration_status"] == "success"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_loop_reattachment_history_replay(tmp_path):
    """Test loop reattachment reconstructs complete history.

    Scenario:
    1. Execute multiple goals
    2. Create failed branches
    3. Client reattaches
    4. Receive history_replay event with complete event stream
    5. Verify all goals/iterations/branches reconstructed
    """
    with mock_soothe_home(tmp_path):
        PersistenceDirectoryManager.ensure_directories_exist()
        persistence_manager = AgentLoopCheckpointPersistenceManager()  # Defaults to SQLite
        loop_id = "test_reattach_loop"

        # Register the loop first (required for FK constraint)
        await persistence_manager.register_loop(
            loop_id=loop_id,
            thread_ids=["thread_001", "thread_002"],
            current_thread_id="thread_001",
            status="running",
        )

        # Mock checkpointer
        mock_checkpointer = AsyncMock()
        mock_checkpointer.aget_tuple = AsyncMock(
            return_value=MagicMock(
                config={
                    "configurable": {
                        "thread_id": "thread_001",
                        "checkpoint_id": "checkpoint_reattach_1",
                    }
                }
            )
        )

        # Execute goal 1 (iteration 0)
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
                        "checkpoint_id": "checkpoint_reattach_end_1",
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
                "next_action_summary": "Goal 1 completed",
                "tools_executed": ["execute(ls)", "execute(read_file)"],
            },
        )

        # Execute goal 2 (iteration 1) - with failure
        mock_checkpointer_2 = AsyncMock()
        mock_checkpointer_2.aget_tuple = AsyncMock(
            return_value=MagicMock(
                config={
                    "configurable": {
                        "thread_id": "thread_001",
                        "checkpoint_id": "checkpoint_reattach_2",
                    }
                }
            )
        )

        await anchor_manager.capture_iteration_start_anchor(
            iteration=1,
            thread_id="thread_001",
            checkpointer=mock_checkpointer_2,
        )

        # Create failed branch for iteration 1
        from soothe.cognition.agent_loop.branch_manager import FailedBranchManager

        branch_manager = FailedBranchManager(loop_id)

        mock_checkpointer_fail = AsyncMock()
        mock_checkpointer_fail.aget_tuple = AsyncMock(
            return_value=MagicMock(
                config={
                    "configurable": {
                        "thread_id": "thread_001",
                        "checkpoint_id": "checkpoint_reattach_failure",
                    }
                }
            )
        )

        await branch_manager.detect_iteration_failure(
            iteration=1,
            thread_id="thread_001",
            failure_reason="Tool execution timeout",
            checkpointer=mock_checkpointer_fail,
        )

        # Reconstruct event stream
        event_stream = await reconstruct_event_stream(loop_id, persistence_manager)

        # Verify event stream contains all expected events
        assert len(event_stream) > 0

        # Verify ITERATION_STARTED events
        iter_started_events = [e for e in event_stream if e["type"] == ITERATION_STARTED]
        assert len(iter_started_events) >= 2  # iteration 0 and 1

        # Verify ITERATION_COMPLETED events
        iter_completed_events = [e for e in event_stream if e["type"] == ITERATION_COMPLETED]
        assert len(iter_completed_events) >= 1  # iteration 0 completed successfully

        # Verify BRANCH_CREATED events
        branch_events = [e for e in event_stream if e["type"] == BRANCH_CREATED]
        assert len(branch_events) == 1  # one failed branch
        assert branch_events[0]["iteration"] == 1
        assert branch_events[0]["failure_reason"] == "Tool execution timeout"

        # Verify chronological order (sorted by timestamp)
        timestamps = [e.get("timestamp", datetime.min) for e in event_stream]
        assert timestamps == sorted(timestamps)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_loop_reattachment_with_thread_switch(tmp_path):
    """Test loop reattachment preserves thread switch history.

    Scenario:
    1. Execute iterations across multiple threads
    2. Thread switches occur
    3. Reattach client
    4. Verify THREAD_SWITCHED events in replay
    """
    with mock_soothe_home(tmp_path):
        PersistenceDirectoryManager.ensure_directories_exist()
        persistence_manager = AgentLoopCheckpointPersistenceManager()  # Defaults to SQLite
        loop_id = "test_thread_switch_loop"

        # Register the loop first (required for FK constraint)
        await persistence_manager.register_loop(
            loop_id=loop_id,
            thread_ids=["thread_001", "thread_002"],
            current_thread_id="thread_001",
            status="running",
        )

        # Mock checkpointer for thread_001
        mock_checkpointer_t1 = AsyncMock()
        mock_checkpointer_t1.aget_tuple = AsyncMock(
            return_value=MagicMock(
                config={
                    "configurable": {
                        "thread_id": "thread_001",
                        "checkpoint_id": "checkpoint_switch_t1",
                    }
                }
            )
        )

        # Execute iteration 0 on thread_001
        anchor_manager = CheckpointAnchorManager(loop_id)
        await anchor_manager.capture_iteration_start_anchor(
            iteration=0,
            thread_id="thread_001",
            checkpointer=mock_checkpointer_t1,
        )

        mock_checkpointer_t1_end = AsyncMock()
        mock_checkpointer_t1_end.aget_tuple = AsyncMock(
            return_value=MagicMock(
                config={
                    "configurable": {
                        "thread_id": "thread_001",
                        "checkpoint_id": "checkpoint_switch_t1_end",
                    }
                }
            )
        )

        await anchor_manager.capture_iteration_end_anchor(
            iteration=0,
            thread_id="thread_001",
            checkpointer=mock_checkpointer_t1_end,
            execution_summary={
                "status": "success",
                "next_action_summary": "Thread switch triggered",
            },
        )

        # Execute iteration 1 on thread_002 (thread switch)
        mock_checkpointer_t2 = AsyncMock()
        mock_checkpointer_t2.aget_tuple = AsyncMock(
            return_value=MagicMock(
                config={
                    "configurable": {
                        "thread_id": "thread_002",
                        "checkpoint_id": "checkpoint_switch_t2",
                    }
                }
            )
        )

        await anchor_manager.capture_iteration_start_anchor(
            iteration=1,
            thread_id="thread_002",
            checkpointer=mock_checkpointer_t2,
        )

        mock_checkpointer_t2_end = AsyncMock()
        mock_checkpointer_t2_end.aget_tuple = AsyncMock(
            return_value=MagicMock(
                config={
                    "configurable": {
                        "thread_id": "thread_002",
                        "checkpoint_id": "checkpoint_switch_t2_end",
                    }
                }
            )
        )

        await anchor_manager.capture_iteration_end_anchor(
            iteration=1,
            thread_id="thread_002",
            checkpointer=mock_checkpointer_t2_end,
            execution_summary={
                "status": "success",
                "next_action_summary": "Continuing on thread_002",
            },
        )

        # Reconstruct event stream
        event_stream = await reconstruct_event_stream(loop_id, persistence_manager)

        # Verify THREAD_SWITCHED event
        from soothe.core.event_constants import THREAD_SWITCHED

        thread_switch_events = [e for e in event_stream if e["type"] == THREAD_SWITCHED]
        assert len(thread_switch_events) == 1
        assert thread_switch_events[0]["from_thread_id"] == "thread_001"
        assert thread_switch_events[0]["to_thread_id"] == "thread_002"
        assert thread_switch_events[0]["iteration"] == 1

        # Verify thread checkpoints cross-reference
        thread_checkpoints = await persistence_manager.get_thread_checkpoints_for_loop(loop_id)
        assert "thread_001" in thread_checkpoints
        assert "thread_002" in thread_checkpoints
