"""Runner helpers for Langfuse goal output text (IG-395)."""

from unittest.mock import MagicMock

from soothe.core.loop.orchestrator.runner import _langfuse_goal_output_text


def test_langfuse_goal_output_text_prefers_goal_completion() -> None:
    ctx = MagicMock()
    ctx.goal_record = MagicMock()
    ctx.goal_record.goal_completion = "  from finalize  "
    ctx.loop_state.previous_plan = MagicMock(full_output="other")
    ctx.loop_state.last_execute_assistant_text = "x"
    assert _langfuse_goal_output_text(ctx) == "from finalize"


def test_langfuse_goal_output_text_falls_back_to_full_output() -> None:
    ctx = MagicMock()
    ctx.goal_record = MagicMock()
    ctx.goal_record.goal_completion = ""
    ctx.loop_state.previous_plan = MagicMock()
    ctx.loop_state.previous_plan.full_output = "plan out"
    ctx.loop_state.previous_plan.next_action = "na"
    ctx.loop_state.last_execute_assistant_text = None
    assert _langfuse_goal_output_text(ctx) == "plan out"


def test_langfuse_goal_output_text_falls_back_to_next_action() -> None:
    ctx = MagicMock()
    ctx.goal_record = None
    ctx.loop_state.previous_plan = MagicMock()
    ctx.loop_state.previous_plan.full_output = None
    ctx.loop_state.previous_plan.next_action = "max iter msg"
    ctx.loop_state.last_execute_assistant_text = None
    assert _langfuse_goal_output_text(ctx) == "max iter msg"


def test_langfuse_goal_output_text_falls_back_to_last_execute() -> None:
    ctx = MagicMock()
    ctx.goal_record = None
    ctx.loop_state.previous_plan = None
    ctx.loop_state.last_execute_assistant_text = "wave text"
    assert _langfuse_goal_output_text(ctx) == "wave text"
