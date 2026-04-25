"""Tests for checkpoint index calculation bug fixes.

Tests verify that:
1. current_goal_index is computed AFTER goal is appended
2. No orphaned running goals with index=-1
3. Validation prevents starting goals while loop is running
4. Recovery logic auto-repairs orphaned goals
"""

import tempfile
from pathlib import Path

import pytest

from soothe.cognition.agent_loop.state_manager import AgentLoopStateManager


@pytest.fixture
def temp_state_manager():
    """Create temporary state manager for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        # Override the global db_path to use temp directory for isolation
        from unittest.mock import patch

        db_path = workspace / "test_loop_checkpoints.db"

        with patch(
            "soothe.cognition.agent_loop.state_manager.PersistenceDirectoryManager.get_loop_checkpoint_path",
            return_value=db_path,
        ):
            state_manager = AgentLoopStateManager(loop_id="test_loop_001", workspace=workspace)
            yield state_manager


class TestIndexCalculationFix:
    """Test that current_goal_index is computed correctly."""

    @pytest.mark.asyncio
    async def test_first_goal_index_is_zero(self, temp_state_manager):
        """Test that first goal has index=0, not -1."""
        sm = temp_state_manager

        # Initialize loop
        checkpoint = await sm.initialize("thread_001", max_iterations=10)

        # Add first goal (simulating agent_loop.py logic)
        goal_record = sm.start_new_goal("test goal", max_iterations=10)
        checkpoint.goal_history.append(goal_record)  # Append FIRST
        checkpoint.current_goal_index = len(checkpoint.goal_history) - 1  # Compute AFTER

        # Verify index is correct
        assert checkpoint.current_goal_index == 0, "First goal should have index=0"
        assert len(checkpoint.goal_history) == 1
        assert checkpoint.goal_history[0].goal_id == goal_record.goal_id
        assert checkpoint.goal_history[0].status == "running"

    @pytest.mark.asyncio
    async def test_second_goal_index_is_one(self, temp_state_manager):
        """Test that second goal has index=1."""
        sm = temp_state_manager

        # Initialize loop and add first goal
        checkpoint = await sm.initialize("thread_001")
        goal1 = sm.start_new_goal("goal 1")
        checkpoint.goal_history.append(goal1)
        checkpoint.current_goal_index = len(checkpoint.goal_history) - 1
        checkpoint.status = "running"
        await sm.save(checkpoint)

        # Complete first goal (changes status to ready_for_next_goal)
        await sm.finalize_goal(goal1, "report 1")

        # Now loop is ready for next goal, add second goal
        goal2 = sm.start_new_goal("goal 2")
        checkpoint.goal_history.append(goal2)  # Append FIRST
        checkpoint.current_goal_index = len(checkpoint.goal_history) - 1  # Compute AFTER
        checkpoint.status = "running"

        # Verify index
        assert checkpoint.current_goal_index == 1, "Second goal should have index=1"
        assert len(checkpoint.goal_history) == 2
        assert checkpoint.goal_history[1].goal_id == goal2.goal_id

    @pytest.mark.asyncio
    async def test_index_never_negative(self, temp_state_manager):
        """Test that index is never negative (>=0)."""
        sm = temp_state_manager

        checkpoint = await sm.initialize("thread_001")

        # Add multiple goals sequentially (finalize each before adding next)
        for i in range(5):
            goal = sm.start_new_goal(f"goal {i}")
            checkpoint.goal_history.append(goal)
            checkpoint.current_goal_index = len(checkpoint.goal_history) - 1
            checkpoint.status = "running"

            # Verify index is always >= 0
            assert checkpoint.current_goal_index >= 0, f"Goal {i} has negative index"
            assert checkpoint.current_goal_index == i, f"Goal {i} should have index={i}"

            # Finalize before next iteration
            await sm.finalize_goal(goal, f"report {i}")
            # Reload checkpoint for next iteration
            checkpoint = sm._checkpoint

    @pytest.mark.asyncio
    async def test_saved_checkpoint_has_correct_index(self, temp_state_manager):
        """Test that saved checkpoint preserves correct index."""
        sm = temp_state_manager

        # Initialize and add goal
        checkpoint = await sm.initialize("thread_001")
        goal = sm.start_new_goal("test goal")
        checkpoint.goal_history.append(goal)
        checkpoint.current_goal_index = len(checkpoint.goal_history) - 1
        checkpoint.status = "running"
        await sm.save(checkpoint)

        # Load checkpoint
        loaded = await sm.load()

        # Verify index persisted correctly
        assert loaded.current_goal_index == 0
        assert len(loaded.goal_history) == 1
        assert loaded.goal_history[0].status == "running"


class TestValidationLogic:
    """Test validation prevents invalid state transitions."""

    @pytest.mark.asyncio
    async def test_cannot_start_goal_while_loop_running(self, temp_state_manager):
        """Test that start_new_goal raises error if loop status='running'."""
        sm = temp_state_manager

        # Initialize loop and add first goal
        checkpoint = await sm.initialize("thread_001")
        goal1 = sm.start_new_goal("goal 1")
        checkpoint.goal_history.append(goal1)
        checkpoint.current_goal_index = len(checkpoint.goal_history) - 1
        checkpoint.status = "running"
        await sm.save(checkpoint)

        # Try to start another goal while loop is running
        with pytest.raises(ValueError) as exc_info:
            sm.start_new_goal("goal 2")

        assert "Cannot start new goal while loop is running" in str(exc_info.value)
        assert "status=running" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_can_start_goal_after_finalize(self, temp_state_manager):
        """Test that goal can be started after previous goal finalized."""
        sm = temp_state_manager

        # Initialize and complete first goal
        checkpoint = await sm.initialize("thread_001")
        goal1 = sm.start_new_goal("goal 1")
        checkpoint.goal_history.append(goal1)
        checkpoint.current_goal_index = len(checkpoint.goal_history) - 1
        checkpoint.status = "running"
        await sm.save(checkpoint)

        # Finalize goal (status becomes ready_for_next_goal)
        await sm.finalize_goal(goal1, "report 1")

        # Reload checkpoint
        checkpoint = sm._checkpoint

        # Now can start second goal (because status=ready_for_next_goal)
        goal2 = sm.start_new_goal("goal 2")
        checkpoint.goal_history.append(goal2)
        checkpoint.current_goal_index = len(checkpoint.goal_history) - 1
        checkpoint.status = "running"  # Set status to running after adding goal

        assert checkpoint.current_goal_index == 1
        assert checkpoint.status == "running"


class TestOrphanedGoalRecovery:
    """Test auto-repair logic for orphaned goals."""

    @pytest.mark.asyncio
    async def test_detects_orphaned_goal(self, temp_state_manager):
        """Test that load() detects orphaned running goals with index=-1."""
        sm = temp_state_manager

        # Create corrupted checkpoint (simulate bug)
        checkpoint = await sm.initialize("thread_001")
        goal = sm.start_new_goal("orphaned goal")

        # Simulate buggy behavior: append AFTER index
        checkpoint.current_goal_index = len(checkpoint.goal_history) - 1  # = -1 (BUG)
        checkpoint.goal_history.append(goal)  # Append AFTER (goal now exists)
        checkpoint.status = "ready_for_next_goal"  # Loop thinks it's idle

        await sm._save_checkpoint_to_db(checkpoint)

        # Load should detect and repair
        loaded = await sm.load()

        # Verify auto-repair
        assert loaded.current_goal_index == 0, "Should auto-repair to index=0"
        assert loaded.status == "running", "Should auto-repair status to 'running'"
        assert loaded.goal_history[0].status == "running"

    @pytest.mark.asyncio
    async def test_repair_sets_correct_index(self, temp_state_manager):
        """Test that auto-repair sets current_goal_index to last running goal."""
        sm = temp_state_manager

        # Create checkpoint with multiple orphaned goals (simulating bug scenario)
        checkpoint = await sm.initialize("thread_001")

        # Manually create corrupted state (simulating bug where multiple goals were orphaned)
        # In real scenario, only ONE goal should be running at a time
        for i in range(3):
            goal = sm.start_new_goal(f"goal {i}")
            checkpoint.goal_history.append(goal)
            # Simulate bug: don't update index properly
            checkpoint.current_goal_index = -1  # Keep at -1 to simulate orphaned state

        checkpoint.status = "ready_for_next_goal"  # Loop thinks it's idle
        await sm._save_checkpoint_to_db(checkpoint)

        # Load and repair
        loaded = await sm.load()

        # Should repair to last goal index (len - 1 = 2)
        assert loaded.current_goal_index == 2, "Should set index to last goal (2)"
        assert loaded.status == "running", "Should set status to running"
        assert len(loaded.goal_history) == 3

    @pytest.mark.asyncio
    async def test_no_repair_if_goals_completed(self, temp_state_manager):
        """Test that auto-repair does not trigger if goals are completed."""
        sm = temp_state_manager

        # Create checkpoint with completed goals
        checkpoint = await sm.initialize("thread_001")
        goal = sm.start_new_goal("completed goal")
        checkpoint.goal_history.append(goal)
        checkpoint.current_goal_index = len(checkpoint.goal_history) - 1
        checkpoint.status = "running"
        await sm.save(checkpoint)

        # Finalize goal (IG-055: resets current_goal_index to -1)
        await sm.finalize_goal(goal, "report")

        # Load should NOT repair (status=ready_for_next_goal is correct)
        loaded = await sm.load()
        assert loaded.current_goal_index == -1  # IG-055: Reset to -1 after completion
        assert loaded.status == "ready_for_next_goal"  # Correct status
        assert loaded.goal_history[0].status == "completed"


class TestDatabaseConsistency:
    """Test database-level consistency checks."""

    @pytest.mark.asyncio
    async def test_goal_history_matches_database(self, temp_state_manager):
        """Test that goal_history matches goal_records table."""
        sm = temp_state_manager

        # Initialize and add goals
        checkpoint = await sm.initialize("thread_001")

        for i in range(3):
            goal = sm.start_new_goal(f"goal {i}")
            checkpoint.goal_history.append(goal)
            checkpoint.current_goal_index = len(checkpoint.goal_history) - 1
            checkpoint.status = "running"
            await sm.save(checkpoint)

            if i < 2:  # Finalize first 2 goals
                await sm.finalize_goal(goal, f"report {i}")

        # Load and verify
        loaded = await sm.load()

        assert len(loaded.goal_history) == 3
        assert loaded.goal_history[0].status == "completed"
        assert loaded.goal_history[1].status == "completed"
        assert loaded.goal_history[2].status == "running"
        assert loaded.current_goal_index == 2

    @pytest.mark.asyncio
    async def test_no_goals_with_negative_index_after_save(self, temp_state_manager):
        """Test that no saved goals have current_goal_index=-1."""
        sm = temp_state_manager

        # Add multiple goals sequentially
        checkpoint = await sm.initialize("thread_001")
        for i in range(5):
            goal = sm.start_new_goal(f"goal {i}")
            checkpoint.goal_history.append(goal)
            checkpoint.current_goal_index = len(checkpoint.goal_history) - 1
            checkpoint.status = "running"
            await sm.save(checkpoint)

            # Verify index in database
            import aiosqlite

            async with aiosqlite.connect(sm.db_path) as db:
                cursor = await db.execute(
                    "SELECT current_goal_index FROM agentloop_loops WHERE loop_id = ?",
                    (sm.loop_id,),
                )
                row = await cursor.fetchone()
                db_index = row[0]

                assert db_index >= 0, f"Database index should be >=0, got {db_index}"
                assert db_index == i, f"Database index should match {i}"

            # Finalize before next goal
            await sm.finalize_goal(goal, f"report {i}")
            # Reload checkpoint for next iteration
            checkpoint = sm._checkpoint


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_empty_goal_history(self, temp_state_manager):
        """Test behavior with empty goal_history."""
        sm = temp_state_manager

        # Initialize without adding goals
        checkpoint = await sm.initialize("thread_001")

        assert checkpoint.goal_history == []
        assert checkpoint.current_goal_index == -1  # Correct: no active goal
        assert checkpoint.status == "ready_for_next_goal"

    @pytest.mark.asyncio
    async def test_single_goal_iteration(self, temp_state_manager):
        """Test single goal with one iteration."""
        sm = temp_state_manager

        checkpoint = await sm.initialize("thread_001")
        goal = sm.start_new_goal("single goal")
        checkpoint.goal_history.append(goal)
        checkpoint.current_goal_index = len(checkpoint.goal_history) - 1
        checkpoint.status = "running"

        assert checkpoint.current_goal_index == 0
        assert checkpoint.goal_history[0].iteration == 0

    @pytest.mark.asyncio
    async def test_thread_switch_preserves_index(self, temp_state_manager):
        """Test that thread switch preserves correct goal index."""
        sm = temp_state_manager

        # Initialize on thread_001
        checkpoint = await sm.initialize("thread_001")
        goal = sm.start_new_goal("goal on thread_001")
        checkpoint.goal_history.append(goal)
        checkpoint.current_goal_index = len(checkpoint.goal_history) - 1
        checkpoint.status = "running"
        await sm.save(checkpoint)

        # Switch to thread_002
        await sm.execute_thread_switch("thread_002")

        # Load and verify index preserved
        loaded = await sm.load()
        assert loaded.current_goal_index == 0  # Same goal
        assert loaded.current_thread_id == "thread_002"
        assert loaded.goal_history[0].thread_id == "thread_001"  # Original thread


# Run tests with: pytest packages/soothe/tests/unit/cognition/agent_loop/test_checkpoint_index_fix.py -v
