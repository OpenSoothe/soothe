"""Origin-aware resume payload builder.

Maps each clarification origin to the correct resume station and builds the
CoreAgent `Command(resume=...)` payload. Uses a controlled-vocabulary mapping
(fail-closed) instead of the legacy token-set heuristic with fail-open default.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from soothe.sloop.clarification.origins import (
    ORIGIN_EXECUTE,
    ORIGIN_TOOL_APPROVAL,
    resume_node_for_clarification_origin,
)
from soothe.sloop.relay.errors import InvalidAnswerSchemaError
from soothe.sloop.relay.store import ClarificationRow
from soothe.sloop.relay.types import CoreAgentResumeSpec

DecisionType = Literal["approve", "reject", "edit"]

_DECISION_SYNONYMS: dict[str, DecisionType] = {
    "approve": "approve",
    "allow": "approve",
    "accept": "approve",
    "proceed": "approve",
    "yes": "approve",
    "y": "approve",
    "reject": "reject",
    "deny": "reject",
    "block": "reject",
    "cancel": "reject",
    "no": "reject",
    "n": "reject",
    "edit": "edit",
    "modify": "edit",
    "revise": "edit",
}


@dataclass(frozen=True)
class ToolApprovalDecision:
    """One HITL decision for a pending tool call.

    Attributes:
        type: `approve`, `reject`, or `edit`.
        message: Optional instructive reject message.
    """

    type: DecisionType
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"type": self.type}
        if self.message is not None:
            d["message"] = self.message
        return d

    @staticmethod
    def from_answer_string(
        answer: str, *, instructive_reason: str | None = None
    ) -> ToolApprovalDecision:
        """Parse a controlled-vocabulary answer string into a decision.

        Raises `InvalidAnswerSchemaError` on unrecognized input (fail-closed).
        """
        token = (answer or "").strip().lower()
        if not token:
            raise InvalidAnswerSchemaError("", "empty tool-approval answer")
        decision_type = _DECISION_SYNONYMS.get(token)
        if decision_type is None:
            try:
                parsed = json.loads(token)
                if isinstance(parsed, dict):
                    raw = str(parsed.get("decision") or parsed.get("type") or "").strip().lower()
                    decision_type = _DECISION_SYNONYMS.get(raw)
            except (json.JSONDecodeError, TypeError):
                pass
        if decision_type is None:
            raise InvalidAnswerSchemaError("", f"unrecognized tool-approval decision: {answer!r}")
        msg = instructive_reason if decision_type == "reject" and instructive_reason else None
        return ToolApprovalDecision(type=decision_type, message=msg)


def resume_station_for_origin(origin: str) -> str:
    """Return the StrangeLoop station that should resume after the answer."""
    node = resume_node_for_clarification_origin(origin)
    return node if node is not None else "END"


def build_core_agent_resume(
    row: ClarificationRow,
    *,
    answers: tuple[str, ...],
    instructive_reason: str | None = None,
) -> CoreAgentResumeSpec | None:
    """Build the CoreAgent `Command(resume=...)` payload for a clarified row.

    Returns `None` for origins that don't resume in-graph (`plan_mode_review`,
    `rail_pause`). Raises `InvalidAnswerSchemaError` for unrecognized
    tool-approval decisions.
    """
    thread_id = row.core_agent_thread_id
    if not thread_id:
        return None

    interrupt_id = row.origin_interrupt_id

    if row.origin == ORIGIN_TOOL_APPROVAL:
        request = row.decode_request()
        action_requests = request.metadata.get("action_requests", [])
        n_pending = (
            len(action_requests)
            if isinstance(action_requests, list) and action_requests
            else len(answers)
            if answers
            else 1
        )
        decisions: list[dict[str, Any]] = []
        for i in range(n_pending):
            ans = answers[i] if i < len(answers) else (answers[0] if answers else "approve")
            decision = ToolApprovalDecision.from_answer_string(
                ans, instructive_reason=instructive_reason
            )
            decisions.append(decision.to_dict())
        payload: dict[str, Any] = {interrupt_id: {"decisions": decisions}}
    elif row.origin == ORIGIN_EXECUTE:
        payload = {interrupt_id: {"answers": list(answers)}}
    else:
        return None

    return CoreAgentResumeSpec(thread_id=thread_id, resume_payload=payload)


__all__ = [
    "DecisionType",
    "ToolApprovalDecision",
    "build_core_agent_resume",
    "resume_station_for_origin",
]
