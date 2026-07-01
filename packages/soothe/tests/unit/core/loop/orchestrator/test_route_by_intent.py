"""Tests for RFC-630 ``route_by_intent`` branch dispatch and the trivial branch.

Covers IG-528 test groups 2 (routing truth table), 4 (branch node sequence),
and 6 (trivial-branch synth plan + mislabel recovery).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from soothe.foundation.sloop.cognition.trivial_plan import build_trivial_plan
from soothe.foundation.sloop.intention.models import IntakeLabel
from soothe.foundation.sloop.orchestrator.nodes.init_or_resume import node_init_or_resume
from soothe.foundation.sloop.orchestrator.routing import route_by_intent


async def _noop_emit(*_args, **_kwargs) -> None:  # type: ignore[no-untyped-def]
    """No-op event sink for init_or_resume tests."""
    return None


# -- Group 2: route_by_intent truth table ---------------------------------


def test_route_by_intent_continuation_overlay_wins() -> None:
    """Continuation (structural) overrides the intake label."""
    state = {"is_continuation": True, "intake_label": IntakeLabel.TRIVIAL}
    assert route_by_intent(state) == "plan_assess"


def test_route_by_intent_quiz_fast_path() -> None:
    state = {
        "is_continuation": False,
        "intent_route": "fast_path",
        "intake_label": IntakeLabel.QUIZ,
    }
    assert route_by_intent(state) == "__end__"


def test_route_by_intent_trivial() -> None:
    state = {"is_continuation": False, "intake_label": IntakeLabel.TRIVIAL}
    assert route_by_intent(state) == "resolve_decision"


def test_route_by_intent_simple() -> None:
    state = {"is_continuation": False, "intake_label": IntakeLabel.SIMPLE}
    assert route_by_intent(state) == "plan_generate"


def test_route_by_intent_complex() -> None:
    state = {"is_continuation": False, "intake_label": IntakeLabel.COMPLEX}
    assert route_by_intent(state) == "bounded_evidence_gather"


def test_route_by_intent_missing_label_falls_back_to_complex() -> None:
    """Fail-safe: a missing label routes to the full pipeline (complex)."""
    state = {"is_continuation": False, "intake_label": None}
    assert route_by_intent(state) == "bounded_evidence_gather"


# -- Group 4: trivial-branch synth plan injection -------------------------


@pytest.mark.asyncio
async def test_init_or_resume_trivial_injects_synth_plan() -> None:
    """The trivial label injects a 1-step plan into scratch, skipping plan_generate."""
    from soothe.foundation.sloop.intention import IntentClassification, TaskComplexity

    intent = IntentClassification(
        intent_type="agentic",
        intake_label=IntakeLabel.TRIVIAL,
        goal_description="list files in this directory",
        task_complexity=TaskComplexity.SIMPLE,
    )
    scratch = SimpleNamespace(plan_result=None, plan_assessment=None, decision=None)
    loop_state = SimpleNamespace(intent=intent, goal="list files in this directory")
    ctx = SimpleNamespace(
        loop_state=loop_state,
        scratch=scratch,
        ce=None,
        continue_loop_mode=False,
        emit=_noop_emit,
    )

    result = await node_init_or_resume(ctx, {})

    assert result["intake_label"] == IntakeLabel.TRIVIAL
    assert result["intent_route"] == "continue_loop"
    assert scratch.plan_result is not None
    # Goal-as-step-action, no "I will complete this goal directly:" prefix.
    assert "I will complete this goal directly" not in scratch.plan_result.next_action
    assert scratch.plan_result.next_action == "list files in this directory"
    assert scratch.plan_result.decision is not None
    assert len(scratch.plan_result.decision.steps) == 1


@pytest.mark.asyncio
async def test_init_or_resume_trivial_skipped_when_continue_loop() -> None:
    """Trivial intake must not bypass plan_assess when loop continuation is active."""
    from soothe.foundation.sloop.intention import IntentClassification, TaskComplexity

    intent = IntentClassification(
        intent_type="agentic",
        intake_label=IntakeLabel.TRIVIAL,
        goal_description="continue",
        task_complexity=TaskComplexity.SIMPLE,
    )
    scratch = SimpleNamespace(plan_result=None, plan_assessment=None, decision=None)
    loop_state = SimpleNamespace(intent=intent, goal="continue")
    prior_goal = SimpleNamespace(
        id="goal-0",
        status="cancelled",
        description="review local changes",
        action_history=[],
        steps=SimpleNamespace(nodes={"s1": SimpleNamespace(status="completed")}),
    )
    ctx = SimpleNamespace(
        loop_state=loop_state,
        scratch=scratch,
        ce=SimpleNamespace(get_all_goals=lambda: [prior_goal]),
        ce_goal_id="goal-1",
        checkpoint=SimpleNamespace(goal_history=[SimpleNamespace(), SimpleNamespace()]),
        continue_loop_mode=True,
        recovery_valid_resume=False,
        emit=_noop_emit,
    )

    result = await node_init_or_resume(ctx, {})

    assert result["is_continuation"] is True
    assert scratch.plan_result is None


@pytest.mark.asyncio
async def test_init_or_resume_simple_synthesizes_assessment() -> None:
    """The simple label synthesizes a plan_assessment so plan_generate can run."""
    from soothe.foundation.sloop.intention import IntentClassification, TaskComplexity

    intent = IntentClassification(
        intent_type="agentic",
        intake_label=IntakeLabel.SIMPLE,
        goal_description="summarize RFC-220 topology",
        task_complexity=TaskComplexity.SIMPLE,
    )
    scratch = SimpleNamespace(plan_result=None, plan_assessment=None, decision=None)
    loop_state = SimpleNamespace(intent=intent, goal="summarize RFC-220 topology")
    ctx = SimpleNamespace(
        loop_state=loop_state,
        scratch=scratch,
        ce=None,
        continue_loop_mode=False,
        emit=_noop_emit,
    )

    result = await node_init_or_resume(ctx, {})

    assert result["intake_label"] == IntakeLabel.SIMPLE
    assert scratch.plan_assessment is not None
    assert scratch.plan_assessment.status == "continue"


@pytest.mark.asyncio
async def test_init_or_resume_complex_does_not_inject_synth_plan() -> None:
    """The complex label leaves scratch empty — the full spine runs plan_assess/generate."""
    from soothe.foundation.sloop.intention import IntentClassification, TaskComplexity

    intent = IntentClassification(
        intent_type="agentic",
        intake_label=IntakeLabel.COMPLEX,
        goal_description="refactor persistence layer",
        task_complexity=TaskComplexity.COMPLEX,
    )
    scratch = SimpleNamespace(plan_result=None, plan_assessment=None, decision=None)
    loop_state = SimpleNamespace(intent=intent, goal="refactor persistence layer")
    ctx = SimpleNamespace(
        loop_state=loop_state,
        scratch=scratch,
        ce=None,
        continue_loop_mode=False,
        emit=_noop_emit,
    )

    result = await node_init_or_resume(ctx, {})

    assert result["intake_label"] == IntakeLabel.COMPLEX
    assert scratch.plan_result is None
    assert scratch.plan_assessment is None


# -- Group 6: mislabel recovery (trivial plan shape) ----------------------


def test_trivial_plan_has_no_synthetic_reasoning_prefix() -> None:
    """RFC-630 §11: the trivial plan emits the goal as the step, no verbose prefix."""
    plan = build_trivial_plan("list files in this directory")
    assert plan.next_action == "list files in this directory"
    assert plan.plan_reasoning == ""
    assert plan.decision is not None
    assert plan.decision.reasoning == ""
    # The ## Result evidence contract is retained.
    assert "## Result" in plan.decision.steps[0].expected_output
