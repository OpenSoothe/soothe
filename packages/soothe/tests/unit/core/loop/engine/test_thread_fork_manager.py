"""Unit tests for ThreadForkManager (RFC-223).

Tests cover:
- select_fork_source: Fork source selection based on direct dependencies
- fork_checkpoint: Checkpoint copy via LangGraph acopy_thread
- prepare_thread_for_step: Full preparation flow with state updates
"""

from unittest.mock import AsyncMock

import pytest

from soothe.core.loop.engine.thread_fork_manager import ThreadForkManager
from soothe.core.loop.state.schemas import AgentDecision, LoopState, StepAction


class TestSelectForkSource:
    """Tests for select_fork_source method."""

    def test_no_deps_returns_main_thread(self) -> None:
        """First step (no deps) forks from main thread."""
        manager = ThreadForkManager(None)
        step = StepAction(id="A", description="Test step", dependencies=[])
        decision = AgentDecision(type="execute_steps", steps=[step])
        state = LoopState(thread_id="loop1", goal="test goal")

        source = manager.select_fork_source(step, decision, state)
        assert source == "loop1"

    def test_singleton_dep_returns_predecessor_thread(self) -> None:
        """Single direct dep forks from predecessor's thread."""
        manager = ThreadForkManager(None)
        step_b = StepAction(id="B", description="Test step B", dependencies=["A"])
        step_a = StepAction(id="A", description="Test step", dependencies=[])
        decision = AgentDecision(type="execute_steps", steps=[step_a, step_b])
        state = LoopState(
            thread_id="loop1",
            goal="test goal",
            step_thread_ids={"A": "loop1__step_A"},
        )

        source = manager.select_fork_source(step_b, decision, state)
        assert source == "loop1__step_A"

    def test_chain_singleton_inherits_from_immediate_predecessor(self) -> None:
        """Chain A→B→C: C forks from B (direct dep), not A."""
        manager = ThreadForkManager(None)
        step_a = StepAction(id="A", description="Test step", dependencies=[])
        step_b = StepAction(id="B", description="Test step B", dependencies=["A"])
        step_c = StepAction(id="C", description="Test step C", dependencies=["B"])
        decision = AgentDecision(type="execute_steps", steps=[step_a, step_b, step_c])
        state = LoopState(
            thread_id="loop1",
            goal="test goal",
            step_thread_ids={"A": "loop1__step_A", "B": "loop1__step_B"},
        )

        source = manager.select_fork_source(step_c, decision, state)
        assert source == "loop1__step_B"

    def test_multi_dep_returns_main_thread(self) -> None:
        """Multiple direct deps fallback to main thread."""
        manager = ThreadForkManager(None)
        step_c = StepAction(id="C", description="Test step C", dependencies=["A", "B"])
        decision = AgentDecision(
            type="execute_steps",
            steps=[
                StepAction(id="A", description="Test step A", dependencies=[]),
                StepAction(id="B", description="Test step B", dependencies=[]),
                step_c,
            ],
        )
        state = LoopState(
            thread_id="loop1",
            goal="test goal",
            step_thread_ids={"A": "loop1__step_A", "B": "loop1__step_B"},
        )

        source = manager.select_fork_source(step_c, decision, state)
        assert source == "loop1"

    def test_missing_predecessor_thread_fallback_to_main(self) -> None:
        """If predecessor thread_id not tracked, fallback to main."""
        manager = ThreadForkManager(None)
        step_b = StepAction(id="B", description="Test step B", dependencies=["A"])
        decision = AgentDecision(
            type="execute_steps",
            steps=[
                StepAction(id="A", description="Test step A", dependencies=[]),
                step_b,
            ],
        )
        state = LoopState(thread_id="loop1", goal="test goal")  # No step_thread_ids

        source = manager.select_fork_source(step_b, decision, state)
        assert source == "loop1"

    def test_empty_dependencies_list_returns_main(self) -> None:
        """Explicitly empty dependencies list → main thread."""
        manager = ThreadForkManager(None)
        step = StepAction(id="A", description="Test step", dependencies=[])
        decision = AgentDecision(type="execute_steps", steps=[step])
        state = LoopState(thread_id="loop1", goal="test goal")

        source = manager.select_fork_source(step, decision, state)
        assert source == "loop1"

    def test_none_dependencies_returns_main(self) -> None:
        """None dependencies → main thread."""
        manager = ThreadForkManager(None)
        step = StepAction(id="A", description="Test step", dependencies=None)
        decision = AgentDecision(type="execute_steps", steps=[step])
        state = LoopState(thread_id="loop1", goal="test goal")

        source = manager.select_fork_source(step, decision, state)
        assert source == "loop1"


