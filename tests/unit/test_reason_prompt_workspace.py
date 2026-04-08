"""Reason-phase prompt includes workspace context (Layer 2, RFC-104)."""

from __future__ import annotations

from unittest.mock import MagicMock

from soothe.cognition.loop_agent.schemas import LoopState
from soothe.core.prompts import PromptBuilder
from soothe.protocols.planner import PlanContext


def test_build_loop_reason_prompt_with_config_includes_soothe_blocks() -> None:
    state = LoopState(goal="analyze architecture", thread_id="t1", max_iterations=8)
    ctx = PlanContext(workspace="/abs/path/to/repo")
    config = MagicMock()
    config.resolve_model.return_value = "claude-opus-4-6"
    builder = PromptBuilder(config)
    text = builder.build_reason_prompt("analyze architecture", state, ctx)
    assert "<SOOTHE_ENVIRONMENT" in text
    assert "<SOOTHE_WORKSPACE" in text
    assert "/abs/path/to/repo" in text
    assert "<SOOTHE_REASON_WORKSPACE_RULES>" in text
    assert "Do NOT ask the user" in text


def test_build_loop_reason_prompt_without_config_workspace_only() -> None:
    state = LoopState(goal="analyze architecture", thread_id="t1", max_iterations=8)
    ctx = PlanContext(workspace="/abs/path/to/repo")
    builder = PromptBuilder()
    text = builder.build_reason_prompt("analyze architecture", state, ctx)
    assert "<SOOTHE_ENVIRONMENT" not in text
    assert "<SOOTHE_WORKSPACE" in text
    assert "/abs/path/to/repo" in text
    assert "<SOOTHE_REASON_WORKSPACE_RULES>" in text


def test_build_loop_reason_prompt_omits_workspace_rules_without_workspace() -> None:
    state = LoopState(goal="hi", thread_id="t1", max_iterations=8)
    ctx = PlanContext(workspace=None)
    builder = PromptBuilder()
    text = builder.build_reason_prompt("hi", state, ctx)
    assert "<SOOTHE_REASON_WORKSPACE_RULES>" not in text


def test_build_loop_reason_prompt_includes_working_memory_excerpt() -> None:
    state = LoopState(goal="g", thread_id="t1", max_iterations=8)
    ctx = PlanContext(
        workspace=None,
        working_memory_excerpt="[step_0] ✓ listed src/",
    )
    builder = PromptBuilder()
    text = builder.build_reason_prompt("g", state, ctx)
    assert "<SOOTHE_LOOP_WORKING_MEMORY>" in text
    assert "listed src/" in text


def test_build_loop_reason_prompt_includes_prior_conversation_ig128() -> None:
    state = LoopState(goal="翻译成中文", thread_id="t1", max_iterations=8)
    # Set flag to False to trigger prior conversation injection (IG-133)
    state.act_will_have_checkpoint_access = False
    ctx = PlanContext(
        workspace=None,
        recent_messages=[
            "<user>\nIran news please\n</user>",
            "<assistant>\n**Infrastructure** … long body …\n</assistant>",
        ],
    )
    builder = PromptBuilder()
    text = builder.build_reason_prompt("翻译成中文", state, ctx)
    assert "<SOOTHE_PRIOR_CONVERSATION>" in text
    assert "<SOOTHE_FOLLOW_UP_POLICY>" in text
    assert "Infrastructure" in text
    assert "translate" in text.lower() or "Layer 1" in text


def test_build_loop_reason_prompt_plan_continue_when_steps_remain() -> None:
    from soothe.cognition.loop_agent.schemas import AgentDecision, StepAction

    state = LoopState(goal="g", thread_id="t1", max_iterations=8)
    state.current_decision = AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(id="a", description="x", expected_output="o"),
            StepAction(id="b", description="y", expected_output="o"),
        ],
        execution_mode="sequential",
        reasoning="r",
    )
    state.completed_step_ids = {"a"}
    builder = PromptBuilder()
    text = builder.build_reason_prompt("g", state, PlanContext())
    assert "PLAN_CONTINUE_POLICY" in text
