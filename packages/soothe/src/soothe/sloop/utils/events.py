"""Strange loop events for agentic execution."""

from __future__ import annotations

from typing import Literal

from soothe_sdk.core.events import ProtocolEvent

from soothe.events import VerbosityTier, register_event


class LoopAgentReasonEvent(ProtocolEvent):
    """User-visible cognition progress (assess cards, step completion summaries)."""

    type: Literal["soothe.cognition.strange_loop.reasoned"] = (
        "soothe.cognition.strange_loop.reasoned"
    )
    status: str
    progress: str
    assessment_reasoning: str = ""
    plan_reasoning: str = ""  # step-completion / strategy line; not plan-generate
    plan_action: Literal["keep", "new", ""] = "new"
    iteration: int


register_event(
    LoopAgentReasonEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="{assessment_reasoning}",
)
