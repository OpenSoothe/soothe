"""Structured-output schema for veritas (RFC-622, RFC-623)."""

from __future__ import annotations

from typing import Any

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
        rationale: Short explanation for the audit trail. RFC-623 attaches a
            structured prefix (``structured_output_failed: ...``) or marker
            (``answer_was_question``) when veritas itself coerced the result;
            ``AutoClarificationPolicy`` reads these to populate ``DeferKind``.
    """

    answers: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    defer: bool = False
    rationale: str = ""


def build_veritas_response_schema(question_count: int) -> dict[str, Any]:
    """Return the per-request JSON Schema veritas sends to the LLM (RFC-623).

    The schema enforces *exactly N non-empty answers OR defer* via ``oneOf``
    so that empty-but-not-deferred and wrong-count responses are rejected at
    the structured-output boundary instead of being caught by a post-hoc
    Python guard.

    Args:
        question_count: Number of questions in the originating request. Must
            be a positive integer; the schema is undefined for zero questions.

    Returns:
        A JSON Schema dict suitable for ``invoke_structured_chat``.

    Raises:
        ValueError: If ``question_count`` is less than 1.
    """
    if question_count < 1:
        msg = f"question_count must be >= 1, got {question_count}"
        raise ValueError(msg)
    return {
        "type": "object",
        "title": "VeritasAnswer",
        "required": ["defer", "confidence", "rationale"],
        "properties": {
            "defer": {"type": "boolean"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "rationale": {"type": "string", "minLength": 1},
            "answers": {"type": "array", "items": {"type": "string"}},
        },
        "oneOf": [
            {"properties": {"defer": {"const": True}}},
            {
                "properties": {
                    "defer": {"const": False},
                    "answers": {
                        "type": "array",
                        "minItems": question_count,
                        "maxItems": question_count,
                        "items": {"type": "string", "minLength": 1},
                    },
                },
                "required": ["answers"],
            },
        ],
    }


__all__ = ["VeritasAnswerSchema", "build_veritas_response_schema"]
