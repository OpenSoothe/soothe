"""Utility modules for agent loop.

Provides JSON utilities, reflection logic, and helper components.
"""

from .events import LoopAgentReasonEvent
from .json_parsing import _load_llm_json_dict
from .messages import LoopHumanMessage
from .reflection import _default_agent_decision
from .stream_normalize import (
    GoalCompletionAccumState,
    iter_messages_for_act_aggregation,
    resolve_goal_completion_text,
    update_goal_completion_from_message,
)

__all__ = [
    "_load_llm_json_dict",
    "_default_agent_decision",
    "LoopHumanMessage",
    "LoopAgentReasonEvent",
    "GoalCompletionAccumState",
    "iter_messages_for_act_aggregation",
    "resolve_goal_completion_text",
    "update_goal_completion_from_message",
]
