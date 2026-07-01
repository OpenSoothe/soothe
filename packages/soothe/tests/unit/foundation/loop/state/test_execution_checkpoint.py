"""Unit tests for ExecutionCheckpoint and WaveMetrics (RFC-626 Phase 3).

Tests for the new execution checkpoint pattern with execution-only fields.
"""

from datetime import UTC, datetime

import pytest
from soothe.foundation.sloop.state.execution_checkpoint import (
    ExecutionCheckpoint,
    GoalIndexEntry,
    WaveMetrics,
)


class TestWaveMetrics:
    """Tests for WaveMetrics model."""

    def test_default_values(self) -> None:
        """Test that all defaults are zero/empty."""
        metrics = WaveMetrics()
        assert metrics.wave_index == 0
        assert metrics.tool_call_count == 0
        assert metrics.subagent_task_count == 0
        assert not metrics.hit_subagent_cap
        assert not metrics.hit_tool_budget
        assert metrics.output_length == 0
        assert metrics.error_count == 0
        assert metrics.tokens_used == 0
        assert metrics.duration_ms == 0

    def test_wave_index_validation(self) -> None:
        """Test wave_index field bounds."""
        # Negative wave_index should fail
        with pytest.raises(ValueError):
            WaveMetrics(wave_index=-1)

        # Valid wave_index
        metrics = WaveMetrics(wave_index=5)
        assert metrics.wave_index == 5

    def test_populated_metrics(self) -> None:
        """Test metrics with values."""
        metrics = WaveMetrics(
            wave_index=3,
            tool_call_count=10,
            subagent_task_count=2,
            hit_subagent_cap=True,
            output_length=5000,
            error_count=1,
            tokens_used=1500,
            duration_ms=2500,
        )
        assert metrics.wave_index == 3
        assert metrics.tool_call_count == 10
        assert metrics.subagent_task_count == 2
        assert metrics.hit_subagent_cap
        assert metrics.output_length == 5000
        assert metrics.error_count == 1
        assert metrics.tokens_used == 1500
        assert metrics.duration_ms == 2500


class TestGoalIndexEntry:
    """Tests for GoalIndexEntry model."""

    def test_default_values(self) -> None:
        """Test default values for goal index entry."""
        now = datetime.now(UTC)
        entry = GoalIndexEntry(goal_id="test-goal-001", thread_id="thread-123", started_at=now)
        assert entry.goal_id == "test-goal-001"
        assert entry.thread_id == "thread-123"
        assert entry.status == "running"
        assert entry.duration_ms == 0
        assert entry.tokens_used == 0
        assert entry.started_at is not None
        assert entry.completed_at is None

    def test_status_validation(self) -> None:
        """Test status field validation."""
        now = datetime.now(UTC)
        # Invalid status should fail
        with pytest.raises(ValueError):
            GoalIndexEntry(goal_id="test", thread_id="t1", status="invalid", started_at=now)

        # Valid statuses
        for status in ["running", "completed", "failed", "cancelled"]:
            entry = GoalIndexEntry(goal_id="test", thread_id="t1", status=status, started_at=now)
            assert entry.status == status

    def test_completed_entry(self) -> None:
        """Test completed goal entry."""
        now = datetime.now(UTC)
        entry = GoalIndexEntry(
            goal_id="test-goal-001",
            thread_id="thread-123",
            status="completed",
            duration_ms=10000,
            tokens_used=5000,
            started_at=now,
            completed_at=now,
        )
        assert entry.status == "completed"
        assert entry.completed_at is not None


