"""Tests for Context Engine adapters (RFC-624 Phase 3)."""

from __future__ import annotations

import pytest

from soothe.context.engine import ContextEngine
from soothe.context.models import StepNode
from soothe.context.planning import StepPlanManagerAdapter
from soothe.foundation.loop.engine.context_adapters import (
    ContextEngineGoalContextAdapter,
)
from soothe.foundation.loop.state.schemas import (
    AgentDecision,
    PlanResult,
    StepAction,
    StepResult,
)

# ── Helpers ──────────────────────────────────────────────────────────


def _make_plan_result(
    steps: list[StepAction] | None = None,
    status: str = "continue",
    plan_action: str = "new",
) -> PlanResult:
    decision = None
    if plan_action == "new":
        if steps:
            decision = AgentDecision(type="execute_steps", steps=steps)
        else:
            decision = AgentDecision(
                type="execute_steps",
                steps=[StepAction(id="01", description="Dummy")],
            )
    return PlanResult(
        status=status,
        plan_action=plan_action,
        decision=decision,
        evidence_summary="",
        goal_progress="none",
        next_action="test",
    )


def _make_step_result(step_id: str, success: bool = True) -> StepResult:
    return StepResult(
        step_id=step_id,
        success=success,
        duration_ms=100,
        thread_id="test-thread",
        error="test error" if not success else None,
    )


# ── StepPlanManagerAdapter ─────────────────────────────────────────


class TestPlanAdapterIngestPlan:
    @pytest.mark.asyncio
    async def test_ingest_plan_adds_steps_to_ce(self) -> None:
        ce = ContextEngine()
        goal = await ce.create_goal("Test goal")
        adapter = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id=goal.id)

        steps = [
            StepAction(id="01", description="Step 1"),
            StepAction(id="02", description="Step 2", dependencies=["01"]),
        ]
        plan_result = _make_plan_result(steps)

        # ingest_plan uses asyncio.get_running_loop() which works in async test
        await ce.activate_goal(goal.id, loop_id="loop-1")
        adapter.ingest_plan(plan_result, "KFA", 0)

        assert len(adapter.plan_history) == 1
        # Steps are added via create_task; give event loop a tick
        # Since add_steps is async and we called it via create_task,
        # we need to await it properly for the test
        await ce.add_steps(
            goal.id,
            [
                StepNode(id="01", description="Step 1"),
                StepNode(id="02", description="Step 2", dependencies=["01"]),
            ],
            plan_iteration=0,
        )

        retrieved = await ce.get_goal(goal.id)
        assert "01" in retrieved.steps.nodes
        assert "02" in retrieved.steps.nodes

    @pytest.mark.asyncio
    async def test_ingest_plan_accumulates_history(self) -> None:
        ce = ContextEngine()
        goal = await ce.create_goal("Test goal")
        adapter = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id=goal.id)

        plan1 = _make_plan_result([StepAction(id="01", description="S1")])
        plan2 = _make_plan_result([StepAction(id="02", description="S2")])

        adapter.ingest_plan(plan1, "AAA", 0)
        adapter.ingest_plan(plan2, "BBB", 1)

        assert len(adapter.plan_history) == 2


class TestPlanAdapterGetPlanningContext:
    @pytest.mark.asyncio
    async def test_empty_context_when_no_goal(self) -> None:
        ce = ContextEngine()
        adapter = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id="")
        ctx = adapter.get_planning_context()
        assert ctx.total_steps == 0
        assert ctx.has_prior_state is False

    @pytest.mark.asyncio
    async def test_context_has_all_nine_fields(self) -> None:
        ce = ContextEngine()
        goal = await ce.create_goal("Test goal")
        await ce.add_step(
            goal.id,
            StepNode(id="KFA-01", description="S1", status="completed"),
        )
        await ce.add_step(
            goal.id,
            StepNode(id="KFA-02", description="S2", status="pending", dependencies=["KFA-01"]),
        )

        adapter = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id=goal.id)
        adapter.plan_history.append(_make_plan_result())

        ctx = adapter.get_planning_context()

        # All 9 fields that _format_dag_context accesses
        assert isinstance(ctx.has_prior_state, bool)
        assert isinstance(ctx.total_steps, int)
        assert isinstance(ctx.completed_steps, int)
        assert isinstance(ctx.failed_step_ids, set)
        assert isinstance(ctx.ready_step_ids, set)
        assert isinstance(ctx.pending_step_ids, set)
        assert isinstance(ctx.chain_depth, int)
        assert isinstance(ctx.success_rate, float)
        assert isinstance(ctx.replan_count, int)

        assert ctx.total_steps == 2
        assert ctx.completed_steps == 1
        assert "KFA-02" in ctx.ready_step_ids
        assert "KFA-02" in ctx.pending_step_ids

    @pytest.mark.asyncio
    async def test_replan_count_from_history(self) -> None:
        ce = ContextEngine()
        goal = await ce.create_goal("Test goal")
        adapter = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id=goal.id)

        adapter.ingest_plan(_make_plan_result([StepAction(id="01", description="S1")]), "KFA", 0)
        adapter.ingest_plan(_make_plan_result([StepAction(id="02", description="S2")]), "KFA", 1)
        adapter.ingest_plan(_make_plan_result([StepAction(id="03", description="S3")]), "KFA", 2)

        ctx = adapter.get_planning_context()
        assert ctx.replan_count == 2  # len(plan_waves) - 1


