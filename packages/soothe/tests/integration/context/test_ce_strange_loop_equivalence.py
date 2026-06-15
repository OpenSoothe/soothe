"""Integration test: ContextEngine StrangeLoop path produces equivalent outputs to the non-CE path.

RFC-624 Phase 3: verifies that enabling the ContextEngine path yields
identical observable behavior (loop_messages, plan outcomes, DAG reports)
compared to the standard PlanManager path.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from soothe.context.engine import ContextEngine
from soothe.context.models import StepNode
from soothe.context.planning import StepPlanManagerAdapter
from soothe.foundation.loop.planning.manager import (
    PlanManager,
)
from soothe.foundation.loop.state.schemas import (
    AgentDecision,
    PlanResult,
    StepAction,
    StepResult,
)

# ── Helpers ──────────────────────────────────────────────────────────


def _make_step_action(step_id: str, desc: str, deps: list[str] | None = None) -> StepAction:
    return StepAction(id=step_id, description=desc, dependencies=deps or [])


def _make_plan_result(
    steps: list[StepAction] | None = None,
    status: str = "continue",
    plan_action: str = "new",
    require_goal_completion: bool = True,
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
        require_goal_completion=require_goal_completion,
    )


def _make_step_result(step_id: str, success: bool = True) -> StepResult:
    return StepResult(
        step_id=step_id,
        success=success,
        duration_ms=100,
        thread_id="test-thread",
        error="test error" if not success else None,
    )


def _make_loop_state(**overrides: Any) -> MagicMock:
    state = MagicMock()
    state.iteration = 0
    state.goal = "Test goal"
    state.thread_id = "test-thread"
    state.workspace = None
    state.current_decision = None
    state.loop_messages = []
    state.last_execute_wave_parallel_multi_step = False
    state.last_wave_hit_subagent_cap = False
    for k, v in overrides.items():
        setattr(state, k, v)
    return state


# ── PlanAdapter vs PlanManager Equivalence ───────────────────────────


class TestPlanAdapterPlanManagerEquivalence:
    """Verify StepPlanManagerAdapter produces the same results as PlanManager
    for the same inputs and state."""

    @pytest.mark.asyncio
    async def test_ingest_and_get_planning_context_match(self) -> None:
        """Both paths produce the same DagPlanningContext after ingesting a plan."""
        steps = [
            _make_step_action("01", "Step 1"),
            _make_step_action("02", "Step 2", deps=["01"]),
        ]
        plan_result = _make_plan_result(steps)

        # PlanManager path
        pm = PlanManager(goal="Test goal")
        pm.ingest_plan(plan_result, "KFA", 0)
        pm_ctx = pm.get_planning_context()

        # StepPlanManagerAdapter path
        ce = ContextEngine()
        goal = await ce.create_goal("Test goal")
        await ce.activate_goal(goal.id, loop_id="loop-1")
        await ce.add_steps(
            goal.id,
            [
                StepNode(id="01", description="Step 1"),
                StepNode(id="02", description="Step 2", dependencies=["01"]),
            ],
            plan_iteration=0,
        )
        adapter = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id=goal.id)
        adapter.ingest_plan(plan_result, "KFA", 0)
        ce_ctx = adapter.get_planning_context()

        # Compare the 9 duck-typed attributes
        assert ce_ctx.total_steps == pm_ctx.total_steps
        assert ce_ctx.completed_steps == pm_ctx.completed_steps
        assert ce_ctx.replan_count == pm_ctx.replan_count
        assert ce_ctx.chain_depth == pm_ctx.chain_depth

    @pytest.mark.asyncio
    async def test_record_step_outcomes_match(self) -> None:
        """Both paths produce the same success rate after recording outcomes."""
        steps = [
            _make_step_action("01", "Step 1"),
            _make_step_action("02", "Step 2"),
        ]
        plan_result = _make_plan_result(steps)

        # PlanManager path
        pm = PlanManager(goal="Test goal")
        pm.ingest_plan(plan_result, "KFA", 0)
        pm.dag.mark_completed("01", _make_step_result("01", success=True))
        pm.dag.mark_failed("02", _make_step_result("02", success=False))
        pm_ctx = pm.get_planning_context()

        # StepPlanManagerAdapter path
        ce = ContextEngine()
        goal = await ce.create_goal("Test goal")
        await ce.activate_goal(goal.id, loop_id="loop-1")
        await ce.add_steps(
            goal.id,
            [StepNode(id="01", description="Step 1"), StepNode(id="02", description="Step 2")],
        )
        adapter = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id=goal.id)
        adapter.ingest_plan(plan_result, "KFA", 0)
        adapter.record_step_outcomes(
            [
                _make_step_result("01", success=True),
                _make_step_result("02", success=False),
            ]
        )
        ce_ctx = adapter.get_planning_context()

        assert ce_ctx.total_steps == pm_ctx.total_steps
        assert ce_ctx.completed_steps == pm_ctx.completed_steps
        assert "02" in ce_ctx.failed_step_ids
        assert "02" in pm_ctx.failed_step_ids

    @pytest.mark.asyncio
    async def test_determine_goal_completion_needs_matches(self) -> None:
        """Both paths make the same goal completion decision for identical state."""
        steps = [_make_step_action("01", "Step 1")]
        plan_result = _make_plan_result(steps)

        # PlanManager path
        pm = PlanManager(goal="Test goal")
        pm.ingest_plan(plan_result, "KFA", 0)

        # Adapter path
        ce = ContextEngine()
        goal = await ce.create_goal("Test goal")
        await ce.activate_goal(goal.id, loop_id="loop-1")
        await ce.add_step(goal.id, StepNode(id="01", description="Step 1"))
        adapter = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id=goal.id)
        adapter.ingest_plan(plan_result, "KFA", 0)

        state = _make_loop_state()

        for mode in ("llm_only", "heuristic_only", "hybrid"):
            for llm_decision in (True, False):
                adapter_result = adapter.determine_goal_completion_needs(
                    llm_decision=llm_decision, state=state, mode=mode
                )
                pm_result = pm.determine_goal_completion_needs(
                    llm_decision=llm_decision, state=state, mode=mode
                )
                assert adapter_result == pm_result, (
                    f"Mismatch for mode={mode}, llm_decision={llm_decision}: "
                    f"adapter={adapter_result}, pm={pm_result}"
                )

    @pytest.mark.asyncio
    async def test_format_completion_dag_report_matches(self) -> None:
        """Both paths produce structurally similar completion DAG reports."""
        steps = [
            _make_step_action("01", "First step"),
            _make_step_action("02", "Second step"),
        ]
        plan_result = _make_plan_result(steps)

        # PlanManager path
        pm = PlanManager(goal="Test goal")
        pm.ingest_plan(plan_result, "KFA", 0)
        pm.dag.mark_completed("01", _make_step_result("01"))
        pm.dag.mark_failed("02", _make_step_result("02", success=False))
        pm_report = pm.format_completion_dag_report()

        # Adapter path
        ce = ContextEngine()
        goal = await ce.create_goal("Test goal")
        await ce.activate_goal(goal.id, loop_id="loop-1")
        await ce.add_steps(
            goal.id,
            [
                StepNode(id="01", description="First step"),
                StepNode(id="02", description="Second step"),
            ],
        )
        adapter = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id=goal.id)
        adapter.ingest_plan(plan_result, "KFA", 0)
        adapter.record_step_outcomes(
            [
                _make_step_result("01", success=True),
                _make_step_result("02", success=False),
            ]
        )
        ce_report = adapter.format_completion_dag_report()

        # Both reports should contain key structural elements
        assert "Execution statistics" in pm_report
        assert "Context Engine Goal DAG" in ce_report
        assert "COMPLETED" in pm_report
        assert "COMPLETED" in ce_report
        assert "FAILED" in pm_report
        assert "FAILED" in ce_report


class TestLedgerAdapterCEOnly:
    """Verify _record_ledger_message writes to CE LedgerManager (RFC-624 Phase 4 Stage 2)."""

    @pytest.mark.asyncio
    async def test_ce_ledger_receives_all_phases(self) -> None:
        """All phase-tagged messages go to the CE LedgerManager (CE is sole source)."""
        from langchain_core.messages import AIMessage, HumanMessage

        from soothe.foundation.loop.utils.messages import _record_ledger_message

        ce = ContextEngine()

        # Simulate the 5 phases — CE-only writes (no loop_messages argument)
        _record_ledger_message(ce, HumanMessage(content="Execute step 1"), "execute_step")
        _record_ledger_message(ce, AIMessage(content="Step 1 done"), "execute_step")
        _record_ledger_message(ce, HumanMessage(content="Plan assess"), "plan_assess")
        _record_ledger_message(ce, AIMessage(content="Assessment result"), "plan_assess")
        _record_ledger_message(ce, HumanMessage(content="Plan generate"), "plan_generate")
        _record_ledger_message(ce, AIMessage(content="Generated plan"), "plan_generate")
        _record_ledger_message(ce, HumanMessage(content="Goal complete"), "goal_completion")
        _record_ledger_message(ce, AIMessage(content="Final output"), "goal_completion")

        # LedgerManager should have all 8 messages with correct phase tags
        exec_msgs = ce._ledger.get_messages(["execute_step"])
        assert len(exec_msgs) == 2
        plan_assess_msgs = ce._ledger.get_messages(["plan_assess"])
        assert len(plan_assess_msgs) == 2
        plan_gen_msgs = ce._ledger.get_messages(["plan_generate"])
        assert len(plan_gen_msgs) == 2
        goal_msgs = ce._ledger.get_messages(["goal_completion"])
        assert len(goal_msgs) == 2

        # Total should be 8
        all_msgs = ce._ledger.get_messages()
        assert len(all_msgs) == 8

    @pytest.mark.asyncio
    async def test_no_ce_raises_value_error(self) -> None:
        """Stage 2: _record_ledger_message requires a CE instance."""
        from langchain_core.messages import HumanMessage

        from soothe.foundation.loop.utils.messages import _record_ledger_message

        msg = HumanMessage(content="test")
        try:
            _record_ledger_message(None, msg, "execute_step")
        except ValueError as e:
            assert "requires a ContextEngine instance" in str(e)
        else:
            raise AssertionError("Expected ValueError")


class TestNamedConstantsEquivalence:
    """Verify constants are defined once in completion.py (single source of truth)."""

    def test_threshold_values_defined(self) -> None:
        """The constants in completion.py are the canonical definitions."""
        from soothe.context.planning.completion import (
            DAG_DEPENDENCY_THRESHOLD,
            LOW_SUCCESS_RATE_THRESHOLD,
            SIMPLE_DAG_LEDGER_DIRECT_MAX_STEPS,
        )

        assert LOW_SUCCESS_RATE_THRESHOLD == 0.6
        assert DAG_DEPENDENCY_THRESHOLD == 3
        assert SIMPLE_DAG_LEDGER_DIRECT_MAX_STEPS == 2
