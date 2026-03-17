"""Tests for SootheRunner checkpoint event emission (RFC-0010)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from soothe.config import SootheConfig
from soothe.core.artifact_store import RunArtifactStore
from soothe.core.runner import RunnerState, SootheRunner


class TestCheckpointEventEmission:
    """Test that _save_checkpoint emits stream events (RFC-0010)."""

    @pytest.mark.asyncio
    async def test_checkpoint_saved_event_emitted(self, tmp_path: Path) -> None:
        """Verify soothe.checkpoint.saved event is emitted on successful save."""
        # Create a minimal runner with artifact store
        config = SootheConfig()
        runner = object.__new__(SootheRunner)
        runner._artifact_store = RunArtifactStore("test-thread-123", soothe_home=str(tmp_path))
        runner._goal_engine = None
        runner._logger = MagicMock()

        state = RunnerState()
        state.thread_id = "test-thread-123"

        events = [
            chunk
            async for chunk in runner._save_checkpoint(
                state,
                user_input="test query",
                mode="single_pass",
                status="in_progress",
            )
        ]

        # Should emit exactly one event
        assert len(events) == 1
        # StreamChunk is a tuple: ((), "custom", data)
        event_data = events[0][2]  # Third element is the data dict

        # Verify event structure
        assert event_data["type"] == "soothe.checkpoint.saved"
        assert event_data["thread_id"] == "test-thread-123"
        assert "completed_steps" in event_data
        assert "completed_goals" in event_data
        assert isinstance(event_data["completed_steps"], int)
        assert isinstance(event_data["completed_goals"], int)

    @pytest.mark.asyncio
    async def test_checkpoint_event_not_emitted_without_artifact_store(self, tmp_path: Path) -> None:
        """Verify no event is emitted if artifact store is not initialized."""
        # Create runner without artifact store
        config = SootheConfig()
        runner = object.__new__(SootheRunner)
        runner._artifact_store = None
        runner._goal_engine = None
        runner._logger = MagicMock()

        state = RunnerState()
        state.thread_id = "test-thread-456"

        events = [
            chunk
            async for chunk in runner._save_checkpoint(
                state,
                user_input="test query",
                mode="single_pass",
                status="in_progress",
            )
        ]

        # Should emit no events (artifact store is None)
        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_checkpoint_event_counts_steps(self, tmp_path: Path) -> None:
        """Verify completed_steps count is accurate."""
        from soothe.protocols.planner import Plan, PlanStep

        # Create a minimal runner with artifact store
        config = SootheConfig()
        runner = object.__new__(SootheRunner)
        runner._artifact_store = RunArtifactStore("test-thread-789", soothe_home=str(tmp_path))
        runner._goal_engine = None
        runner._logger = MagicMock()

        # Create a plan with some completed steps
        plan = Plan(
            goal="Test goal",
            steps=[
                PlanStep(id="s1", description="Step 1", status="completed", result="Done"),
                PlanStep(id="s2", description="Step 2", status="completed", result="Done"),
                PlanStep(id="s3", description="Step 3", status="pending"),
            ],
        )

        state = RunnerState()
        state.thread_id = "test-thread-789"
        state.plan = plan

        events = [
            chunk
            async for chunk in runner._save_checkpoint(
                state,
                user_input="test query",
                mode="autonomous",
                status="in_progress",
            )
        ]

        assert len(events) == 1
        # StreamChunk is a tuple: ((), "custom", data)
        event_data = events[0][2]  # Third element is the data dict
        assert event_data["completed_steps"] == 2  # s1 and s2 are completed
