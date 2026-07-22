"""Plan-phase prompt includes workspace context (Layer 2, RFC-104)."""

from __future__ import annotations

from unittest.mock import MagicMock

from langchain_core.messages import SystemMessage
from soothe_sdk.protocols.planner import PlanContext

from soothe.prompts import PromptBuilder
from soothe.sloop.state.schemas import LoopState
from soothe.sloop.utils.messages import LoopAIMessage, LoopHumanMessage


def test_build_loop_plan_messages_with_config_omits_workspace_blocks() -> None:
    """plan-generate omits workspace blocks; those live on execute-step system prompts."""
    state = LoopState(goal="analyze architecture", thread_id="t1", max_iterations=8)
    ctx = PlanContext(workspace="/abs/path/to/repo")
    config = MagicMock()
    config.resolve_model.return_value = "claude-opus-4-6"
    builder = PromptBuilder(config)
    messages = builder.build_plan_messages(
        "analyze architecture", state, ctx, plan_phase="generate"
    )

    assert len(messages) == 2
    assert isinstance(messages[0], SystemMessage)
    assert isinstance(messages[1], LoopHumanMessage)

    system_content = messages[0].content
    human_content = messages[1].content

    assert "<ENVIRONMENT" not in system_content
    assert "<WORKSPACE" not in system_content
    assert "/abs/path/to/repo" not in system_content
    assert "<WORKSPACE_RULES>" not in system_content
    assert "<EXECUTION_POLICIES>" in system_content
    assert "<PLAN_GENERATE>" in system_content

    assert "</USER_QUERY>" not in system_content
    assert "GOAL:" in human_content
    assert "analyze architecture" in human_content


def test_build_loop_plan_messages_without_config_omits_workspace_blocks() -> None:
    """plan-generate without config still omits WORKSPACE / WORKSPACE_RULES."""
    state = LoopState(goal="analyze architecture", thread_id="t1", max_iterations=8)
    ctx = PlanContext(workspace="/abs/path/to/repo")
    builder = PromptBuilder()
    messages = builder.build_plan_messages(
        "analyze architecture", state, ctx, plan_phase="generate"
    )

    assert len(messages) == 2
    system_content = messages[0].content
    human_content = messages[1].content

    assert "<ENVIRONMENT" not in system_content
    assert "<WORKSPACE" not in system_content
    assert "/abs/path/to/repo" not in system_content
    assert "<WORKSPACE_RULES>" not in system_content

    assert "</USER_QUERY>" not in system_content
    assert "GOAL:" in human_content
    assert "analyze architecture" in human_content


def test_build_loop_plan_messages_omits_workspace_rules_without_workspace() -> None:
    """Test build_plan_messages() omits WORKSPACE_RULES when no workspace."""
    state = LoopState(goal="hi", thread_id="t1", max_iterations=8)
    ctx = PlanContext(workspace=None)
    builder = PromptBuilder()
    messages = builder.build_plan_messages("hi", state, ctx)

    system_content = messages[0].content
    assert "<WORKSPACE_RULES>" not in system_content


def test_build_loop_plan_messages_omits_working_memory_in_plan_human_ig371() -> None:
    """Plan-context human does not embed WORKING_MEMORY; ledger carries execution context (IG-371)."""
    state = LoopState(goal="g", thread_id="t1", max_iterations=8)
    ctx = PlanContext(
        workspace=None,
        working_memory_excerpt="[step_0] ✓ listed src/",
    )
    builder = PromptBuilder()
    messages = builder.build_plan_messages("g", state, ctx)

    full = "\n".join(m.content for m in messages)
    assert "<WORKING_MEMORY>" not in full
    assert "listed src/" not in full


def test_build_loop_plan_messages_includes_prior_conversation_ig128() -> None:
    """Plan-generate converts prior conversation XML to native ledger turns (RFC-214)."""
    state = LoopState(goal="翻译成中文", thread_id="t1", max_iterations=8)
    ctx = PlanContext(
        workspace=None,
        recent_messages=[
            "<USER>\nIran news please\n</USER>",
            "<ASSISTANT>\n**Infrastructure** … long body …\n</ASSISTANT>",
        ],
    )
    builder = PromptBuilder()
    messages = builder.build_plan_messages(
        "翻译成中文",
        state,
        ctx,
        plan_phase="generate",
    )

    system_content = messages[0].content

    # Prior conversation now appears as native LoopHumanMessage/LoopAIMessage in message list
    assert "<PRIOR_CONVERSATION>" not in messages[-1].content
    # 4 messages: System + 2 prior thread messages (user+assistant) + plan-context human
    assert len(messages) == 4
    assert isinstance(messages[1], LoopHumanMessage)
    assert isinstance(messages[2], LoopAIMessage)
    # Infrastructure appears in the prior thread LoopAIMessage, not plan-context human
    assert "Infrastructure" in messages[2].content
    assert "Infrastructure" not in messages[-1].content
    # Plan-context human starts with GOAL:
    assert messages[-1].content.strip().startswith("GOAL:")
    assert "</USER_QUERY>" not in system_content  # goal text lives in human message only
    assert "翻译成中文" in messages[-1].content
    # Plan prompts omit volatile clock — execute system prompt carries <TIMESTAMP> when needed.
    assert "TIMESTAMP:" not in messages[-1].content
    assert "<TIMESTAMP>" not in system_content

    # FOLLOW_UP_POLICY in SystemMessage (static rule)
    assert "<FOLLOW_UP_POLICY>" in system_content


def test_build_loop_plan_messages_plan_continue_when_steps_remain() -> None:
    """Test build_plan_messages() works with current_decision and completed steps."""
    from soothe.sloop.state.schemas import AgentDecision, StepAction

    state = LoopState(goal="g", thread_id="t1", max_iterations=8)
    state.current_decision = AgentDecision(
        type="execute_steps",
        steps=[
            StepAction(id="a", description="x", expected_output="o"),
            StepAction(id="b", description="y", expected_output="o"),
        ],
        execution_mode="parallel",
        reasoning="r",
    )
    state._completed_step_ids_cache = {"a"}
    builder = PromptBuilder()
    messages = builder.build_plan_messages("g", state, PlanContext())

    assert len(messages) == 2
    assert isinstance(messages[0], SystemMessage)
    assert isinstance(messages[1], LoopHumanMessage)


def test_build_plan_messages_appends_ledger_loop_messages() -> None:
    """Assess projection keeps execute AI only between system and task envelope (IG-557)."""
    state = LoopState(goal="read readme", thread_id="t1", max_iterations=8, iteration=1)
    state._loop_messages_cache = [
        LoopHumanMessage(
            content="Execute: read top of README",
            thread_id="t1",
            iteration=0,
            phase="execute_step",
        ),
        LoopAIMessage(
            content="First lines of README here.",
            thread_id="t1",
            iteration=0,
            phase="execute_step",
        ),
    ]
    builder = PromptBuilder()
    messages = builder.build_plan_messages("read readme", state, PlanContext())

    assert len(messages) == 3
    assert isinstance(messages[1], LoopAIMessage)
    assert isinstance(messages[2], LoopHumanMessage)
    assert "First lines of README" in messages[1].content
    system = messages[0].content
    plan_human = messages[2].content
    assert "</USER_QUERY>" not in system  # goal text lives in human message only
    assert "GOAL:" in plan_human
    assert "read readme" in plan_human
    assert "Execute iteration" not in plan_human
    assert "<AGENTLOOP_HISTORY>" not in system
