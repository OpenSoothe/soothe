"""Loop agent events for Layer 2 agentic execution."""

from __future__ import annotations

from typing import Literal

from soothe.core.event_catalog import VerbosityTier, register_event
from soothe.foundation.base_events import ProtocolEvent


class LoopAgentReasonEvent(ProtocolEvent):
    """User-visible progress after the Reason phase (ReAct Layer 2)."""

    type: Literal["soothe.cognition.loop_agent.reason"] = "soothe.cognition.loop_agent.reason"
    status: str
    progress: float
    confidence: float
    soothe_next_action: str
    progress_detail: str | None
    iteration: int


register_event(
    LoopAgentReasonEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="{soothe_next_action}",
)
