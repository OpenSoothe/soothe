"""Agent loop events for agentic execution."""

from __future__ import annotations

from typing import Literal

from soothe.core.event_catalog import VerbosityTier, register_event
from soothe.foundation.base_events import ProtocolEvent


class LoopAgentReasonEvent(ProtocolEvent):
    """User-visible progress after the Reason phase (ReAct loop)."""

    type: Literal["soothe.cognition.agent_loop.reason"] = "soothe.cognition.agent_loop.reason"
    status: str
    progress: float
    confidence: float
    next_action: str
    reasoning: str  # Internal technical analysis (max 500 chars)
    iteration: int


register_event(
    LoopAgentReasonEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="{next_action}",
)
