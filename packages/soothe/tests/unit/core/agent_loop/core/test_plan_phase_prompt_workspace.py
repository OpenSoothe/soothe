"""Plan-phase prompt includes workspace context (Layer 2, RFC-104)."""

from __future__ import annotations

from unittest.mock import MagicMock

from langchain_core.messages import SystemMessage

from soothe.core.agent_loop.state.schemas import LoopState
from soothe.core.agent_loop.utils.messages import LoopAIMessage, LoopHumanMessage
from soothe.core.prompts import PromptBuilder
from soothe.protocols.planner import PlanContext


def test_build_loop_plan_messages_with_config_includes_soothe_blocks() -> None:
    """Test build_plan_messages() with config includes ENVIRONMENT and WORKSPACE."""
    state = LoopState(goal="analyze architecture", thread_id="t1", max_iterations=8)
    ctx = PlanContext(workspace="/abs/path/to/repo")
    config = MagicMock()
    config.resolve_model.return_value = "claude-opus-4-6"
    builder = PromptBuilder(config)
    messages = builder.build_plan_messages("analyze architecture", state, ctx)

    # Assess: system + optional ledger; goal in <GOAL_PROGRESS> on system when no prior thread
    assert len(messages) == 1
    assert isinstance(messages[0], SystemMessage)

    system_content = messages[0].content

    # RFC-207: SystemMessage has static context
    # RFC-207: Removed SOOTHE_ prefix from all tags
    assert "<ENVIRONMENT" in system_content
    assert "<WORKSPACE" in system_content
    assert "/abs/path/to/repo" in system_content
    assert "<WORKSPACE_RULES>" in system_content
    assert "Do NOT ask the user" in system_content

    assert "<GOAL_PROGRESS>" in system_content
    assert "Goal: analyze architecture" in system_content
    assert "Execute iteration: 1/8" in system_content


def test_build_loop_plan_messages_without_config_workspace_only() -> None:
    """Test build_plan_messages() without config includes WORKSPACE but not ENVIRONMENT."""
    state = LoopState(goal="analyze architecture", thread_id="t1", max_iterations=8)
    ctx = PlanContext(workspace="/abs/path/to/repo")
    builder = PromptBuilder()
    messages = builder.build_plan_messages("analyze architecture", state, ctx)

    assert len(messages) == 1
    system_content = messages[0].content

    # RFC-207: Removed SOOTHE_ prefix from all tags
    assert "<ENVIRONMENT" not in system_content
    assert "<WORKSPACE" in system_content
    assert "/abs/path/to/repo" in system_content
    assert "<WORKSPACE_RULES>" in system_content

    assert "<GOAL_PROGRESS>" in system_content
    assert "Goal: analyze architecture" in system_content


def test_build_loop_plan_messages_omits_workspace_rules_without_workspace() -> None:
    """Test build_plan_messages() omits WORKSPACE_RULES when no workspace."""
    state = LoopState(goal="hi", thread_id="t1", max_iterations=8)
    ctx = PlanContext(workspace=None)
    builder = PromptBuilder()
    messages = builder.build_plan_messages("hi", state, ctx)

    system_content = messages[0].content
    # RFC-207: WORKSPACE_RULES in SystemMessage when workspace present
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
    """Test build_plan_messages() includes prior conversation in HumanMessage."""
    state = LoopState(goal="翻译成中文", thread_id="t1", max_iterations=8)
    # RFC-209: Prior conversation always available (same thread_id)
    ctx = PlanContext(
        workspace=None,
        recent_messages=[
            "<user>\nIran news please\n</user>",
            "<assistant>\n**Infrastructure** … long body …\n</assistant>",
        ],
    )
    builder = PromptBuilder()
    messages = builder.build_plan_messages("翻译成中文", state, ctx)

    system_content = messages[0].content
    human_content = messages[1].content

    # RFC-207: Removed SOOTHE_ prefix from PRIOR_CONVERSATION tag
    # Prior conversation stays on plan-context human; assess goal lines live in system
    assert "<PRIOR_CONVERSATION>" in human_content
    assert "Infrastructure" in human_content
    assert not human_content.strip().startswith("Goal:")
    assert "<GOAL_PROGRESS>" in system_content
    assert "Goal: 翻译成中文" in system_content

    # FOLLOW_UP_POLICY in SystemMessage (static rule)
    assert "<FOLLOW_UP_POLICY>" in system_content


def test_build_loop_plan_messages_plan_continue_when_steps_remain() -> None:
    """Test build_plan_messages() works with current_decision and completed steps."""
    from soothe.core.agent_loop.state.schemas import AgentDecision, StepAction

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
    messages = builder.build_plan_messages("g", state, PlanContext())

    assert len(messages) == 1
    assert isinstance(messages[0], SystemMessage)


def test_build_plan_messages_appends_ledger_loop_messages() -> None:
    """Ledger (execute turns) precedes plan-context human so assess sees history then framing (IG-372)."""
    state = LoopState(goal="read readme", thread_id="t1", max_iterations=8)
    state.loop_messages = [
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
    assert isinstance(messages[1], LoopHumanMessage)
    assert isinstance(messages[2], LoopAIMessage)
    assert messages[1].content.startswith("Execute:")
    assert "First lines of README" in messages[2].content
    system = messages[0].content
    assert "<GOAL_PROGRESS>" in system
    assert "Goal: read readme" in system
    assert "Execute iteration: 1/8" in system
    assert "<AGENTLOOP_HISTORY>" not in system
