"""Clarification relay for the Agent Loop (RFC-622).

When CoreAgent emits an ``ask_user`` interrupt (or ends a turn with a plain-text
question), the loop bubbles the question up through a :class:`ClarificationPolicy`
that returns a real answer (from a human via the TUI, or from the ``veritas``
subagent in autonomous mode). The loop then resumes CoreAgent with the answer
instead of the empty-string fallback that previously caused replan spins.
"""

from __future__ import annotations

from soothe.core.loop.clarification.auto import AutoClarificationPolicy
from soothe.core.loop.clarification.capture import ClarificationCapture
from soothe.core.loop.clarification.detector import ClarificationDetector
from soothe.core.loop.clarification.interactive import InteractiveClarificationPolicy
from soothe.core.loop.clarification.protocol import (
    ClarificationAnswer,
    ClarificationDeferredError,
    ClarificationOrigin,
    ClarificationPolicy,
    ClarificationRequest,
    LoopStateView,
    answer_from_state,
    answer_to_state,
    request_from_state,
    request_to_state,
)
from soothe.core.loop.clarification.selector import build_default_clarification_policy

__all__ = [
    "AutoClarificationPolicy",
    "ClarificationAnswer",
    "ClarificationCapture",
    "ClarificationDeferredError",
    "ClarificationDetector",
    "ClarificationOrigin",
    "ClarificationPolicy",
    "ClarificationRequest",
    "InteractiveClarificationPolicy",
    "LoopStateView",
    "answer_from_state",
    "answer_to_state",
    "build_default_clarification_policy",
    "request_from_state",
    "request_to_state",
]
