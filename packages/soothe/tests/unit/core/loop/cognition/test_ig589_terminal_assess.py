"""IG-589: plan-assess terminal consistency structural gates."""

from __future__ import annotations

from soothe.context.planning_completion import _dag_requires_synthesis
from soothe.sloop.cognition.plan_step_safety import (
    assess_respects_gap_analysis,
    derive_goal_progress_from_status,
    normalize_status_assessment,
    terminal_assess_may_complete,
)
from soothe.sloop.intention.models import (
    IntakeLabel,
    IntentClassification,
    TaskComplexity,
)
from soothe.sloop.state.schemas import (
    GoalComponentStatus,
    LoopState,
    PlanGapAnalysis,
    PriorProgressDigest,
    StatusAssessment,
    StepResult,
)


def _loop_state(**kwargs: object) -> LoopState:
    state = LoopState(goal="make all cases pass", thread_id="t", iteration=1)
    for key, value in kwargs.items():
        setattr(state, key, value)
    return state


def test_normalize_coerces_done_with_none_progress() -> None:
    raw = StatusAssessment(status="done", goal_progress="none")
    normalized = normalize_status_assessment(raw)
    assert normalized.status == "replan"
    assert normalized.goal_progress == "none"


def test_normalize_coerces_done_without_terminal_readiness() -> None:
    raw = StatusAssessment(
        status="done",
        goal_progress="high",
        terminal_readiness="not_ready",
    )
    normalized = normalize_status_assessment(raw)
    assert normalized.status == "replan"


def test_normalize_accepts_done_when_gap_confirms_at_goal() -> None:
    raw = StatusAssessment(status="done", goal_progress="none", terminal_readiness="not_ready")
    gap = PlanGapAnalysis(
        components=[GoalComponentStatus(component="file exists", status="satisfied")],
        evidence_summary="confirmed",
        distance_from_goal="at_goal",
        gap_reasoning="all components satisfied",
    )
    normalized = normalize_status_assessment(raw, gap)
    assert normalized.status == "done"
    assert normalized.goal_progress == "complete"
    assert normalized.terminal_readiness == "ready"


def test_terminal_assess_rejects_done_with_low_progress() -> None:
    state = _loop_state()
    state.add_step_result(StepResult(step_id="01", success=True, duration_ms=1, thread_id="t"))
    assessment = StatusAssessment(status="done", goal_progress="none")
    assert (
        terminal_assess_may_complete(
            state,
            assessment,
            None,
            intake_label=IntakeLabel.COMPLEX,
        )
        is False
    )


def test_terminal_assess_rejects_when_gap_near_with_open_component() -> None:
    state = _loop_state()
    state.add_step_result(StepResult(step_id="01", success=True, duration_ms=1, thread_id="t"))
    gap = PlanGapAnalysis(
        components=[
            GoalComponentStatus(component="final validation", status="partial"),
        ],
        evidence_summary="baseline run only",
        remaining_gaps=["fix failures"],
        distance_from_goal="near",
        gap_reasoning="one component open",
    )
    assessment = StatusAssessment(
        status="done",
        goal_progress="high",
        terminal_readiness="ready",
        gap_alignment=True,
    )
    assert assess_respects_gap_analysis(assessment, gap) is False
    assert (
        terminal_assess_may_complete(
            state,
            assessment,
            gap,
            intake_label=IntakeLabel.COMPLEX,
        )
        is False
    )


def test_terminal_assess_rejects_multi_phase_without_complete_progress() -> None:
    state = _loop_state(
        intent=IntentClassification(
            intake_label=IntakeLabel.COMPLEX,
            reasoning="multi wave",
            multi_phase=True,
            task_complexity=TaskComplexity.COMPLEX,
        ),
    )
    state.add_step_result(StepResult(step_id="01", success=True, duration_ms=1, thread_id="t"))
    gap = PlanGapAnalysis(
        components=[GoalComponentStatus(component="tests green", status="satisfied")],
        evidence_summary="all pass",
        distance_from_goal="at_goal",
        gap_reasoning="done",
    )
    assessment = StatusAssessment(
        status="done",
        goal_progress="high",
        terminal_readiness="ready",
        gap_alignment=True,
    )
    assert (
        terminal_assess_may_complete(
            state,
            assessment,
            gap,
            intake_label=IntakeLabel.COMPLEX,
        )
        is False
    )


def test_terminal_assess_allows_prior_progress_lag_when_gap_proves_terminal() -> None:
    state = _loop_state(
        prior_progress=PriorProgressDigest(
            iteration=1,
            derived_progress_hint="medium",
        ),
    )
    state.add_step_result(StepResult(step_id="01", success=True, duration_ms=1, thread_id="t"))
    gap = PlanGapAnalysis(
        components=[GoalComponentStatus(component="all docs updated", status="satisfied")],
        evidence_summary="all goal components verified",
        distance_from_goal="at_goal",
        gap_reasoning="terminal evidence complete",
    )
    assessment = StatusAssessment(
        status="done",
        goal_progress="complete",
        terminal_readiness="ready",
        gap_alignment=True,
    )
    assert (
        terminal_assess_may_complete(
            state,
            assessment,
            gap,
            intake_label=IntakeLabel.COMPLEX,
        )
        is True
    )


