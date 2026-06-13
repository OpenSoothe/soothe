"""Tests for IG-483: Adapter Hardening + Projection Wiring."""

from __future__ import annotations

import pytest

from soothe.context.engine import ContextEngine
from soothe.context.ledger import LedgerManager
from soothe.context.models import GoalNode, StepExecution, StepNode
from soothe.context.planning import StepPlanManagerAdapter
from soothe.context.projection import ContextBundle
from soothe.foundation.loop.engine.context_adapters import (
    ContextEngineGoalContextAdapter,
    _format_execute_briefing_from_ce_goals,
)
from soothe.foundation.loop.planning.manager import DagPlanningContext

# ── StepPlanManagerAdapter public API ────────────────────────────────


class TestPlanAdapterPublicAPI:
    def test_ingest_plan_uses_step_planning_subengine(self) -> None:
        ce = ContextEngine()
        goal = GoalNode(description="Test goal")
        ce._dag.add_goal(goal)

        adapter = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id=goal.id)
        from soothe.foundation.loop.state.schemas import AgentDecision, StepAction

        decision = AgentDecision(
            type="execute_steps",
            execution_mode="parallel",
            reasoning="test",
            steps=[
                StepAction(id="S01", description="Step 1"),
                StepAction(id="S02", description="Step 2", dependencies=["S01"]),
            ],
        )
        from soothe.foundation.loop.state.schemas import PlanResult

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
    async def test_get_plan_context_reads_from_ce_dag(self) -> None:
        ce = ContextEngine()
        g1 = GoalNode(description="Completed goal", status="completed")
        g1.steps.add_step(StepNode(id="S1", description="Step 1"))
        g1.steps.mark_completed("S1", StepExecution())
        ce._dag.add_goal(g1)

        adapter = ContextEngineGoalContextAdapter(ce, state_manager=None)
        result = await adapter.get_plan_context()

        assert len(result) == 1
        assert "Completed goal" in result[0]
        assert "completed" in result[0]

    @pytest.mark.asyncio
    async def test_get_plan_context_excludes_non_completed(self) -> None:
        ce = ContextEngine()
        GoalNode(description="Active goal", status="active")
        g1 = GoalNode(description="Active goal", status="active")
        g2 = GoalNode(description="Completed goal", status="completed")
        ce._dag.add_goal(g1)
        ce._dag.add_goal(g2)

        adapter = ContextEngineGoalContextAdapter(ce, state_manager=None)
        result = await adapter.get_plan_context()

        assert len(result) == 1
        assert "Completed goal" in result[0]

    @pytest.mark.asyncio
    async def test_get_plan_context_respects_limit(self) -> None:
        ce = ContextEngine()
        for i in range(5):
            g = GoalNode(description=f"Goal {i}", status="completed")
            ce._dag.add_goal(g)

        adapter = ContextEngineGoalContextAdapter(ce, state_manager=None)
        result = await adapter.get_plan_context(limit=2)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_get_plan_context_disabled_returns_empty(self) -> None:
        ce = ContextEngine()
        g = GoalNode(description="Completed", status="completed")
        ce._dag.add_goal(g)

        class DisabledConfig:
            enabled = False

        adapter = ContextEngineGoalContextAdapter(ce, state_manager=None, config=DisabledConfig())
        result = await adapter.get_plan_context()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_plan_context_no_completed_goals(self) -> None:
        ce = ContextEngine()
        g = GoalNode(description="Active", status="active")
        ce._dag.add_goal(g)

        adapter = ContextEngineGoalContextAdapter(ce, state_manager=None)
        result = await adapter.get_plan_context()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_plan_context_step_summary_rendered(self) -> None:
        ce = ContextEngine()
        g = GoalNode(description="Goal with steps", status="completed")
        g.steps.add_step(StepNode(id="S1", description="Do thing 1"))
        g.steps.add_step(StepNode(id="S2", description="Do thing 2"))
        g.steps.mark_completed("S1", StepExecution())
        g.steps.mark_failed("S2", StepExecution(error="boom"))
        ce._dag.add_goal(g)

        adapter = ContextEngineGoalContextAdapter(ce, state_manager=None)
        result = await adapter.get_plan_context()

        assert len(result) == 1
        # Completed step should be in the output
        assert "S1" in result[0]
        assert "Do thing 1" in result[0]

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


# ── PromptBuilder ContextBundle injection ──────────────────────────────


