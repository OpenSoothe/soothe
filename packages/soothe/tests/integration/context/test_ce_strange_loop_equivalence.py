"""Integration tests for ContextEngine step-plan adapter (RFC-624, IG-537)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from soothe.foundation.context.engine import ContextEngine
from soothe.foundation.context.planning import StepPlanManagerAdapter
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


class TestStepPlanManagerAdapterIntegration:
    """Verify StepPlanManagerAdapter planning context and reports."""

    @pytest.mark.asyncio
    async def test_ingest_and_get_planning_context(self) -> None:
        steps = [
            _make_step_action("01", "Step 1"),
            _make_step_action("02", "Step 2", deps=["01"]),
        ]
        plan_result = _make_plan_result(steps)

        ce = ContextEngine()
        goal = await ce.create_goal("Test goal")
        await ce.activate_goal(goal.id, loop_id="loop-1")
        adapter = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id=goal.id)
        adapter.ingest_plan(plan_result, "KFA", 0)
        ctx = adapter.get_planning_context()

        assert ctx.total_steps == 2
        assert ctx.replan_count == 0
        assert ctx.chain_depth >= 1

    @pytest.mark.asyncio
    async def test_record_step_outcomes_updates_context(self) -> None:
        steps = [
            _make_step_action("01", "Step 1"),
            _make_step_action("02", "Step 2"),
        ]
        plan_result = _make_plan_result(steps)

        ce = ContextEngine()
        goal = await ce.create_goal("Test goal")
        await ce.activate_goal(goal.id, loop_id="loop-1")
        adapter = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id=goal.id)
        adapter.ingest_plan(plan_result, "KFA", 0)
        adapter.record_step_outcomes(
            [
                _make_step_result("01", success=True),
                _make_step_result("02", success=False),
            ]
        )
        ctx = adapter.get_planning_context()

        assert ctx.completed_steps == 1
        assert "02" in ctx.failed_step_ids

    @pytest.mark.asyncio
    async def test_determine_goal_completion_needs(self) -> None:
        steps = [_make_step_action("01", "Step 1")]
        plan_result = _make_plan_result(steps)

        ce = ContextEngine()
        goal = await ce.create_goal("Test goal")
        adapter = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id=goal.id)
        adapter.ingest_plan(plan_result, "KFA", 0)

        state = _make_loop_state()
        assert adapter.determine_goal_completion_needs(True, state, "llm_only") is True
        assert adapter.determine_goal_completion_needs(False, state, "llm_only") is False

    @pytest.mark.asyncio
    async def test_format_completion_dag_report(self) -> None:
        steps = [
            _make_step_action("01", "First step"),
            _make_step_action("02", "Second step"),
        ]
        plan_result = _make_plan_result(steps)

        ce = ContextEngine()
        goal = await ce.create_goal("Test goal")
        adapter = StepPlanManagerAdapter(subengine=ce.planning.step, goal_id=goal.id)
        adapter.ingest_plan(plan_result, "KFA", 0)
        adapter.record_step_outcomes(
            [
                _make_step_result("01", success=True),
                _make_step_result("02", success=False),
            ]
        )
        report = adapter.format_completion_dag_report()

        assert "Context Engine Goal DAG" in report
        assert "COMPLETED" in report
        assert "FAILED" in report


class TestLedgerAdapterCEOnly:
    """Verify _record_ledger_message writes to CE LedgerManager (RFC-624 Phase 4 Stage 2)."""

    @pytest.mark.asyncio
    async def test_ce_ledger_receives_all_phases(self) -> None:
        """All phase-tagged messages go to the CE LedgerManager (CE is sole source)."""
        from langchain_core.messages import AIMessage, HumanMessage

        from soothe.foundation.loop.utils.messages import _record_ledger_message

        ce = ContextEngine()

        _record_ledger_message(ce, HumanMessage(content="Execute step 1"), "execute_step")
        _record_ledger_message(ce, AIMessage(content="Step 1 done"), "execute_step")
        _record_ledger_message(ce, HumanMessage(content="Plan assess"), "plan_assess")
        _record_ledger_message(ce, AIMessage(content="Assessment result"), "plan_assess")
        _record_ledger_message(ce, HumanMessage(content="Plan generate"), "plan_generate")
        _record_ledger_message(ce, AIMessage(content="Generated plan"), "plan_generate")
        _record_ledger_message(ce, HumanMessage(content="Goal complete"), "goal_completion")
        _record_ledger_message(ce, AIMessage(content="Final output"), "goal_completion")

        exec_msgs = ce._ledger.get_messages(["execute_step"])
        assert len(exec_msgs) == 2
        plan_assess_msgs = ce._ledger.get_messages(["plan_assess"])
        assert len(plan_assess_msgs) == 2
        plan_gen_msgs = ce._ledger.get_messages(["plan_generate"])
        assert len(plan_gen_msgs) == 2
        goal_msgs = ce._ledger.get_messages(["goal_completion"])
        assert len(goal_msgs) == 2
        assert len(ce._ledger.get_messages()) == 8

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
        from soothe.foundation.context.planning.completion import (
            DAG_DEPENDENCY_THRESHOLD,
            LOW_SUCCESS_RATE_THRESHOLD,
            SIMPLE_DAG_LEDGER_DIRECT_MAX_STEPS,
        )

        assert LOW_SUCCESS_RATE_THRESHOLD == 0.6
        assert DAG_DEPENDENCY_THRESHOLD == 3
        assert SIMPLE_DAG_LEDGER_DIRECT_MAX_STEPS == 2