def test_terminal_assess_allows_gap_terminal_even_when_gap_alignment_false() -> None:
    state = _loop_state()
    state.add_step_result(StepResult(step_id="01", success=True, duration_ms=1, thread_id="t"))
    gap = PlanGapAnalysis(
        components=[GoalComponentStatus(component="all docs updated", status="satisfied")],
        evidence_summary="all goal components verified",
        distance_from_goal="at_goal",
        gap_reasoning="terminal evidence complete",
    )
    assessment = StatusAssessment(
        status="done",
        goal_progress="complete",
        terminal_readiness="ready",
        gap_alignment=False,
    )
    assert (
        terminal_assess_may_complete(
            state,
            assessment,
            gap,
            intake_label=IntakeLabel.COMPLEX,
        )
        is True
    )


def test_terminal_assess_requires_gap_alignment_when_no_gap_snapshot() -> None:
    state = _loop_state()
    state.add_step_result(StepResult(step_id="01", success=True, duration_ms=1, thread_id="t"))
    assessment = StatusAssessment(
        status="done",
        goal_progress="high",
        terminal_readiness="ready",
        gap_alignment=False,
    )
    assert (
        terminal_assess_may_complete(
            state,
            assessment,
            None,
            intake_label=IntakeLabel.COMPLEX,
        )
        is False
    )


def test_terminal_assess_rejects_recoverable_tool_errors_without_complete() -> None:
    state = _loop_state()
    state.add_step_result(
        StepResult(
            step_id="01",
            success=True,
            duration_ms=1,
            thread_id="t",
            had_recoverable_tool_errors=True,
        )
    )
    gap = PlanGapAnalysis(
        components=[GoalComponentStatus(component="token works", status="satisfied")],
        evidence_summary="token found",
        distance_from_goal="at_goal",
        gap_reasoning="ok",
    )
    assessment = StatusAssessment(
        status="done",
        goal_progress="high",
        terminal_readiness="ready",
        gap_alignment=True,
    )
    assert (
        terminal_assess_may_complete(
            state,
            assessment,
            gap,
            intake_label=IntakeLabel.COMPLEX,
        )
        is False
    )


def test_terminal_assess_allows_complete_with_at_goal_gap() -> None:
    state = _loop_state()
    state.add_step_result(StepResult(step_id="01", success=True, duration_ms=1, thread_id="t"))
    gap = PlanGapAnalysis(
        components=[GoalComponentStatus(component="all tests pass", status="satisfied")],
        evidence_summary="exit 0",
        distance_from_goal="at_goal",
        gap_reasoning="satisfied",
    )
    assessment = StatusAssessment(
        status="done",
        goal_progress="complete",
        terminal_readiness="ready",
        gap_alignment=True,
    )
    assert (
        terminal_assess_may_complete(
            state,
            assessment,
            gap,
            intake_label=IntakeLabel.COMPLEX,
        )
        is True
    )


def test_terminal_assess_ignores_progress_without_done_status() -> None:
    state = _loop_state()
    gap = PlanGapAnalysis(
        components=[GoalComponentStatus(component="all tests pass", status="satisfied")],
        evidence_summary="exit 0",
        distance_from_goal="at_goal",
        gap_reasoning="satisfied",
    )
    assessment = StatusAssessment(
        status="continue",
        goal_progress="complete",
        terminal_readiness="ready",
        gap_alignment=True,
    )
    assert (
        terminal_assess_may_complete(
            state,
            assessment,
            gap,
            intake_label=IntakeLabel.COMPLEX,
        )
        is False
    )


def test_derive_goal_progress_from_status_done_uses_gap_completion() -> None:
    state = _loop_state()
    gap = PlanGapAnalysis(
        components=[GoalComponentStatus(component="all tests pass", status="satisfied")],
        evidence_summary="exit 0",
        distance_from_goal="at_goal",
        gap_reasoning="satisfied",
    )
    assessment = StatusAssessment(
        status="done",
        goal_progress="none",
        terminal_readiness="ready",
        gap_alignment=True,
    )
    assert derive_goal_progress_from_status(state, assessment, gap) == "complete"


def test_dag_requires_synthesis_skips_replan_when_not_terminal() -> None:
    assert (
        _dag_requires_synthesis(
            plan_wave_count=2,
            failed_steps=0,
            completed_steps=1,
            chain_depth=1,
            last_wave_hit_subagent_cap=False,
            last_execute_wave_parallel_multi_step=False,
            assessment_terminal=False,
        )
        is False
    )
