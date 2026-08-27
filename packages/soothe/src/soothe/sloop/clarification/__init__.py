"""Clarification relay for the Agent Loop (RFC-622).

When CoreAgent emits a structured ``ask_user`` interrupt, the loop bubbles the
question up through a :class:`ClarificationPolicy` that returns a real answer
(from a human via the TUI, or from the ``veritas`` subagent in autonomous mode).
The loop then resumes CoreAgent with the answer instead of the empty-string
fallback that previously caused replan spins. Plain-text questions are not
treated as clarifications.
"""

from __future__ import annotations

from soothe.sloop.clarification.auto import AutoClarificationPolicy
from soothe.sloop.clarification.capture import ClarificationCapture, ResumeTicket
from soothe.sloop.clarification.detector import ClarificationDetector
from soothe.sloop.clarification.interactive import InteractiveClarificationPolicy
from soothe.sloop.clarification.origins import (
    CLARIFICATION_ORIGIN_RESUME_NODE,
    CLARIFICATION_ORIGINS,
    DEFAULT_FORCE_MANUAL_ORIGINS,
    ORIGIN_EXECUTE,
    ORIGIN_PLAN_MODE_REVIEW,
    ORIGIN_RAIL_PAUSE,
    ORIGIN_TOOL_APPROVAL,
    PLAN_MODE_REVIEW_INTERRUPT_PREFIX,
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
from soothe.sloop.clarification.tool_approval_pipeline import (
    ApprovalResult,
    ToolApprovalPipeline,
)
from soothe.sloop.clarification.tool_rule_matcher import (
    match_command_rule,
    match_path_rule,
)
from soothe.sloop.clarification.tool_safety_check import (
    SafetyResult,
    check_command_safety,
    check_path_safety,
)

__all__ = [
    "ApprovalResult",
    "AutoClarificationPolicy",
    "CLARIFICATION_ORIGINS",
    "CLARIFICATION_ORIGIN_RESUME_NODE",
    "ClarificationAnswer",
    "ClarificationCapture",
    "ResumeTicket",
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
    "ORIGIN_PLAN_MODE_REVIEW",
    "ORIGIN_RAIL_PAUSE",
    "ORIGIN_TOOL_APPROVAL",
    "PLAN_MODE_REVIEW_INTERRUPT_PREFIX",
    "SafetyResult",
    "ToolApprovalPipeline",
    "answer_from_state",
    "answer_to_state",
    "bind_clarification_emit",
    "build_clarification_policy_for_runner",
    "build_default_clarification_policy",
    "check_command_safety",
    "check_path_safety",
    "match_command_rule",
    "match_path_rule",
    "request_from_state",
    "request_to_state",
    "resolve_clarification_mode",
    "resume_node_for_clarification_origin",
]
