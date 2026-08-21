"""Tests for RFC-630 ``route_by_intent`` branch dispatch and minimal intake routing.

Covers test groups 2 (routing truth table), 4 (branch node sequence),
and 6 (wired-subagent plan shape + mislabel recovery).

Chitchat fast-path bypass is decided upstream in ``enter_loop`` via
``should_bypass_chitchat_fast_path``; routing trusts that decision and ENDs.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from langgraph.graph import END
from soothe_sdk.intention.models import TaskComplexity

from soothe.sloop.intention.models import IntakeLabel
from soothe.sloop.orchestrator.routing import route_by_intent
from soothe.sloop.plans.wired_subagent_plan import build_wired_subagent_plan
from soothe.sloop.stations.preprocess.enter_loop import node_init_or_resume


async def _noop_emit(*_args, **_kwargs) -> None:  # type: ignore[no-untyped-def]
    """No-op event sink for init_or_resume tests."""
    return None


# -- Group 2: route_by_intent truth table ---------------------------------


def test_route_by_intent_continuation_minimal() -> None:
    """Mid-loop minimal enters dispatch (default spine;)."""
    state = {
        "is_continuation": True,
        "is_fresh_goal": False,
        "intake_label": IntakeLabel.MINIMAL,
    }
    assert route_by_intent(state) == "dispatch"


def test_route_by_intent_continuation_simple() -> None:
    state = {
        "is_continuation": True,
        "is_fresh_goal": False,
        "intake_label": IntakeLabel.SIMPLE,
    }
    assert route_by_intent(state) == "dispatch"


def test_route_by_intent_continuation_complex() -> None:
    state = {
        "is_continuation": True,
        "is_fresh_goal": False,
        "intake_label": IntakeLabel.COMPLEX,
    }
    assert route_by_intent(state) == "dispatch"


def test_route_by_intent_continuation_missing_label() -> None:
    state = {"is_continuation": True, "is_fresh_goal": False, "intake_label": None}
    assert route_by_intent(state) == "dispatch"


def test_route_by_intent_minimal() -> None:
    state = {
        "is_continuation": False,
        "is_fresh_goal": True,
        "intake_label": IntakeLabel.MINIMAL,
    }
    assert route_by_intent(state) == "dispatch"


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
    state = {
        "is_continuation": False,
        "is_fresh_goal": True,
        "intake_label": IntakeLabel.SIMPLE,
    }
    assert route_by_intent(state) == "dispatch"


def test_route_by_intent_complex() -> None:
    state = {
        "is_continuation": False,
        "is_fresh_goal": True,
        "intake_label": IntakeLabel.COMPLEX,
    }
    assert route_by_intent(state) == "dispatch"


def test_route_by_intent_missing_label_falls_back_to_complex() -> None:
    """Fail-safe: a missing label on fresh routes to DISPATCH."""
    state = {"is_continuation": False, "is_fresh_goal": True, "intake_label": None}
    assert route_by_intent(state) == "dispatch"


# -- Group 4: minimal intake routing (DISPATCH) -----------------------------


@pytest.mark.asyncio
async def test_init_or_resume_chitchat_fast_path_with_continue_loop_mode() -> None:
    """Chitchat must bypass StrangeLoop even when the loop has prior goals."""
    from soothe.sloop.intention import IntentClassification

    emitted: list[tuple[str, object]] = []

    async def _emit(event_type: str, event_data: object) -> None:
        emitted.append((event_type, event_data))

    intent = IntentClassification(
        intake_label=IntakeLabel.CHITCHAT,
        chitchat_response="I'm Soothe, a cloud-based AI assistant.",
        task_complexity=TaskComplexity.MINIMAL,
    )
    scratch = SimpleNamespace(plan_result=None, decision=None)
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
async def test_init_or_resume_chitchat_continue_without_goal_history_is_social() -> None:
    """Bare continue with empty this-loop checkpoint stays in-graph chitchat."""
    from soothe.sloop.intention import IntentClassification

    emitted: list[tuple[str, object]] = []

    async def _emit(event_type: str, event_data: object) -> None:
        emitted.append((event_type, event_data))

    intent = IntentClassification(
        intake_label=IntakeLabel.CHITCHAT,
        chitchat_response="Sure, I'm ready when you are.",
        task_complexity=TaskComplexity.MINIMAL,
    )
    loop_state = SimpleNamespace(
        intent=intent,
        goal="continue",
        thread_id="loop-main",
    )
    ctx = SimpleNamespace(
        loop_state=loop_state,
        scratch=SimpleNamespace(plan_result=None, decision=None),
        ce=None,
        ce_goal_id=None,
        checkpoint=SimpleNamespace(goal_history=[]),
        continue_loop_mode=False,
        recovery_valid_resume=False,
        emit=_emit,
    )

    result = await node_init_or_resume(ctx, {})

    assert result["intent_route"] == "fast_path"
    assert any(t == "intent_fast_path" for t, _ in emitted)


@pytest.mark.asyncio
async def test_init_or_resume_chitchat_continue_with_goal_history_skips_fast_path() -> None:
    """Bare continue with this-loop goal history does not take in-graph chitchat."""
    from soothe.sloop.intention import IntentClassification

    intent = IntentClassification(
        intake_label=IntakeLabel.CHITCHAT,
        chitchat_response="Sure, I'm ready when you are.",
        task_complexity=TaskComplexity.MINIMAL,
    )
    loop_state = SimpleNamespace(
        intent=intent,
        goal="continue",
        thread_id="loop-main",
    )
    ctx = SimpleNamespace(
        loop_state=loop_state,
        scratch=SimpleNamespace(plan_result=None, decision=None),
        ce=None,
        ce_goal_id=None,
        checkpoint=SimpleNamespace(goal_history=[SimpleNamespace()]),
        continue_loop_mode=False,
        recovery_valid_resume=False,
        emit=_noop_emit,
    )

    result = await node_init_or_resume(ctx, {})

    assert result["intent_route"] == "continue_loop"


@pytest.mark.asyncio
async def test_init_or_resume_minimal_routes_to_dispatch() -> None:
    """Trivial label routes to DISPATCH without plan injection."""
    from soothe.sloop.intention import IntentClassification

    emitted: list[tuple[str, object]] = []

    async def _emit(event_type: str, event_data: object) -> None:
        emitted.append((event_type, event_data))

    intent = IntentClassification(
        intake_label=IntakeLabel.MINIMAL,
        task_complexity=TaskComplexity.MINIMAL,
    )
    scratch = SimpleNamespace(plan_result=None, decision=None)
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
        recovery_valid_resume=False,
        emit=_emit,
    )

    result = await node_init_or_resume(ctx, {})

    assert result["intake_label"] == IntakeLabel.MINIMAL
    assert result["is_fresh_goal"] is True
    assert result["intent_route"] == "continue_loop"
    assert not any(t == "intent_fast_path" for t, _ in emitted)
    # RFC-904: enter_loop no longer injects minimal plans; DISPATCH owns the root step.
    assert scratch.plan_result is None


@pytest.mark.asyncio
async def test_init_or_resume_minimal_skipped_when_continue_loop() -> None:
    """Trivial intake still routes through DISPATCH when loop continuation is active."""
    from soothe.sloop.intention import IntentClassification

    intent = IntentClassification(
        intake_label=IntakeLabel.MINIMAL,
        task_complexity=TaskComplexity.SIMPLE,
    )
    scratch = SimpleNamespace(plan_result=None, decision=None)
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
async def test_init_or_resume_simple_does_not_synthesize_assessment_on_continuation() -> None:
    """Simple mid-loop routes through DISPATCH; no plan injection."""
    from soothe.sloop.intention import IntentClassification

    intent = IntentClassification(
        intake_label=IntakeLabel.SIMPLE,
        task_complexity=TaskComplexity.SIMPLE,
    )
    scratch = SimpleNamespace(plan_result=None, decision=None)
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
    assert result["is_fresh_goal"] is False
    assert scratch.plan_result is None


@pytest.mark.asyncio
async def test_init_or_resume_simple_no_plan_injection() -> None:
    """Fresh-loop simple routes through DISPATCH; no plan injection."""
    from soothe.sloop.intention import IntentClassification

    intent = IntentClassification(
        intake_label=IntakeLabel.SIMPLE,
        task_complexity=TaskComplexity.SIMPLE,
    )
    scratch = SimpleNamespace(plan_result=None, decision=None)
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
    assert result["is_fresh_goal"] is True
    assert scratch.plan_result is None


@pytest.mark.asyncio
async def test_init_or_resume_complex_does_not_inject_synth_plan() -> None:
    """The complex label leaves scratch empty — DISPATCH owns the root step."""
    from soothe.sloop.intention import IntentClassification

    intent = IntentClassification(
        intake_label=IntakeLabel.COMPLEX,
        task_complexity=TaskComplexity.COMPLEX,
    )
    scratch = SimpleNamespace(plan_result=None, decision=None)
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


# -- Group 6: mislabel recovery (wired-subagent plan) -------------------


def test_wired_subagent_plan_has_no_synthetic_reasoning_prefix() -> None:
    """The wired-subagent plan emits the goal as the step, no verbose prefix."""
    plan = build_wired_subagent_plan("list files in this directory")
    assert plan.next_action == "list files in this directory"
    assert plan.decision is not None
    assert plan.decision.reasoning == ""
    assert plan.terminal_after_execute is True
    assert plan.require_goal_completion is False
    assert "Direct answer" in plan.decision.steps[0].expected_output
    assert plan.decision.steps[0].requires_tool_use is False


# -- Chitchat fast-path ENDs unconditionally (bypass is upstream) ------


def test_chitchat_fast_path_ends_unconditionally() -> None:
    """The fast-path ENDs the graph regardless of goal freshness.

    A social message like "how are u" on a fresh goal must short-circuit to
    END here; whether it should bypass the fast-path at all is decided upstream
    in enter_loop via should_bypass_chitchat_fast_path.
    """
    state = {
        "is_continuation": False,
        "intake_label": IntakeLabel.CHITCHAT,
        "intent_route": "fast_path",
    }
    assert route_by_intent(state) == END


def test_chitchat_fast_path_ends_even_on_continuation() -> None:
    """Fast-path ENDs even mid-loop; finalize-blocking is handled at finalize."""
    state = {
        "is_continuation": True,
        "intake_label": IntakeLabel.CHITCHAT,
        "intent_route": "fast_path",
    }
    assert route_by_intent(state) == END


def test_chitchat_label_without_fast_path_routes_to_dispatch() -> None:
    """Chitchat that did not take the fast-path (bypassed upstream) dispatches."""
    state = {
        "is_continuation": False,
        "intake_label": IntakeLabel.CHITCHAT,
        "intent_route": "continue_loop",
    }
    assert route_by_intent(state) == "dispatch"
