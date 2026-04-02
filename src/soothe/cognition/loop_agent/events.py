"""Loop agent events for Layer 2 agentic execution."""

from __future__ import annotations

from typing import Literal

from soothe.core.event_catalog import VerbosityTier, register_event
from soothe.foundation.base_events import ProtocolEvent


class LoopAgentJudgmentEvent(ProtocolEvent):
    """Event emitted when loop agent makes a judgment about goal progress.

    This event shows the user the reasoning behind the agent's decision
    to continue, replan, or complete the goal.
    """

    type: Literal["soothe.cognition.loop_agent.judgment"] = "soothe.cognition.loop_agent.judgment"
    status: str  # "done", "replan", "continue"
    progress: float  # 0.0 to 1.0
    confidence: float  # 0.0 to 1.0
    reasoning: str
    iteration: int


# Register the event with NORMAL verbosity (visible to users)
register_event(
    LoopAgentJudgmentEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Judgment: status={status} progress={progress:.0%} confidence={confidence:.0%} - {reasoning}",
)