class TestExecutionCheckpoint:
    """Tests for ExecutionCheckpoint model (schema 5.0)."""

    def test_default_values(self) -> None:
        """Test default values for execution checkpoint."""
        checkpoint = ExecutionCheckpoint(loop_id="test-loop-001", thread_id="thread-123")
        assert checkpoint.loop_id == "test-loop-001"
        assert checkpoint.thread_id == "thread-123"
        assert checkpoint.iteration == 0
        assert checkpoint.wave_metrics == WaveMetrics()
        assert checkpoint.status == "idle"
        assert checkpoint.current_goal_id is None
        assert checkpoint.schema_version == "5.0"

    def test_iteration_validation(self) -> None:
        """Test iteration field validation."""
        # Negative iteration should fail
        with pytest.raises(ValueError):
            ExecutionCheckpoint(loop_id="test", thread_id="t1", iteration=-1)

        # Valid iteration
        checkpoint = ExecutionCheckpoint(loop_id="test", thread_id="t1", iteration=5)
        assert checkpoint.iteration == 5

    def test_status_validation(self) -> None:
        """Test status field validation."""
        # Invalid status should fail
        with pytest.raises(ValueError):
            ExecutionCheckpoint(loop_id="test", thread_id="t1", status="invalid")

        # Valid statuses (per RFC-626 ExecutionCheckpoint)
        for status in ["running", "idle", "finalized", "cancelled"]:
            checkpoint = ExecutionCheckpoint(loop_id="test", thread_id="t1", status=status)
            assert checkpoint.status == status

    def test_with_goal_id(self) -> None:
        """Test checkpoint with goal ID."""
        checkpoint = ExecutionCheckpoint(
            loop_id="test-loop",
            thread_id="thread-123",
            iteration=3,
            status="running",
            current_goal_id="goal-002",
        )
        assert checkpoint.current_goal_id == "goal-002"
        assert checkpoint.iteration == 3
        assert checkpoint.status == "running"

    def test_touch_updates_timestamp(self) -> None:
        """Test that touch() updates updated_at."""
        import time

        checkpoint = ExecutionCheckpoint(loop_id="test", thread_id="t1")
        old_updated = checkpoint.updated_at
        # Small delay to ensure timestamp differs
        time.sleep(0.01)
        checkpoint.touch()
        assert checkpoint.updated_at > old_updated

    def test_is_terminal(self) -> None:
        """Test is_terminal() method."""
        terminal_states = ["finalized", "cancelled"]
        for status in terminal_states:
            checkpoint = ExecutionCheckpoint(loop_id="test", thread_id="t1", status=status)
            assert checkpoint.is_terminal()

        non_terminal_states = ["running", "idle"]
        for status in non_terminal_states:
            checkpoint = ExecutionCheckpoint(loop_id="test", thread_id="t1", status=status)
            assert not checkpoint.is_terminal()

    def test_serialization_roundtrip(self) -> None:
        """Test JSON serialization and deserialization."""
        checkpoint = ExecutionCheckpoint(
            loop_id="test-loop",
            thread_id="thread-123",
            iteration=5,
            wave_metrics=WaveMetrics(
                wave_index=5,
                tool_call_count=10,
                tokens_used=1500,
            ),
            status="running",
            current_goal_id="goal-001",
        )

        # Serialize to JSON
        json_str = checkpoint.model_dump_json()

        # Deserialize from JSON
        recovered = ExecutionCheckpoint.model_validate_json(json_str)

        assert recovered.loop_id == checkpoint.loop_id
        assert recovered.iteration == checkpoint.iteration
        assert recovered.wave_metrics.tool_call_count == checkpoint.wave_metrics.tool_call_count
        assert recovered.current_goal_id == checkpoint.current_goal_id


class TestExecutionCheckpointRecovery:
    """Tests for execution checkpoint recovery flow (RFC-626 Phase 3)."""

    def test_recovery_from_minimal_checkpoint(self) -> None:
        """Test recovery with minimal checkpoint data.

        Goal state is recovered from CE persistence, not from checkpoint.
        """
        checkpoint = ExecutionCheckpoint(
            loop_id="test-loop",
            thread_id="thread-123",
            status="running",
            iteration=2,
        )

        # Checkpoint should have execution-only fields
        assert checkpoint.loop_id == "test-loop"
        assert checkpoint.status == "running"
        assert checkpoint.iteration == 2

        # Goal state would be recovered from CE GoalNode
        # This test validates checkpoint has NO goal_text, steps, etc.
        # (those fields don't exist in ExecutionCheckpoint)

    def test_wave_metrics_recovery(self) -> None:
        """Test that wave metrics persist through checkpoint save/load."""
        checkpoint = ExecutionCheckpoint(
            loop_id="test-loop",
            thread_id="thread-123",
            wave_metrics=WaveMetrics(
                wave_index=3,
                tool_call_count=5,
                subagent_task_count=2,
                hit_subagent_cap=True,
            ),
        )

        json_data = checkpoint.model_dump()
        recovered = ExecutionCheckpoint.model_validate(json_data)

        assert recovered.wave_metrics.wave_index == 3
        assert recovered.wave_metrics.tool_call_count == 5
        assert recovered.wave_metrics.hit_subagent_cap
