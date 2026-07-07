"""Tests for planner ledger projection modes (IG-538)."""

from __future__ import annotations

from soothe.foundation.sloop.prompts import PromptBuilder
from soothe.foundation.sloop.prompts.plan_ledger_projection import (
    project_planner_ledger,
    resolve_planner_projection_mode,
)
from soothe.foundation.sloop.state.schemas import LoopState, StatusAssessment, StepResult
from soothe.foundation.sloop.utils.messages import LoopAIMessage, LoopHumanMessage
from soothe.protocols.planner import PlanContext


def test_resolve_planner_projection_mode_new_goal() -> None:
    state = LoopState(goal="g", thread_id="t", iteration=0)
    assert resolve_planner_projection_mode(state) == "new_goal"


def test_resolve_planner_projection_mode_mid_goal_on_step_results() -> None:
    state = LoopState(goal="g", thread_id="t", iteration=0)
    state.step_results.append(StepResult(step_id="01", success=True, duration_ms=1, thread_id="t"))
    assert resolve_planner_projection_mode(state) == "mid_goal"


def test_project_planner_ledger_mid_goal_isolates_prior_execute() -> None:
    ledger = [
        LoopHumanMessage(content="exec h1", phase="execute_step", thread_id="t"),
        LoopAIMessage(content="exec a1", phase="execute_step", thread_id="t"),
        LoopHumanMessage(content="gc h1", phase="goal_completion", thread_id="t"),
        LoopAIMessage(content="gc a1", phase="goal_completion", thread_id="t"),
        LoopHumanMessage(content="exec h2", phase="execute_step", thread_id="t"),
        LoopAIMessage(content="exec a2", phase="execute_step", thread_id="t"),
    ]
    projected = project_planner_ledger(ledger, "mid_goal", None)
    contents = " ".join(str(getattr(m, "content", "")) for m in projected)
    assert "gc a1" in contents
    assert "exec a2" in contents
    assert "exec h2" in contents
    assert "exec a1" not in contents
    assert "exec h1" not in contents


def test_project_planner_ledger_mid_goal_includes_execute() -> None:
    state = LoopState(
        goal="g",
        thread_id="t",
        iteration=1,
        loop_messages=[
            LoopHumanMessage(content="exec h", phase="execute_step", thread_id="t"),
            LoopAIMessage(content="exec a", phase="execute_step", thread_id="t"),
        ],
    )
    projected = project_planner_ledger(
        state.loop_messages,
        resolve_planner_projection_mode(state),
        None,
    )
    assert len(projected) == 2


def test_project_planner_ledger_excludes_plan_assess_by_default() -> None:
    ledger = [
        LoopHumanMessage(content="assess h0", phase="plan_assess", iteration=0, thread_id="t"),
        LoopAIMessage(content="assess a0", phase="plan_assess", iteration=0, thread_id="t"),
        LoopHumanMessage(content="gen h0", phase="plan_generate", iteration=0, thread_id="t"),
        LoopAIMessage(content="gen a0", phase="plan_generate", iteration=0, thread_id="t"),
        LoopHumanMessage(content="exec h", phase="execute_step", thread_id="t"),
        LoopAIMessage(content="exec a", phase="execute_step", thread_id="t"),
    ]
    projected = project_planner_ledger(ledger, "mid_goal", None)
    contents = " ".join(str(getattr(m, "content", "")) for m in projected)
    assert "assess h0" not in contents
    assert "assess a0" not in contents
    assert "gen h0" in contents
    assert "exec h" in contents


def test_build_plan_assess_messages_omit_prior_plan_assess_ledger() -> None:
    state = LoopState(
        goal="read readme",
        thread_id="t",
        iteration=1,
        loop_messages=[
            LoopHumanMessage(content="assess h0", phase="plan_assess", iteration=0, thread_id="t"),
            LoopAIMessage(content="assess a0", phase="plan_assess", iteration=0, thread_id="t"),
            LoopHumanMessage(content="exec h", phase="execute_step", thread_id="t"),
            LoopAIMessage(content="exec a", phase="execute_step", thread_id="t"),
        ],
    )
    msgs = PromptBuilder().build_plan_messages(
        state.goal,
        state,
        PlanContext(),
        plan_phase="assess",
    )
    contents = " ".join(str(getattr(m, "content", "")) for m in msgs)
    assert "assess h0" not in contents
    assert "assess a0" not in contents
    assert "exec h" not in contents
    assert "exec a" in contents


def test_build_plan_generate_messages_omit_plan_assess_from_projection() -> None:
    state = LoopState(
        goal="read readme",
        thread_id="t",
        iteration=1,
        loop_messages=[
            LoopHumanMessage(content="assess h1", phase="plan_assess", iteration=1, thread_id="t"),
            LoopAIMessage(content="assess a1", phase="plan_assess", iteration=1, thread_id="t"),
            LoopHumanMessage(content="exec h", phase="execute_step", thread_id="t"),
            LoopAIMessage(content="exec a", phase="execute_step", thread_id="t"),
        ],
    )
    msgs = PromptBuilder().build_plan_messages(
        state.goal,
        state,
        PlanContext(),
        plan_phase="generate",
        inline_assessment=StatusAssessment(
            status="continue",
            goal_progress="low",
            assessment_reasoning="Checked evidence.",
        ),
    )
    contents = " ".join(str(getattr(m, "content", "")) for m in msgs)
    assert "assess h1" not in contents
    assert "assess a1" not in contents
    assert "exec h" in contents
    assert "ASSESSMENT:" in msgs[-1].content