class TestPromptBuilderContextBundle:
    def test_build_plan_messages_without_bundle(self) -> None:
        """When context_bundle is None, behavior is unchanged."""
        from soothe.foundation.loop.prompts.builder import PromptBuilder
        from soothe.foundation.loop.state.schemas import LoopState
        from soothe.protocols.planner import PlanContext

        builder = PromptBuilder()
        state = LoopState(goal="Test goal", thread_id="t1")
        context = PlanContext()

        messages = builder.build_plan_messages("Test goal", state, context)
        assert len(messages) >= 1
        # System message should not contain ContextBundle-specific tags
        system_msg = messages[0]
        assert "<AGENT_INSTRUCTIONS>" not in str(system_msg.content)
        assert "<MEMORY_INSTRUCTIONS>" not in str(system_msg.content)

    def test_build_plan_messages_with_bundle_supplements_system(self) -> None:
        """ContextBundle injects supplementary instructions into system message."""
        from soothe.foundation.loop.prompts.builder import PromptBuilder
        from soothe.foundation.loop.state.schemas import LoopState
        from soothe.protocols.planner import PlanContext

        builder = PromptBuilder()
        state = LoopState(goal="Test goal", thread_id="t1")
        context = PlanContext(workspace="/tmp/test")

        bundle = ContextBundle(
            project_instructions="Custom project instructions",
            agent_instructions="Agent-specific instructions",
            memory_instructions="Memory-based instructions",
        )

        messages = builder.build_plan_messages(
            "Test goal",
            state,
            context,
            plan_phase="generate",
            context_bundle=bundle,
        )
        system_content = str(messages[0].content)
        assert "Custom project instructions" in system_content
        assert "<AGENT_INSTRUCTIONS>" in system_content
        assert "Agent-specific instructions" in system_content
        assert "<MEMORY_INSTRUCTIONS>" in system_content
        assert "Memory-based instructions" in system_content

    def test_build_plan_messages_with_bundle_supplements_human(self) -> None:
        """ContextBundle injects goal lineage/progress into human message."""
        from soothe.foundation.loop.prompts.builder import PromptBuilder
        from soothe.foundation.loop.state.schemas import LoopState
        from soothe.protocols.planner import PlanContext

        builder = PromptBuilder()
        state = LoopState(goal="Test goal", thread_id="t1")
        context = PlanContext()

        bundle = ContextBundle(
            goal_lineage="Root → Child",
            goal_progress="2/5 completed",
            step_lineage="Reasoning trace here",
        )

        messages = builder.build_plan_messages(
            "Test goal",
            state,
            context,
            context_bundle=bundle,
        )
        # Find the human message (LoopHumanMessage, not SystemMessage)
        from soothe.foundation.loop.utils.messages import LoopHumanMessage

        human_msgs = [m for m in messages if isinstance(m, LoopHumanMessage)]
        assert len(human_msgs) >= 1
        human_content = str(human_msgs[0].content)
        assert "GOAL LINEAGE:" in human_content
        assert "Root → Child" in human_content
        assert "GOAL PROGRESS:" in human_content
        assert "2/5 completed" in human_content
        assert "STEP LINEAGE:" in human_content
        assert "Reasoning trace here" in human_content

    def test_build_plan_messages_empty_bundle_fields_omitted(self) -> None:
        """Empty ContextBundle fields are not injected."""
        from soothe.foundation.loop.prompts.builder import PromptBuilder
        from soothe.foundation.loop.state.schemas import LoopState
        from soothe.protocols.planner import PlanContext

        builder = PromptBuilder()
        state = LoopState(goal="Test goal", thread_id="t1")
        context = PlanContext()

        bundle = ContextBundle()  # All defaults are empty

        messages = builder.build_plan_messages(
            "Test goal",
            state,
            context,
            context_bundle=bundle,
        )
        system_content = str(messages[0].content)
        assert "<AGENT_INSTRUCTIONS>" not in system_content
        assert "<MEMORY_INSTRUCTIONS>" not in system_content

        from soothe.foundation.loop.utils.messages import LoopHumanMessage

        human_msgs = [m for m in messages if isinstance(m, LoopHumanMessage)]
        if human_msgs:
            human_content = str(human_msgs[0].content)
            assert "GOAL LINEAGE:" not in human_content
            assert "GOAL PROGRESS:" not in human_content
            assert "STEP LINEAGE:" not in human_content


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
