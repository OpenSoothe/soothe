"""Plan-assess vs plan-generate system prompt split (IG-372)."""

from __future__ import annotations

from unittest.mock import MagicMock

from langchain_core.messages import SystemMessage

from soothe.core.agent_loop.state.schemas import LoopState, PlanResult
from soothe.core.prompts import PromptBuilder
from soothe.protocols.planner import PlanContext


def test_assess_system_uses_plan_assess_not_full_execute_loop() -> None:
    """Assess phase system prompt matches StatusAssessment scope (compact)."""
    state = LoopState(goal="g", thread_id="t1", iteration=0, max_iterations=8)
    ctx = PlanContext(workspace=None)
    builder = PromptBuilder()
    messages = builder.build_plan_messages("g", state, ctx, plan_phase="assess")
    system = messages[0]
    assert isinstance(system, SystemMessage)
    assert "<PLAN_ASSESS>" in system.content
    assert "<PLAN_EXECUTE_LOOP>" not in system.content
    assert "<EXECUTION_POLICIES>" not in system.content


def test_generate_system_includes_policies_and_execute_loop() -> None:
    """Generate phase keeps execution policies and full plan instructions."""
    state = LoopState(goal="g", thread_id="t1", iteration=0, max_iterations=8)
    ctx = PlanContext(workspace=None)
    builder = PromptBuilder()
    messages = builder.build_plan_messages("g", state, ctx, plan_phase="generate")
    system = messages[0]
    assert isinstance(system, SystemMessage)
    assert "<PLAN_EXECUTE_LOOP>" in system.content
    assert "<EXECUTION_POLICIES>" in system.content
    assert "<PLAN_ASSESS>" not in system.content


def test_assess_with_config_still_includes_environment_workspace() -> None:
    """Assess retains ENVIRONMENT / WORKSPACE when config and workspace set."""
    state = LoopState(goal="analyze", thread_id="t1", iteration=0, max_iterations=8)
    ctx = PlanContext(workspace="/abs/ws")
    config = MagicMock()
    config.resolve_model.return_value = "claude-opus-4-6"
    builder = PromptBuilder(config)
    messages = builder.build_plan_messages("analyze", state, ctx, plan_phase="assess")
    system = messages[0].content
    assert "<ENVIRONMENT" in system
    assert "<WORKSPACE" in system
    assert "/abs/ws" in system


def test_plan_human_compact_when_iteration_positive_ig372() -> None:
    """After iteration 0, goal line uses iter= prefix; plan status is one line."""
    state = LoopState(goal="read readme", thread_id="t1", iteration=2, max_iterations=8)
    state.previous_plan = PlanResult(
        status="continue",
        confidence=0.85,
        goal_progress=0.4,
        plan_action="keep",
        decision=None,
        next_action="Open README and show first lines",
    )
    builder = PromptBuilder()
    messages = builder.build_plan_messages("read readme", state, PlanContext())
    human = messages[-1].content
    assert human.startswith("iter=2/8 | read readme")
    assert "Plan status: continue 40% | next: Open README and show first lines" in human
    assert "CURRENT PLAN STATUS" not in human


def test_plan_human_iteration_zero_still_uses_goal_prefix() -> None:
    """Iteration 0 keeps explicit Goal: line for cache/tests stability."""
    state = LoopState(goal="read readme", thread_id="t1", iteration=0, max_iterations=8)
    builder = PromptBuilder()
    messages = builder.build_plan_messages("read readme", state, PlanContext())
    assert "Goal: read readme" in messages[-1].content
