"""Tests for SootheRunner checkpoint event emission (RFC-0010)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.config import SootheConfig
from soothe.core.artifact_store import RunArtifactStore
from soothe.core.runner import RunnerState, SootheRunner
from soothe.core.runner._runner_autonomous import AutonomousMixin
from soothe.protocols.planner import Plan, PlanStep


class TestCheckpointEventEmission:
    """Test that _save_checkpoint emits stream events (RFC-0010)."""

    @pytest.mark.asyncio
    async def test_checkpoint_saved_event_emitted(self, tmp_path: Path) -> None:
        """Verify soothe.lifecycle.checkpoint.saved event is emitted on successful save."""
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

        # Should emit exactly one event
        assert len(events) == 1
        # StreamChunk is a tuple: ((), "custom", data)
        event_data = events[0][2]  # Third element is the data dict

        # Verify event structure
        assert event_data["type"] == "soothe.lifecycle.checkpoint.saving"
        assert event_data["thread_id"] == "test-thread-123"
        assert "completed_steps" in event_data
        assert "completed_goals" in event_data
        assert isinstance(event_data["completed_steps"], int)
        assert isinstance(event_data["completed_goals"], int)

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
        """Verify completed_steps count is accurate."""
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

        assert len(events) == 1
        # StreamChunk is a tuple: ((), "custom", data)
        event_data = events[0][2]  # Third element is the data dict
        assert event_data["completed_steps"] == 2  # s1 and s2 are completed


class TestStepObservationReuse:
    """Test that step execution reuses query-scoped observation."""

    @pytest.mark.asyncio
    async def test_execute_step_inherits_parent_observation(self) -> None:
        runner = object.__new__(SootheRunner)
        runner._memory = MagicMock()
        runner._context = MagicMock()
        runner._current_plan = None
        runner._concurrency = SimpleNamespace(acquire_llm_call=_noop_acquire_llm_call)

        observed: dict[str, object] = {}

        async def _fake_stream_phase(step_input: str, step_state: RunnerState):
            observed["step_input"] = step_input
            observed["context_projection"] = step_state.context_projection
            observed["recalled_memories"] = list(step_state.recalled_memories)
            observed["observation_scope_key"] = step_state.observation_scope_key
            step_state.full_response.append("step complete")
            if False:
                yield ()

        runner._stream_phase = _fake_stream_phase  # type: ignore[method-assign]

        parent_state = RunnerState(
            thread_id="thread-1",
            context_projection=SimpleNamespace(
                entries=[SimpleNamespace(source="ctx", content="data")]
            ),
            recalled_memories=[SimpleNamespace(source_thread="thread-0", content="memo")],
            observation_scope_key="analyze project structure",
        )
        step = PlanStep(id="S_1", description="Inspect repository layout")

        chunks = [
            chunk
            async for chunk in runner._execute_step(
                step,
                goal_description="Analyze project structure",
                dependency_results=[],
                thread_id="thread-1__step_S_1",
                state=parent_state,
                batch_index=0,
            )
        ]

        assert chunks[0][2]["type"] == "soothe.cognition.plan.step.started"
        assert chunks[-1][2]["type"] == "soothe.cognition.plan.step.completed"
        assert observed["context_projection"] is parent_state.context_projection
        assert observed["recalled_memories"] == parent_state.recalled_memories
        assert observed["observation_scope_key"] == "analyze project structure"
        runner._memory.recall.assert_not_called()
        runner._context.project.assert_not_called()


def _noop_acquire_llm_call() -> _NoopAsyncContext:
    return _NoopAsyncContext()


async def _empty_async_generator(*args, **kwargs):
    if False:
        yield args, kwargs


class TestAutonomousObservationReuse:
    """Test autonomous goal execution reuses parent observation."""

    @pytest.mark.asyncio
    async def test_execute_autonomous_goal_inherits_parent_observation(self) -> None:
        runner = object.__new__(SootheRunner)
        runner._memory = MagicMock()
        runner._context = MagicMock()
        runner._planner = None
        runner._goal_engine = AsyncMock()
        runner._artifact_store = None
        runner._current_plan = None
        runner._config = SootheConfig()
        runner._concurrency = SimpleNamespace(acquire_llm_call=_noop_acquire_llm_call)
        runner._store_iteration_record = AsyncMock()
        runner._save_checkpoint = _empty_async_generator

        observed: dict[str, object] = {}

        async def _fake_stream_phase(step_input: str, step_state: RunnerState):
            observed["step_input"] = step_input
            observed["context_projection"] = step_state.context_projection
            observed["recalled_memories"] = list(step_state.recalled_memories)
            observed["observation_scope_key"] = step_state.observation_scope_key
            step_state.full_response.append("goal complete")
            if False:
                yield ()

        runner._stream_phase = _fake_stream_phase  # type: ignore[method-assign]
        runner._synthesize_root_goal_report = MagicMock(return_value="summary")

        parent_state = RunnerState(
            thread_id="thread-1",
            context_projection=SimpleNamespace(
                entries=[SimpleNamespace(source="ctx", content="data")]
            ),
            recalled_memories=[SimpleNamespace(source_thread="thread-0", content="memo")],
            observation_scope_key="analyze project structure",
        )
        goal = SimpleNamespace(
            id="G_1",
            description="Inspect repository layout",
            plan_count=0,
            depends_on=[],
            report=None,
        )

        chunks = [
            chunk
            async for chunk in AutonomousMixin._execute_autonomous_goal(
                runner,
                goal,
                parent_state=parent_state,
                thread_id="thread-1__goal_G_1",
                user_input="analyze project structure",
                iteration_records=[],
                total_iterations=0,
                parallel_goals=1,
            )
        ]

        assert chunks[0][2]["type"] == "soothe.lifecycle.iteration.started"
        assert observed["context_projection"] is parent_state.context_projection
        assert observed["recalled_memories"] == parent_state.recalled_memories
        assert observed["observation_scope_key"] == "analyze project structure"
        runner._memory.recall.assert_not_called()
        runner._context.project.assert_not_called()


class _NoopAsyncContext:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False
