"""Structured-output schema for veritas (RFC-622)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class VeritasAnswerSchema(BaseModel):
    """Veritas's answer to a clarification request.

    Args:
        answers: One answer per question in the originating request, in order.
        confidence: 0.0-1.0 self-assessed confidence. The auto policy treats
            values below ``agent.clarification.auto_min_confidence`` as defer.
        defer: When ``True``, veritas is explicitly signaling "ask a human".
            The auto policy translates this into a ``ClarificationDeferredError``
            and the loop transitions to ``awaiting_clarification``.
        rationale: Short explanation for the audit trail.
    """

    answers: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    defer: bool = False
    rationale: str = ""
