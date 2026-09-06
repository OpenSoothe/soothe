"""Resume command builders (StrangeLoop → CoreAgent).

Single resume translator for every clarification origin. Adding a new origin
means editing this module only, not the executor capture site. The
`GraphStreamChunkReader` and `DispatchTimeoutError` stay in
`engine/execute/graph_interrupt.py` (stream mechanics, not relay mechanics).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from soothe.sloop.clarification.origins import ORIGIN_TOOL_APPROVAL

if TYPE_CHECKING:
    from soothe.sloop.clarification.protocol import (
        ClarificationAnswer,
        ClarificationRequest,
    )

_APPROVE_TOKENS = frozenset({"approve", "yes", "ok", "allow", "accept", "proceed", "y"})
_REJECT_TOKENS = frozenset({"reject", "no", "deny", "block", "cancel", "n"})
_EDIT_TOKENS = frozenset({"edit", "modify", "change", "revise"})


def is_ask_user_interrupt(value: Any) -> bool:
    """Return True if `value` is a structured `ask_user` interrupt payload."""
    return isinstance(value, Mapping) and value.get("type") == "ask_user"


def is_tool_approval_interrupt(value: Any) -> bool:
    """Return True if `value` is a deepagents `action_requests` interrupt.

    Emitted by `HumanInTheLoopMiddleware` when a tool call matches an
    `interrupt_on` rule. Captured into the relay (`tool_approval` origin) and
    resolved by the multi-stage pipeline or veritas fallback — never
    auto-approved silently.
    """
    return isinstance(value, Mapping) and "action_requests" in value


def answer_to_decision(answer: str) -> str:
    """Map a tool-approval answer string to a HITL `DecisionType`.

    The relay answers with a free-form string (from veritas or the TUI). The
    deepagents middleware expects `"approve"` / `"edit"` / `"reject"`. Defaults
    to `"approve"` for unrecognized positive-ish answers and `"reject"` only
    on an explicit reject token.
    """
    token = (answer or "").strip().lower()
    if token in _REJECT_TOKENS:
        return "reject"
    if token in _EDIT_TOKENS:
        return "edit"
    return "approve"


def build_tool_approval_resume_payload(
    interrupt_id: str,
    *,
    decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the resume payload for a tool-approval interrupt.

    Translates the relay's answer (approve/reject/edit per action request)
    into the `{"decisions": [...]}` shape the deepagents
    `HumanInTheLoopMiddleware` expects on `Command(resume=...)`.
    """
    return {interrupt_id: {"decisions": decisions}}


def build_auto_resume_payload(pending_interrupts: Mapping[str, Any]) -> dict[str, Any]:
    """Build a `Command(resume=...)` payload for residual non-clarification interrupts.

    `ask_user` and `action_requests` interrupts are captured by the relay
    before this runs; they never reach `pending_interrupts`. This auto-approves
    any other interrupt type (typically deepagents middleware interrupts
    unrelated to clarification).
    """
    payload: dict[str, Any] = {}
    for iid, value in pending_interrupts.items():
        if is_ask_user_interrupt(value) or is_tool_approval_interrupt(value):
            continue
        payload[iid] = {"decisions": [{"type": "approve"}]}
    return payload


def build_clarification_resume_payload(
    request: ClarificationRequest,
    answer: ClarificationAnswer,
) -> dict[str, Any]:
    """Build the `Command(resume=...)` payload for a clarified interrupt.

    - `tool_approval` — map the relay's answer to a HITL `decisions` shape. One
      decision per pending action request; the decisions list length must
      match the number of hanging tool calls. When the answer has fewer
      entries, remaining slots default to the first answer (or `"approve"`).
    - otherwise (`ask_user` / execute) — deliver answers verbatim so the
      `ask_user` tool returns the Q&A and the agent continues its turn.

    Instructive rejects (audit `instructive: True`) attach the safety `reason`
    as a `message` on each reject decision so the model's `ToolMessage`
    explains why the call was blocked.
    """
    if request.origin_node == ORIGIN_TOOL_APPROVAL:
        action_requests = request.metadata.get("action_requests", [])
        n_pending = (
            len(action_requests) if isinstance(action_requests, list) and action_requests else 0
        )
        answers = list(answer.answers) if answer.answers else ["approve"]
        if n_pending == 0:
            n_pending = len(answers) if answers else 1
        audit = answer.audit if isinstance(answer.audit, dict) else {}
        instructive_reason: str | None = None
        if audit.get("instructive"):
            instructive_reason = str(audit.get("reason") or "").strip() or None
        decisions: list[dict[str, Any]] = []
        for i in range(n_pending):
            ans = answers[i] if i < len(answers) else answers[0]
            decision_type = answer_to_decision(ans)
            decision: dict[str, Any] = {"type": decision_type}
            if decision_type == "reject" and instructive_reason is not None:
                decision["message"] = instructive_reason
            decisions.append(decision)
        return build_tool_approval_resume_payload(
            request.origin_interrupt_id,
            decisions=decisions,
        )
    return {request.origin_interrupt_id: {"answers": list(answer.answers)}}


__all__ = [
    "answer_to_decision",
    "build_auto_resume_payload",
    "build_clarification_resume_payload",
    "build_tool_approval_resume_payload",
    "is_ask_user_interrupt",
    "is_tool_approval_interrupt",
]
