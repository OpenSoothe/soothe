"""Plan-assess vs plan-generate system prompt split (IG-372)."""

from __future__ import annotations

from unittest.mock import MagicMock

from langchain_core.messages import SystemMessage

from soothe.core.loop.state.schemas import LoopState, PlanResult, StepResult
from soothe.core.loop.utils.messages import LoopHumanMessage
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
    assert "Language lock" in system.content
    assert "same natural language as the current goal statement" in system.content


def test_assess_with_config_still_includes_environment_workspace() -> None:
    """Assess retains ENVIRONMENT / WORKSPACE when config and workspace set."""
    state = LoopState(goal="analyze", thread_id="t1", iteration=0, max_iterations=8)
    ctx = PlanContext(workspace="/abs/ws")
    config = MagicMock()
    config.resolve_model.return_value = "claude-opus-4-6"
    builder = PromptBuilder(config)
    messages = builder.build_plan_messages("analyze", state, ctx, plan_phase="assess")
    system = messages[0].content
    assert isinstance(messages[1], LoopHumanMessage)
    assert "<ENVIRONMENT" in system
    assert "<WORKSPACE" in system
    assert "/abs/ws" in system
    # System prompt may mention <USER_QUERY> in instruction text, but
    # the actual user query content is in the human message only.
    assert "</USER_QUERY>" not in system


def test_assess_omits_workspace_rules_and_instructions(tmp_path) -> None:
    """plan-assess is a meta-decision; workspace conventions / project rules
    don't apply to it, so WORKSPACE_RULES and WORKSPACE_INSTRUCTIONS must NOT
    appear in the assess system prompt even when the workspace has AGENTS.md.
    """
    (tmp_path / "AGENTS.md").write_text("# Project rules\n\nBe terse.\n", encoding="utf-8")
    state = LoopState(goal="analyze", thread_id="t1", iteration=0, max_iterations=8)
    ctx = PlanContext(workspace=str(tmp_path))
    config = MagicMock()
    config.resolve_model.return_value = "claude-opus-4-6"
    builder = PromptBuilder(config)
    assess_system = builder.build_plan_messages("analyze", state, ctx, plan_phase="assess")[
        0
    ].content
    generate_system = builder.build_plan_messages("analyze", state, ctx, plan_phase="generate")[
        0
    ].content

    # Assess: stripped.
    assert "<WORKSPACE_RULES>" not in assess_system
    assert "<WORKSPACE_INSTRUCTIONS>" not in assess_system
    # Generate: present (authors steps that touch the workspace).
    assert "<WORKSPACE_RULES>" in generate_system
    assert "<WORKSPACE_INSTRUCTIONS>" in generate_system
    assert "Be terse." in generate_system


def test_assess_user_query_in_plan_context_user_message_ig376() -> None:
    """Plan-assess puts goal in user <USER_QUERY>; system has no goal block."""
    state = LoopState(goal="read readme", thread_id="t1", iteration=2, max_iterations=8)
    state.previous_plan = PlanResult(
        status="continue",
        goal_progress="low",
        plan_action="keep",
        decision=None,
        next_action="Open README and show first lines",
    )
    builder = PromptBuilder()
    messages = builder.build_plan_messages("read readme", state, PlanContext(), plan_phase="assess")
    assert len(messages) == 2
    system = messages[0].content
    human = messages[1].content
    assert "</USER_QUERY>" not in system
    assert "<USER_QUERY>" in human
    assert "read readme" in human
    assert "Execute iteration" not in human
    assert "Plan status:" not in system


def test_assess_iteration_zero_user_query_without_iteration_count() -> None:
    """Assess iteration 0 still produces <USER_QUERY> without iteration count."""
    state = LoopState(goal="read readme", thread_id="t1", iteration=0, max_iterations=8)
    builder = PromptBuilder()
    messages = builder.build_plan_messages("read readme", state, PlanContext(), plan_phase="assess")
    assert len(messages) == 2
    human = messages[1].content
    assert "read readme" in human
    assert "Execute iteration" not in human


def test_generate_user_query_in_plan_context_user_message() -> None:
    """Plan-generate puts goal in user <USER_QUERY>; system has no goal block."""
    state = LoopState(goal="read readme", thread_id="t1", iteration=2, max_iterations=8)
    builder = PromptBuilder()
    messages = builder.build_plan_messages(
        "read readme", state, PlanContext(), plan_phase="generate"
    )
    assert len(messages) == 2
    system = messages[0].content
    human = messages[1].content
    assert "<PLAN_GENERATE>" in system
    assert "</USER_QUERY>" not in system
    assert "<USER_QUERY>" in human
    assert "read readme" in human
    assert "Execute iteration" not in human


def test_generate_includes_plan_step_id_hint_after_prior_steps_ig388() -> None:
    """Plan-generate human adds continuation hint when the goal already has step ids (IG-388)."""
    state = LoopState(goal="g", thread_id="t1", iteration=1, max_iterations=8)
    state.add_step_result(StepResult(step_id="ABC-01", success=True, duration_ms=1, thread_id="t1"))
    builder = PromptBuilder()
    messages = builder.build_plan_messages("g", state, PlanContext(), plan_phase="generate")
    human = messages[1].content
    assert "<PLAN_STEP_ID_HINT>" in human
    assert "02" in human
    assert "03" in human


def test_assess_does_not_include_plan_step_id_hint_ig388() -> None:
    state = LoopState(goal="g", thread_id="t1", iteration=1, max_iterations=8)
    state.add_step_result(StepResult(step_id="ABC-01", success=True, duration_ms=1, thread_id="t1"))
    builder = PromptBuilder()
    messages = builder.build_plan_messages("g", state, PlanContext(), plan_phase="assess")
    human = messages[1].content
    assert "<PLAN_STEP_ID_HINT>" not in human
