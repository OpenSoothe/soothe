"""Strange loop events for agentic execution."""

from __future__ import annotations

from typing import Literal

from soothe_sdk.core.events import ProtocolEvent

from soothe.foundation.events import VerbosityTier, register_event


class LoopAgentReasonEvent(ProtocolEvent):
    """User-visible progress after the Plan phase (Plan-Execute loop)."""

    type: Literal["soothe.cognition.strange_loop.reasoned"] = (
        "soothe.cognition.strange_loop.reasoned"
    )
    status: str
    progress: str
    next_action: str
    assessment_reasoning: str = ""
    plan_reasoning: str = ""
    plan_action: Literal["keep", "new", ""] = "new"
    iteration: int


register_event(
    LoopAgentReasonEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="{assessment_reasoning}",
)
