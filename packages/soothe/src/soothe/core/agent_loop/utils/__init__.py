"""Utility modules for agent loop.

Provides plan parsing, JSON utilities, reflection logic, and helper components.
"""

from .communication import GoalCommunicationHelper
from .events import LoopAgentReasonEvent
from .json_parsing import _load_llm_json_dict
from .messages import LoopHumanMessage
from .plan_parsing import parse_plan_from_text
from .reflection import (
    _default_agent_decision,
    reflect_heuristic,
    reflect_with_llm,
)
from .stream_normalize import (
    GoalCompletionAccumState,
    iter_messages_for_act_aggregation,
    resolve_goal_completion_text,
    update_goal_completion_from_message,
)

__all__ = [
    "parse_plan_from_text",
    "_load_llm_json_dict",
    "reflect_heuristic",
    "reflect_with_llm",
    "_default_agent_decision",
    "GoalCommunicationHelper",
    "LoopHumanMessage",
    "LoopAgentReasonEvent",
    "GoalCompletionAccumState",
    "iter_messages_for_act_aggregation",
    "resolve_goal_completion_text",
    "update_goal_completion_from_message",
]