class TestForkCheckpoint:
    """Tests for fork_checkpoint method."""

    @pytest.mark.asyncio
    async def test_calls_acopy_thread(self) -> None:
        """Verify checkpointer.acopy_thread is called."""
        mock_checkpointer = AsyncMock()
        manager = ThreadForkManager(mock_checkpointer)

        result = await manager.fork_checkpoint("source1", "target1")

        mock_checkpointer.acopy_thread.assert_called_once_with("source1", "target1")
        assert result == "target1"

    @pytest.mark.asyncio
    async def test_failure_returns_source(self) -> None:
        """On failure, return source as fallback."""
        mock_checkpointer = AsyncMock()
        mock_checkpointer.acopy_thread = AsyncMock(side_effect=Exception("DB error"))
        manager = ThreadForkManager(mock_checkpointer)

        result = await manager.fork_checkpoint("source1", "target1")

        assert result == "source1"

    @pytest.mark.asyncio
    async def test_no_checkpointer_returns_source(self) -> None:
        """No checkpointer → skip fork, return source."""
        manager = ThreadForkManager(None)

        result = await manager.fork_checkpoint("source1", "target1")

        assert result == "source1"


class TestPrepareThreadForStep:
    """Tests for prepare_thread_for_step method."""

    @pytest.mark.asyncio
    async def test_updates_state_mappings_first_step(self) -> None:
        """Verify state mappings are updated for first step."""
        mock_checkpointer = AsyncMock()
        manager = ThreadForkManager(mock_checkpointer)
        step = StepAction(id="A", description="Test step", dependencies=[])
        decision = AgentDecision(type="execute_steps", steps=[step])
        state = LoopState(thread_id="loop1", goal="test goal")

        result = await manager.prepare_thread_for_step(step, decision, state, "loop1")

        assert result == "loop1__step_A"
        assert state.step_thread_ids["A"] == "loop1__step_A"
        assert state.thread_fork_sources["loop1__step_A"] == "loop1"

    @pytest.mark.asyncio
    async def test_singleton_step_tracks_lineage(self) -> None:
        """Singleton dep step tracks fork lineage."""
        mock_checkpointer = AsyncMock()
        manager = ThreadForkManager(mock_checkpointer)
        step_b = StepAction(id="B", description="Test step B", dependencies=["A"])
        decision = AgentDecision(
            type="execute_steps",
            steps=[
                StepAction(id="A", description="Test step A", dependencies=[]),
                step_b,
            ],
        )
        state = LoopState(
            thread_id="loop1",
            goal="test goal",
            step_thread_ids={"A": "loop1__step_A"},
        )

        result = await manager.prepare_thread_for_step(step_b, decision, state, "loop1")

        assert result == "loop1__step_B"
        assert state.thread_fork_sources["loop1__step_B"] == "loop1__step_A"

    @pytest.mark.asyncio
    async def test_multi_dep_step_fork_from_main(self) -> None:
        """Multi-dep step forks from main thread."""
        mock_checkpointer = AsyncMock()
        manager = ThreadForkManager(mock_checkpointer)
        step_c = StepAction(id="C", description="Test step C", dependencies=["A", "B"])
        decision = AgentDecision(
            type="execute_steps",
            steps=[
                StepAction(id="A", description="Test step A", dependencies=[]),
                StepAction(id="B", description="Test step B", dependencies=[]),
                step_c,
            ],
        )
        state = LoopState(
            thread_id="loop1",
            goal="test goal",
            step_thread_ids={"A": "loop1__step_A", "B": "loop1__step_B"},
        )

        result = await manager.prepare_thread_for_step(step_c, decision, state, "loop1")

        assert result == "loop1__step_C"
        assert state.thread_fork_sources["loop1__step_C"] == "loop1"

    @pytest.mark.asyncio
    async def test_fork_failure_uses_source_thread(self) -> None:
        """Fork failure returns source thread, still updates state."""
        mock_checkpointer = AsyncMock()
        mock_checkpointer.acopy_thread = AsyncMock(side_effect=Exception("DB error"))
        manager = ThreadForkManager(mock_checkpointer)
        step = StepAction(id="A", description="Test step", dependencies=[])
        decision = AgentDecision(type="execute_steps", steps=[step])
        state = LoopState(thread_id="loop1", goal="test goal")

        result = await manager.prepare_thread_for_step(step, decision, state, "loop1")

        # On failure, returns source thread
        assert result == "loop1"
        # State still updated with actual thread used
        assert state.step_thread_ids["A"] == "loop1"
