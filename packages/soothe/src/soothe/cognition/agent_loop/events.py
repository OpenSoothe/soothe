"""Agent loop events for agentic execution."""

from __future__ import annotations

from typing import Literal

from soothe_sdk.core.events import ProtocolEvent

from soothe.core.event_catalog import VerbosityTier, register_event


class LoopAgentReasonEvent(ProtocolEvent):
    """User-visible progress after the Plan phase (Plan-Execute loop)."""

    type: Literal["soothe.cognition.agent_loop.reasoned"] = "soothe.cognition.agent_loop.reasoned"
    status: str
    progress: float
    confidence: float
    next_action: str
    reasoning: str  # Combined assessment + plan chain (backward compatible)
    assessment_reasoning: str = ""
    plan_reasoning: str = ""
    plan_action: Literal["keep", "new"] = "new"
    iteration: int


register_event(
    LoopAgentReasonEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="{next_action}",
)