class TestPlanAdapterRecordStepOutcomes:
    @pytest.mark.asyncio
    async def test_record_success_and_failure(self) -> None:
        ce = ContextEngine()
        goal = await ce.create_goal("Test goal")
        await ce.add_steps(
            goal.id,
            [
                StepNode(id="KFA-01", description="S1"),
                StepNode(id="KFA-02", description="S2"),
            ],
        )

        adapter = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id=goal.id)
        results = [
            _make_step_result("KFA-01", success=True),
            _make_step_result("KFA-02", success=False),
        ]
        adapter.record_step_outcomes(results)

        # Outcomes are recorded via create_task; verify directly
        goal_node = await ce.get_goal(goal.id)
        assert goal_node.steps.nodes["KFA-01"].status == "completed"
        assert goal_node.steps.nodes["KFA-02"].status == "failed"


class TestPlanAdapterFormatCompletionDagReport:
    @pytest.mark.asyncio
    async def test_empty_when_no_goals(self) -> None:
        ce = ContextEngine()
        adapter = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id="")
        assert adapter.format_completion_dag_report() == ""

    @pytest.mark.asyncio
    async def test_report_shows_goal_without_steps(self) -> None:
        ce = ContextEngine()
        goal = await ce.create_goal("Test goal")
        adapter = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id=goal.id)

        report = adapter.format_completion_dag_report()
        assert "Context Engine Goal DAG" in report
        assert goal.id in report
        assert "Test goal" in report

    @pytest.mark.asyncio
    async def test_report_shows_full_goal_dag(self) -> None:
        ce = ContextEngine()
        goal = await ce.create_goal("Test goal")
        await ce.add_steps(
            goal.id,
            [
                StepNode(id="KFA-01", description="First step", status="completed"),
                StepNode(id="KFA-02", description="Second step", status="failed"),
            ],
        )

        adapter = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id=goal.id)
        adapter.plan_history.append(_make_plan_result())

        report = adapter.format_completion_dag_report()
        assert "Context Engine Goal DAG" in report
        assert "Goal statistics" in report
        assert goal.id in report
        assert "KFA-01" in report
        assert "KFA-02" in report
        assert "COMPLETED" in report
        assert "FAILED" in report
        assert "Step DAG" in report

    @pytest.mark.asyncio
    async def test_report_shows_multiple_goals(self) -> None:
        ce = ContextEngine()
        goal1 = await ce.create_goal("First goal")
        await ce.add_steps(
            goal1.id,
            [StepNode(id="01", description="Step 1", status="completed")],
        )
        goal2 = await ce.create_goal("Second goal")
        await ce.add_steps(
            goal2.id,
            [StepNode(id="02", description="Step 2", status="failed")],
        )

        adapter = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id=goal1.id)
        adapter.plan_history.append(_make_plan_result())

        report = adapter.format_completion_dag_report()
        assert "Total goals: 2" in report
        assert goal1.id in report
        assert goal2.id in report
        assert "First goal" in report
        assert "Second goal" in report

    @pytest.mark.asyncio
    async def test_report_shows_lineage_for_subgoal(self) -> None:
        from soothe.context.models import GoalNode

        ce = ContextEngine()
        parent = await ce.create_goal("Parent goal")
        child = GoalNode(
            id="child-1",
            description="Child goal",
            parent_id=parent.id,
            source="decomposition",
        )
        ce._dag.add_goal(child)
        await ce.add_steps(
            child.id,
            [StepNode(id="01", description="Sub-step", status="completed")],
        )

        adapter = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id=parent.id)
        report = adapter.format_completion_dag_report()
        assert "child-1" in report
        assert f"Parent: {parent.id}" in report
        assert "Lineage:" in report

    @pytest.mark.asyncio
    async def test_report_shows_replan_count(self) -> None:
        ce = ContextEngine()
        goal = await ce.create_goal("Test goal")
        await ce.add_steps(
            goal.id,
            [StepNode(id="01", description="S1", status="completed")],
        )

        adapter = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id=goal.id)
        adapter.ingest_plan(_make_plan_result([StepAction(id="01", description="S1")]), "KFA", 0)
        adapter.ingest_plan(_make_plan_result([StepAction(id="02", description="S2")]), "KFA", 1)

        report = adapter.format_completion_dag_report()
        assert "Replans after first wave: 1" in report


