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


def test_generate_system_includes_policies_and_plan_generate() -> None:
    """Generate phase keeps execution policies and schema-aligned plan-generate instructions (IG-329)."""
    state = LoopState(goal="g", thread_id="t1", iteration=0, max_iterations=8)
    ctx = PlanContext(workspace=None)
    builder = PromptBuilder()
    messages = builder.build_plan_messages("g", state, ctx, plan_phase="generate")
    system = messages[0]
    assert isinstance(system, SystemMessage)
    assert "<PLAN_GENERATE>" in system.content
    assert "<PLAN_EXECUTE_LOOP>" not in system.content
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
    assert "<GOAL_PROGRESS>" in system
    assert "Goal: analyze" in system
    assert "Execute iteration: 1/8" in system


def test_assess_goal_progress_in_system_not_human_ig376() -> None:
    """Plan-assess puts Goal + Execute iteration in system <GOAL_PROGRESS>; no trailing plan human without prior thread."""
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
    messages = builder.build_plan_messages("read readme", state, PlanContext(), plan_phase="assess")
    assert len(messages) == 1
    system = messages[0].content
    assert "<GOAL_PROGRESS>" in system
    assert "Goal: read readme" in system
    assert "Execute iteration: 3/8" in system
    assert "Plan status:" not in system


def test_assess_iteration_zero_goal_progress_footer() -> None:
    """Assess iteration 0 maps to execute iteration 1/max in <GOAL_PROGRESS>."""
    state = LoopState(goal="read readme", thread_id="t1", iteration=0, max_iterations=8)
    builder = PromptBuilder()
    messages = builder.build_plan_messages("read readme", state, PlanContext(), plan_phase="assess")
    assert len(messages) == 1
    system = messages[0].content
    assert "Goal: read readme" in system
    assert "Execute iteration: 1/8" in system


def test_generate_human_still_includes_goal_and_execute_iteration() -> None:
    """Plan-generate keeps Goal + Execute iteration on the plan-context human."""
    state = LoopState(goal="read readme", thread_id="t1", iteration=2, max_iterations=8)
    builder = PromptBuilder()
    messages = builder.build_plan_messages(
        "read readme", state, PlanContext(), plan_phase="generate"
    )
    human = messages[-1].content
    assert human.startswith("Goal: read readme\nExecute iteration: 3/8")
    assert "<GOAL_PROGRESS>" not in human
