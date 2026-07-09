"""Tests for RFC-630 ``route_by_intent`` branch dispatch and the trivial branch.

Covers IG-528 test groups 2 (routing truth table), 4 (branch node sequence),
and 6 (trivial-branch synth plan + mislabel recovery).

IG-554: Routing guard tests for new_goal_created constraint blocking chitchat.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from langgraph.graph import END

from soothe.foundation.sloop.cognition.trivial_plan import build_trivial_plan
from soothe.foundation.sloop.intention.models import IntakeLabel
from soothe.foundation.sloop.orchestrator.nodes.init_or_resume import node_init_or_resume
from soothe.foundation.sloop.orchestrator.routing import route_by_intent


async def _noop_emit(*_args, **_kwargs) -> None:  # type: ignore[no-untyped-def]
    """No-op event sink for init_or_resume tests."""
    return None


# -- Group 2: route_by_intent truth table ---------------------------------


def test_route_by_intent_continuation_trivial() -> None:
    """Continuation trivial goals use plan_assess (continuation discriminator)."""
    state = {"is_continuation": True, "intake_label": IntakeLabel.TRIVIAL}
    assert route_by_intent(state) == "plan_assess"


def test_route_by_intent_continuation_simple() -> None:
    state = {"is_continuation": True, "intake_label": IntakeLabel.SIMPLE}
    assert route_by_intent(state) == "plan_generate"


def test_route_by_intent_continuation_complex() -> None:
    state = {"is_continuation": True, "intake_label": IntakeLabel.COMPLEX}
    assert route_by_intent(state) == "bounded_evidence_gather"


def test_route_by_intent_continuation_missing_label() -> None:
    state = {"is_continuation": True, "intake_label": None}
    assert route_by_intent(state) == "bounded_evidence_gather"


def test_route_by_intent_trivial() -> None:
    state = {"is_continuation": False, "intake_label": IntakeLabel.TRIVIAL}
    assert route_by_intent(state) == "resolve_decision"


def test_route_by_intent_chitchat_fast_path() -> None:
    state = {
        "is_continuation": False,
        "intake_label": IntakeLabel.CHITCHAT,
        "intent_route": "fast_path",
    }
    assert route_by_intent(state) == END


def test_route_by_intent_chitchat_fast_path_wins_over_continuation() -> None:
    """Chitchat fast-path must bypass continuation overlay (RFC-630)."""
    state = {
        "is_continuation": True,
        "intake_label": IntakeLabel.CHITCHAT,
        "intent_route": "fast_path",
    }
    assert route_by_intent(state) == END


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


# -- Group 4: trivial pseudo-plan (in-graph execute) ------------------------


@pytest.mark.asyncio
async def test_init_or_resume_chitchat_fast_path_with_continue_loop_mode() -> None:
    """Chitchat must bypass StrangeLoop even when the loop has prior goals."""
    from soothe.foundation.sloop.intention import IntentClassification, TaskComplexity

    emitted: list[tuple[str, object]] = []

    async def _emit(event_type: str, event_data: object) -> None:
        emitted.append((event_type, event_data))

    intent = IntentClassification(
        intake_label=IntakeLabel.CHITCHAT,
        chitchat_response="I'm Soothe, a cloud-based AI assistant.",
        task_complexity=TaskComplexity.MINIMAL,
    )
    scratch = SimpleNamespace(plan_result=None, plan_assessment=None, decision=None)
    loop_state = SimpleNamespace(
        intent=intent,
        goal="where are u from",
        thread_id="loop-main",
    )
    prior_goal = SimpleNamespace(
        id="goal-0",
        status="completed",
        description="who are u",
        action_history=[],
        steps=SimpleNamespace(nodes={}),
    )
    ctx = SimpleNamespace(
        loop_state=loop_state,
        scratch=scratch,
        ce=SimpleNamespace(get_all_goals=lambda: [prior_goal]),
        ce_goal_id="goal-1",
        checkpoint=SimpleNamespace(goal_history=[SimpleNamespace(), SimpleNamespace()]),
        continue_loop_mode=True,
        recovery_valid_resume=False,
        emit=_emit,
    )

    result = await node_init_or_resume(ctx, {})

    assert result["intent_route"] == "fast_path"
    assert result["is_continuation"] is True
    assert any(t == "intent_fast_path" for t, _ in emitted)
    assert scratch.plan_result is None


@pytest.mark.asyncio
async def test_init_or_resume_trivial_injects_pseudo_plan() -> None:
    """The trivial label injects a 1-step plan and continues through execute."""
    from soothe.foundation.sloop.intention import IntentClassification, TaskComplexity

    emitted: list[tuple[str, object]] = []

    async def _emit(event_type: str, event_data: object) -> None:
        emitted.append((event_type, event_data))

    intent = IntentClassification(
        intake_label=IntakeLabel.TRIVIAL,
        task_complexity=TaskComplexity.MINIMAL,
    )
    scratch = SimpleNamespace(plan_result=None, plan_assessment=None, decision=None)
    loop_state = SimpleNamespace(
        intent=intent,
        goal="list files in this directory",
        thread_id="loop-main",
    )
    ctx = SimpleNamespace(
        loop_state=loop_state,
        scratch=scratch,
        ce=None,
        ce_goal_id=None,
        continue_loop_mode=False,
        recovery_valid_resume=True,
        emit=_emit,
    )

    result = await node_init_or_resume(ctx, {})

    assert result["intake_label"] == IntakeLabel.TRIVIAL
    assert result["intent_route"] == "continue_loop"
    assert not any(t == "intent_fast_path" for t, _ in emitted)
    assert scratch.plan_result is not None
    assert scratch.plan_result.terminal_after_execute is True
    assert scratch.plan_result.decision is not None
    assert len(scratch.plan_result.decision.steps) == 1
    assert scratch.plan_result.decision.steps[0].description == "list files in this directory"


@pytest.mark.asyncio
async def test_init_or_resume_trivial_skipped_when_continue_loop() -> None:
    """Trivial intake must not bypass plan_assess when loop continuation is active."""
    from soothe.foundation.sloop.intention import IntentClassification, TaskComplexity

    intent = IntentClassification(
        intake_label=IntakeLabel.TRIVIAL,
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
async def test_init_or_resume_simple_synthesizes_assessment_on_continuation() -> None:
    """Simple intake on continuation turns still synthesizes plan_assessment."""
    from soothe.foundation.sloop.intention import IntentClassification, TaskComplexity

    intent = IntentClassification(
        intake_label=IntakeLabel.SIMPLE,
        task_complexity=TaskComplexity.SIMPLE,
    )
    scratch = SimpleNamespace(plan_result=None, plan_assessment=None, decision=None)
    loop_state = SimpleNamespace(intent=intent, goal="upgrade client library")
    prior_goal = SimpleNamespace(
        id="goal-0",
        status="completed",
        description="prior work",
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
        emit=_noop_emit,
    )

    result = await node_init_or_resume(ctx, {})

    assert result["is_continuation"] is True
    assert scratch.plan_assessment is not None
    assert scratch.plan_assessment.status == "continue"


@pytest.mark.asyncio
async def test_init_or_resume_simple_synthesizes_assessment() -> None:
    """The simple label synthesizes a plan_assessment so plan_generate can run."""
    from soothe.foundation.sloop.intention import IntentClassification, TaskComplexity

    intent = IntentClassification(
        intake_label=IntakeLabel.SIMPLE,
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
        intake_label=IntakeLabel.COMPLEX,
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
    assert plan.terminal_after_execute is True
    assert plan.require_goal_completion is False
    assert "Direct answer" in plan.decision.steps[0].expected_output
    assert plan.decision.steps[0].requires_tool_use is False


# -- IG-554: Routing guard tests (new_goal_created constraint) --------------


def test_routing_guard_blocks_chitchat_on_new_goal() -> None:
    """IG-554: chitchat fast-path blocked when new_goal_created=True."""
    state = {
        "is_continuation": False,
        "intake_label": IntakeLabel.CHITCHAT,
        "intent_route": "fast_path",
        "new_goal_created": True,
    }
    # Routing guard forces complex instead of END
    assert route_by_intent(state) == "bounded_evidence_gather"


def test_routing_guard_blocks_chitchat_label_on_new_goal() -> None:
    """IG-554: chitchat label forced to complex when new_goal_created=True."""
    state = {
        "is_continuation": False,
        "intake_label": IntakeLabel.CHITCHAT,
        "new_goal_created": True,
    }
    # Routing guard forces complex instead of END
    assert route_by_intent(state) == "bounded_evidence_gather"


def test_routing_guard_allows_chitchat_on_existing_goal() -> None:
    """IG-554: chitchat allowed when new_goal_created=False (resume existing)."""
    state = {
        "is_continuation": False,
        "intake_label": IntakeLabel.CHITCHAT,
        "intent_route": "fast_path",
        "new_goal_created": False,
    }
    assert route_by_intent(state) == END


def test_routing_guard_complex_not_blocked_by_new_goal() -> None:
    """IG-554: complex label not affected by routing guard."""
    state = {
        "is_continuation": False,
        "intake_label": IntakeLabel.COMPLEX,
        "new_goal_created": True,
    }
    assert route_by_intent(state) == "bounded_evidence_gather"


def test_routing_guard_simple_not_blocked_by_new_goal() -> None:
    """IG-554: simple label not affected by routing guard."""
    state = {
        "is_continuation": False,
        "intake_label": IntakeLabel.SIMPLE,
        "new_goal_created": True,
    }
    assert route_by_intent(state) == "plan_generate"


def test_routing_guard_trivial_not_blocked_by_new_goal() -> None:
    """IG-554: trivial label not affected by routing guard."""
    state = {
        "is_continuation": False,
        "intake_label": IntakeLabel.TRIVIAL,
        "new_goal_created": True,
    }
    assert route_by_intent(state) == "resolve_decision"


def test_routing_guard_missing_new_goal_defaults_false() -> None:
    """IG-554: missing new_goal_created defaults to False (chitchat allowed)."""
    state = {
        "is_continuation": False,
        "intake_label": IntakeLabel.CHITCHAT,
        "intent_route": "fast_path",
    }
    assert route_by_intent(state) == END
