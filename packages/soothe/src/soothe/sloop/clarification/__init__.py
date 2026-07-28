"""Clarification relay for the Agent Loop (RFC-622).

When CoreAgent emits an ``ask_user`` interrupt (or ends a turn with a plain-text
question), the loop bubbles the question up through a :class:`ClarificationPolicy`
that returns a real answer (from a human via the TUI, or from the ``veritas``
subagent in autonomous mode). The loop then resumes CoreAgent with the answer
instead of the empty-string fallback that previously caused replan spins.
"""

from __future__ import annotations

from soothe.sloop.clarification.auto import AutoClarificationPolicy
from soothe.sloop.clarification.capture import ClarificationCapture
from soothe.sloop.clarification.detector import ClarificationDetector
from soothe.sloop.clarification.interactive import InteractiveClarificationPolicy
from soothe.sloop.clarification.origins import (
    CLARIFICATION_ORIGIN_RESUME_NODE,
    CLARIFICATION_ORIGINS,
    DEFAULT_FORCE_MANUAL_ORIGINS,
    ORIGIN_EXECUTE,
    ORIGIN_PLAN_ASSESS,
    ORIGIN_PLAN_GAP_ANALYSIS,
    ORIGIN_PLAN_GENERATE,
    ORIGIN_PLANNER_SUBAGENT_REVIEW,
    PLANNER_SUBAGENT_REVIEW_INTERRUPT_PREFIX,
    PLANNER_WIRE_SUBAGENT,
    STRANGELOOP_PLANNING_ORIGINS,
    resume_node_for_clarification_origin,
)
from soothe.sloop.clarification.protocol import (
    ClarificationAnswer,
    ClarificationDeferredError,
    ClarificationOrigin,
    ClarificationPolicy,
    ClarificationRequest,
    DeferKind,
    LoopStateView,
    answer_from_state,
    answer_to_state,
    request_from_state,
    request_to_state,
)
from soothe.sloop.clarification.runtime_factory import (
    bind_clarification_emit,
    build_clarification_policy_for_runner,
    resolve_clarification_mode,
)
from soothe.sloop.clarification.selector import build_default_clarification_policy

__all__ = [
    "AutoClarificationPolicy",
    "CLARIFICATION_ORIGINS",
    "CLARIFICATION_ORIGIN_RESUME_NODE",
    "ClarificationAnswer",
    "ClarificationCapture",
    "ClarificationDeferredError",
    "ClarificationDetector",
    "ClarificationOrigin",
    "ClarificationPolicy",
    "ClarificationRequest",
    "DEFAULT_FORCE_MANUAL_ORIGINS",
    "DeferKind",
    "InteractiveClarificationPolicy",
    "LoopStateView",
    "ORIGIN_EXECUTE",
    "ORIGIN_PLAN_ASSESS",
    "ORIGIN_PLAN_GAP_ANALYSIS",
    "ORIGIN_PLAN_GENERATE",
    "ORIGIN_PLANNER_SUBAGENT_REVIEW",
    "PLANNER_SUBAGENT_REVIEW_INTERRUPT_PREFIX",
    "PLANNER_WIRE_SUBAGENT",
    "STRANGELOOP_PLANNING_ORIGINS",
    "answer_from_state",
    "answer_to_state",
    "bind_clarification_emit",
    "build_clarification_policy_for_runner",
    "build_default_clarification_policy",
    "request_from_state",
    "request_to_state",
    "resolve_clarification_mode",
    "resume_node_for_clarification_origin",
]