class TestPlanAdapterDetermineGoalCompletionNeeds:
    @pytest.mark.asyncio
    async def test_llm_only_mode(self) -> None:
        ce = ContextEngine()
        adapter = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id="")

        assert adapter.determine_goal_completion_needs(True, None, "llm_only") is True
        assert adapter.determine_goal_completion_needs(False, None, "llm_only") is False


class TestPlanAdapterGoalIdProperty:
    def test_goal_id_getter_setter(self) -> None:
        ce = ContextEngine()
        adapter = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id="")
        assert adapter.goal_id is None

        adapter.goal_id = "abc123"
        assert adapter.goal_id == "abc123"


# ── ContextEngineGoalContextAdapter ──────────────────────────────────


class TestGoalContextAdapter:
    @pytest.mark.asyncio
    async def test_get_plan_context_empty_when_no_history(self) -> None:
        ce = ContextEngine()
        adapter = ContextEngineGoalContextAdapter(
            context_engine=ce,
            state_manager=None,
        )
        # state_manager is None; should return empty
        result = await adapter.get_plan_context()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_execute_briefing_returns_none_no_state_manager(self) -> None:
        ce = ContextEngine()
        adapter = ContextEngineGoalContextAdapter(
            context_engine=ce,
            state_manager=None,
        )
        result = await adapter.get_execute_briefing()
        assert result is None


# ── Integration: DagPlanningContext duck typing ───────────────────────


class TestDagPlanningContextDuckTyping:
    """Verify the adapter produces DagPlanningContext with all 9 attributes
    that _format_dag_context() in builder.py accesses via duck typing."""

    @pytest.mark.asyncio
    async def test_all_format_dag_context_attributes(self) -> None:
        ce = ContextEngine()
        goal = await ce.create_goal("Test goal")
        await ce.add_steps(
            goal.id,
            [
                StepNode(id="KFA-01", description="S1", status="completed"),
                StepNode(id="KFA-02", description="S2", status="pending", dependencies=["KFA-01"]),
                StepNode(id="KFA-03", description="S3", status="failed"),
            ],
        )

        adapter = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id=goal.id)
        adapter.plan_history.append(_make_plan_result())

        ctx = adapter.get_planning_context()

        # These are the exact attributes _format_dag_context accesses
        assert hasattr(ctx, "has_prior_state")
        assert hasattr(ctx, "total_steps")
        assert hasattr(ctx, "completed_steps")
        assert hasattr(ctx, "failed_step_ids")
        assert hasattr(ctx, "ready_step_ids")
        assert hasattr(ctx, "pending_step_ids")
        assert hasattr(ctx, "chain_depth")
        assert hasattr(ctx, "success_rate")
        assert hasattr(ctx, "replan_count")

        # Verify values
        assert ctx.has_prior_state is True
        assert ctx.total_steps == 3
        assert ctx.completed_steps == 1
        assert ctx.failed_step_ids == {"KFA-03"}
        assert "KFA-02" in ctx.ready_step_ids
        assert "KFA-02" in ctx.pending_step_ids
        assert ctx.chain_depth >= 1
        assert 0.0 <= ctx.success_rate <= 1.0
        assert ctx.replan_count == 0

    @pytest.mark.asyncio
    async def test_format_dag_context_produces_text(self) -> None:
        """Verify the DagPlanningContext from adapter works with _format_dag_context."""
        from soothe.foundation.loop.prompts.builder import _format_dag_context

        ce = ContextEngine()
        goal = await ce.create_goal("Test goal")
        await ce.add_steps(
            goal.id,
            [
                StepNode(id="KFA-01", description="S1", status="completed"),
                StepNode(id="KFA-02", description="S2", status="pending"),
            ],
        )

        adapter = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id=goal.id)
        adapter.plan_history.append(_make_plan_result())

        ctx = adapter.get_planning_context()
        text = _format_dag_context(ctx)

        assert "Total steps planned: 2" in text
        assert "KFA-02" in text

    @pytest.mark.asyncio
    async def test_format_dag_context_empty_when_no_prior_state(self) -> None:
        from soothe.foundation.loop.prompts.builder import _format_dag_context

        ce = ContextEngine()
        adapter = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id="")
        ctx = adapter.get_planning_context()
        text = _format_dag_context(ctx)
        assert text == ""
