"""Unit tests for DreamingCoordinator (RFC-625)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.autopilot.dreaming_coordinator import DreamingCoordinator
from soothe.autopilot.monitor_models import DreamingContext, EpisodeSpec
from soothe.context.engine import ContextEngine
from soothe.context.models import GoalNode


@pytest.fixture
def mock_config() -> MagicMock:
    """Create mock SootheConfig with autonomous settings."""
    cfg = MagicMock()
    cfg.agent = MagicMock()
    cfg.agent.autopilot = MagicMock()

    dreaming_cfg = MagicMock()
    dreaming_cfg.episodic = MagicMock()
    dreaming_cfg.episodic.enabled = True
    dreaming_cfg.procedure = MagicMock()
    dreaming_cfg.procedure.enabled = True
    dreaming_cfg.semantic = MagicMock()
    dreaming_cfg.semantic.enabled = True
    dreaming_cfg.profile = MagicMock()
    dreaming_cfg.profile.enabled = True
    cfg.agent.autopilot.dreaming_modes = dreaming_cfg

    return cfg


@pytest.fixture
def mock_bus() -> MagicMock:
    """Create mock InternalEventBus."""
    bus = MagicMock()
    bus.emit = AsyncMock()
    bus.emit_autopilot_dreaming = AsyncMock()
    bus.emit_autopilot_awake = AsyncMock()
    return bus


@pytest.fixture
def mock_ce() -> ContextEngine:
    """Create mock ContextEngine."""
    ce = MagicMock(spec=ContextEngine)
    ce._dag = MagicMock()
    ce._dag.goals = {}

    goals = []
    for id_, desc, status, priority, deps, findings in [
        ("goal-1", "Completed goal", "completed", 50, [], ["Finding 1", "Finding 2"]),
        ("goal-2", "Another completed goal", "completed", 40, ["goal-1"], ["Finding 3"]),
    ]:
        goal = MagicMock(spec=GoalNode)
        goal.id = id_
        goal.description = desc
        goal.status = status
        goal.priority = priority
        goal.depends_on = deps
        goal.findings = findings
        ce._dag.goals[id_] = goal
        goals.append(goal)

    def get_goals_by_status(status: str | None) -> list[GoalNode]:
        if status is None:
            return goals
        return [g for g in goals if g.status == status]

    ce.get_goals_by_status = get_goals_by_status
    ce.get_ledger_entries = MagicMock(return_value=[])
    ce.record_episodic_memory = AsyncMock()

    return ce


@pytest.fixture
def coordinator(
    mock_ce: ContextEngine, mock_config: MagicMock, mock_bus: MagicMock
) -> DreamingCoordinator:
    """Create DreamingCoordinator instance."""
    return DreamingCoordinator(mock_ce, mock_config, mock_bus)


class TestDreamingCoordinator:
    """Tests for DreamingCoordinator class."""

    def test_initial_state_is_idle(self, coordinator: DreamingCoordinator) -> None:
        """DreamingCoordinator starts in idle state."""
        assert coordinator._dreaming_state == "idle"

    def test_get_enabled_modes_default_all(self, coordinator: DreamingCoordinator) -> None:
        """_get_enabled_modes returns all modes by default."""
        modes = coordinator._get_enabled_modes()

        assert "episodic" in modes
        assert "procedure" in modes
        assert "semantic" in modes
        assert "profile" in modes

    async def test_enter_dreaming_mode_emits_events(
        self, coordinator: DreamingCoordinator, mock_bus: MagicMock
    ) -> None:
        """enter_dreaming_mode emits start/end events."""
        await coordinator.enter_dreaming_mode()

        mock_bus.emit_autopilot_dreaming.assert_awaited_once()
        mock_bus.emit_autopilot_awake.assert_awaited_once()

    async def test_enter_dreaming_mode_sets_state(self, coordinator: DreamingCoordinator) -> None:
        """enter_dreaming_mode sets state to active then back to idle."""
        await coordinator.enter_dreaming_mode()

        assert coordinator._dreaming_state == "idle"

    async def test_enter_dreaming_mode_skips_if_already_active(
        self, coordinator: DreamingCoordinator, mock_bus: MagicMock
    ) -> None:
        """enter_dreaming_mode skips if already active."""
        coordinator._dreaming_state = "active"

        await coordinator.enter_dreaming_mode()

        mock_bus.emit_autopilot_dreaming.assert_not_called()

    async def test_enter_dreaming_mode_with_specific_modes(
        self, coordinator: DreamingCoordinator, mock_bus: MagicMock
    ) -> None:
        """enter_dreaming_mode can run specific modes."""
        await coordinator.enter_dreaming_mode(modes=["episodic"])

        assert mock_bus.emit_autopilot_dreaming.await_count == 1
        assert mock_bus.emit_autopilot_awake.await_count == 1

    async def test_gather_dreaming_context_loop_scope(
        self, coordinator: DreamingCoordinator
    ) -> None:
        """_gather_dreaming_context returns context for loop scope."""
        context = await coordinator._gather_dreaming_context("loop")

        assert isinstance(context, DreamingContext)
        assert context.scope_id != ""
        assert len(context.goals) > 0

    async def test_gather_dreaming_context_workspace_scope(
        self, coordinator: DreamingCoordinator
    ) -> None:
        """_gather_dreaming_context returns context for workspace scope."""
        context = await coordinator._gather_dreaming_context("workspace")

        assert isinstance(context, DreamingContext)
        assert context.scope_id == "workspace"

    async def test_gather_dreaming_context_topic_scope(
        self, coordinator: DreamingCoordinator
    ) -> None:
        """_gather_dreaming_context returns context for topic scope."""
        context = await coordinator._gather_dreaming_context("topic")

        assert isinstance(context, DreamingContext)
        assert context.scope_id == "topic"

    async def test_run_mode_returns_none_on_llm_failure(
        self, coordinator: DreamingCoordinator
    ) -> None:
        """_run_mode returns None when LLM fails (no mock model)."""
        context = await coordinator._gather_dreaming_context("loop")

        # LLM call will fail since mock_config doesn't have create_chat_model
        result = await coordinator._run_mode("episodic", context)

        assert result is None

    async def test_apply_distillation_result_episodic(
        self, coordinator: DreamingCoordinator
    ) -> None:
        """_apply_distillation_result stores episodic memory from EpisodicDistillationResponse."""
        from soothe.autopilot.dreaming_reasoner import (
            EpisodeDistillationItem,
            EpisodicDistillationResponse,
        )

        response = EpisodicDistillationResponse(
            episodes=[
                EpisodeDistillationItem(
                    goal_id="goal-1",
                    description="Completed task",
                    outcome_summary="Successfully completed",
                    key_steps=["step1", "step2"],
                    lessons_learned="Key takeaway",
                )
            ],
            reasoning="Test reasoning",
        )

        await coordinator._apply_distillation_result("episodic", response)

        coordinator._ce.record_episodic_memory.assert_called_once()

    async def test_apply_distillation_result_handles_none(
        self, coordinator: DreamingCoordinator
    ) -> None:
        """_apply_distillation_result handles None result."""
        await coordinator._apply_distillation_result("episodic", None)

        coordinator._ce.record_episodic_memory.assert_not_called()


class TestDreamingContext:
    """Tests for DreamingContext model."""

    def test_default_values(self) -> None:
        """DreamingContext has empty default values."""
        context = DreamingContext(goals=[], ledger=[], scope_id="test")

        assert context.goals == []
        assert context.ledger == []
        assert context.scope_id == "test"

    def test_accepts_goals(self) -> None:
        """DreamingContext accepts goal list."""
        goal = MagicMock(spec=GoalNode)
        goal.id = "g1"
        context = DreamingContext(goals=[goal], ledger=[], scope_id="test-loop")

        assert len(context.goals) == 1
        assert context.goals[0].id == "g1"


class TestEpisodeSpec:
    """Tests for EpisodeSpec model."""

    def test_default_values(self) -> None:
        """EpisodeSpec has empty default lists."""
        spec = EpisodeSpec(
            goal_id="g1",
            description="Test",
            outcome_summary="Success",
        )

        assert spec.key_steps == []
        assert spec.lessons_learned == ""

    def test_accepts_all_fields(self) -> None:
        """EpisodeSpec accepts all fields."""
        spec = EpisodeSpec(
            goal_id="goal-1",
            description="Completed feature",
            outcome_summary="Feature implemented successfully",
            key_steps=["Plan", "Implement", "Test"],
            lessons_learned="Early planning saves time",
        )

        assert spec.goal_id == "goal-1"
        assert len(spec.key_steps) == 3
        assert spec.lessons_learned != ""
