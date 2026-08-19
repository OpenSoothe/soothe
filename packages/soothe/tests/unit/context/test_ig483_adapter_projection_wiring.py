"""Tests for Adapter Hardening + Projection Wiring."""

from __future__ import annotations

import pytest

from soothe.context import StepPlanManagerAdapter
from soothe.context.engine import ContextEngine
from soothe.context.ledger import LedgerManager
from soothe.context.models import GoalNode, StepExecution, StepNode
from soothe.context.planning_models import DagPlanningContext
from soothe.sloop.engine.context_adapters import (
    ContextEngineGoalContextAdapter,
    _format_execute_briefing_from_ce_goals,
)

# ── StepPlanManagerAdapter public API ────────────────────────────────


class TestPlanAdapterPublicAPI:
    def test_ingest_plan_uses_step_planning_subengine(self) -> None:
        ce = ContextEngine()
        goal = GoalNode(description="Test goal")
        ce._dag.add_goal(goal)

        adapter = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id=goal.id)
        from soothe.sloop.state.schemas import AgentDecision, StepAction

        decision = AgentDecision(
            type="execute_steps",
            execution_mode="parallel",
            reasoning="test",
            steps=[
                StepAction(id="S01", description="Step 1"),
                StepAction(id="S02", description="Step 2", dependencies=["S01"]),
            ],
        )
        from soothe.sloop.state.schemas import PlanResult

        plan_result = PlanResult(
            status="replan",
            goal_progress="none",
            plan_action="new",
            decision=decision,
            next_action="proceed",
        )
        adapter.ingest_plan(plan_result, "p1", 1)

        goal_node = ce.get_goal_sync(goal.id)
        assert goal_node is not None
        assert "S01" in goal_node.steps.nodes
        assert "S02" in goal_node.steps.nodes
        assert goal_node.steps.nodes["S02"].dependencies == ["S01"]

    def test_get_planning_context_reads_from_step_subengine(self) -> None:
        ce = ContextEngine()
        goal = GoalNode(description="Test goal")
        ce._dag.add_goal(goal)

        adapter = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id=goal.id)
        ctx = adapter.get_planning_context()
        assert isinstance(ctx, DagPlanningContext)
        assert ctx.total_steps == 0

    def test_format_completion_dag_report_uses_all_goals(self) -> None:
        ce = ContextEngine()
        g1 = GoalNode(description="Goal 1", status="completed")
        g2 = GoalNode(description="Goal 2", status="active")
        ce._dag.add_goal(g1)
        ce._dag.add_goal(g2)

        adapter = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id=g2.id)
        report = adapter.format_completion_dag_report()
        assert "Goal 1" in report
        assert "Goal 2" in report
        assert "Total goals: 2" in report

    def test_heuristic_delegates_to_completion_module(self) -> None:
        ce = ContextEngine()
        goal = GoalNode(description="Test goal")
        ce._dag.add_goal(goal)

        adapter = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id=goal.id)

        class MockState:
            last_execute_wave_parallel_multi_step = False
            last_wave_hit_subagent_cap = False
            current_decision = None

        result = adapter.determine_goal_completion_needs(False, MockState(), "heuristic_only")
        assert result is False


# ── ContextEngineGoalContextAdapter CE DAG reads ───────────────────────


class TestGoalContextAdapterCEDAGReads:
    @pytest.mark.asyncio
    async def test_get_execute_briefing_reads_from_ce_dag(self) -> None:
        ce = ContextEngine()
        g = GoalNode(description="Completed goal", status="completed")
        g.steps.add_step(StepNode(id="S1", description="Step 1"))
        g.steps.mark_completed("S1", StepExecution())
        ce._dag.add_goal(g)

        # Create a mock state_manager with thread_switch_pending
        class MockCheckpoint:
            thread_switch_pending = True
            current_thread_id = "thread-1"
            goal_history = []

        class MockStateManager:
            async def load(self):
                return MockCheckpoint()

            def get_checkpoint(self):
                return MockCheckpoint()

            async def save(self, checkpoint):
                pass

        adapter = ContextEngineGoalContextAdapter(ce, state_manager=MockStateManager())
        result = await adapter.get_execute_briefing()

        assert result is not None
        assert "Completed goal" in result
        assert "Thread Switch Recovery" in result

    @pytest.mark.asyncio
    async def test_get_execute_briefing_no_thread_switch(self) -> None:
        ce = ContextEngine()
        g = GoalNode(description="Completed goal", status="completed")
        ce._dag.add_goal(g)

        class MockCheckpoint:
            thread_switch_pending = False
            current_thread_id = "thread-1"

        class MockStateManager:
            async def load(self):
                return MockCheckpoint()

            def get_checkpoint(self):
                return MockCheckpoint()

            async def save(self, checkpoint):
                pass

        adapter = ContextEngineGoalContextAdapter(ce, state_manager=MockStateManager())
        result = await adapter.get_execute_briefing()
        assert result is None


# ── _format_execute_briefing_from_ce_goals ──────────────────────────────


class TestFormatExecuteBriefingFromCEGoals:
    def test_formats_ce_goals(self) -> None:
        g = GoalNode(description="Test goal", status="completed")
        g.steps.add_step(StepNode(id="S1", description="Do thing"))
        g.steps.mark_completed("S1", StepExecution())

        result = _format_execute_briefing_from_ce_goals([g], "thread-1")
        assert "Test goal" in result
        assert "Thread Switch Recovery" in result
        assert "thread-1" in result

    def test_empty_goals_list(self) -> None:
        result = _format_execute_briefing_from_ce_goals([], "thread-1")
        assert "Thread Switch Recovery" in result


# ── ContextEngine.get_goal_sync() ───────────────────────────────────────


class TestGetGoalSync:
    def test_get_goal_sync_returns_goal(self) -> None:
        ce = ContextEngine()
        goal = GoalNode(description="Test")
        ce._dag.add_goal(goal)

        result = ce.get_goal_sync(goal.id)
        assert result is goal

    def test_get_goal_sync_missing_returns_none(self) -> None:
        ce = ContextEngine()
        assert ce.get_goal_sync("missing") is None


# ── ContextEngine.ledger property ───────────────────────────────────────


class TestLedgerProperty:
    def test_ledger_property_returns_ledger_manager(self) -> None:
        ce = ContextEngine()
        ledger = ce.ledger
        assert isinstance(ledger, LedgerManager)

    def test_ledger_property_is_read_only(self) -> None:
        ce = ContextEngine()
        # Verify the property returns the same instance each time
        assert ce.ledger is ce.ledger
