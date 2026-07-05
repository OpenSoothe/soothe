"""Runner helpers for Langfuse goal output text (IG-395)."""

from unittest.mock import MagicMock

from soothe.foundation.sloop.orchestrator.runner import _langfuse_goal_output_text
from soothe.foundation.sloop.utils.messages import LoopAIMessage


def test_langfuse_goal_output_text_prefers_goal_completion_ledger() -> None:
    ctx = MagicMock()
    ctx.loop_state.previous_plan = MagicMock(full_output="other")
    ctx.loop_state.loop_messages = [
        LoopAIMessage(content="  from finalize  ", phase="goal_completion", thread_id="t"),
    ]
    assert _langfuse_goal_output_text(ctx) == "from finalize"


def test_langfuse_goal_output_text_falls_back_to_full_output() -> None:
    ctx = MagicMock()
    ctx.loop_state.loop_messages = []
    ctx.loop_state.previous_plan = MagicMock()
    ctx.loop_state.previous_plan.full_output = "plan out"
    ctx.loop_state.previous_plan.next_action = "na"
    assert _langfuse_goal_output_text(ctx) == "plan out"


def test_langfuse_goal_output_text_falls_back_to_next_action() -> None:
    ctx = MagicMock()
    ctx.loop_state.loop_messages = []
    ctx.loop_state.previous_plan = MagicMock()
    ctx.loop_state.previous_plan.full_output = None
    ctx.loop_state.previous_plan.next_action = "max iter msg"
    assert _langfuse_goal_output_text(ctx) == "max iter msg"


def test_langfuse_goal_output_text_ignores_execute_ledger_without_goal_completion() -> None:
    ctx = MagicMock()
    ctx.loop_state.previous_plan = None
    ctx.loop_state.loop_messages = [
        LoopAIMessage(content="wave text", phase="execute_step", thread_id="t"),
    ]
    assert _langfuse_goal_output_text(ctx) == ""


def test_langfuse_goal_output_text_uses_chitchat_intent_response() -> None:
    from soothe.foundation.sloop.intention.models import (
        IntakeLabel,
        IntentClassification,
        TaskComplexity,
    )

    ctx = MagicMock()
    ctx.loop_state.loop_messages = []
    ctx.loop_state.previous_plan = None
    ctx.loop_state.intent = IntentClassification(
        intake_label=IntakeLabel.CHITCHAT,
        chitchat_response="Hi! I'm Soothe.",
        task_complexity=TaskComplexity.MINIMAL,
    )
    assert _langfuse_goal_output_text(ctx) == "Hi! I'm Soothe."
