"""Tests for SootheRunner checkpoint event emission (RFC-0010)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from soothe.config import SootheConfig
from soothe.runner import SootheRunner
from soothe.runner._artifact_store import RunArtifactStore
from soothe.runner._types import RunnerState
from soothe.protocols.planner import Plan, PlanStep


class TestCheckpointEventEmission:
    """Test that _save_checkpoint emits stream events (RFC-0010)."""

    @pytest.mark.asyncio
    async def test_checkpoint_saved_event_emitted(self, tmp_path: Path) -> None:
        """IG-271: checkpoint events removed from normal execution, replaced with logging."""
        # Create a minimal runner with artifact store on state (IG-110)
        config = SootheConfig()
        runner = object.__new__(SootheRunner)
        runner._config = config
        runner._goal_engine = None
        runner._logger = MagicMock()

        state = RunnerState()
        state.thread_id = "test-thread-123"
        state.artifact_store = RunArtifactStore("test-thread-123", soothe_home=str(tmp_path))

        events = [
            chunk
            async for chunk in runner._save_checkpoint(
                state,
                user_input="test query",
                mode="single_pass",
                status="in_progress",
            )
        ]

        # IG-271: No events emitted in normal execution (replaced with logging)
        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_checkpoint_event_not_emitted_without_artifact_store(
        self, tmp_path: Path
    ) -> None:
        """Verify no event is emitted if artifact store is not initialized."""
        # Create runner without artifact store on state
        config = SootheConfig()
        runner = object.__new__(SootheRunner)
        runner._config = config
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
        """IG-271: checkpoint events removed from normal execution, replaced with logging."""
        # Create a minimal runner with artifact store on state (IG-110)
        config = SootheConfig()
        runner = object.__new__(SootheRunner)
        runner._config = config
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
        state.artifact_store = RunArtifactStore("test-thread-789", soothe_home=str(tmp_path))

        events = [
            chunk
            async for chunk in runner._save_checkpoint(
                state,
                user_input="test query",
                mode="autonomous",
                status="in_progress",
            )
        ]

        # IG-271: No events emitted in normal execution (replaced with logging)
        assert len(events) == 0
