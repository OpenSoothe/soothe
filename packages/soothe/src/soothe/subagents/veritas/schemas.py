"""Structured-output schema for veritas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class VeritasAnswerSchema(BaseModel):
    """Veritas's answer to a clarification request."""

    answers: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    defer: bool = False
    rationale: str = ""
    reasoning: str = ""
    answer_is_question: list[bool] = Field(default_factory=list)


def coerce_veritas_response(
    data: dict[str, Any],
    question_count: int,
    *,
    coerced_confidence: float = 0.7,
) -> dict[str, Any]:
    """Fill missing metadata when the model returns answers-only JSON."""
    if not isinstance(data, dict):
        return data
    out = dict(data)
    answers = out.get("answers")
    if not isinstance(answers, list) or len(answers) != question_count:
        return out
    if not all(isinstance(a, str) and a.strip() for a in answers):
        return out
    if out.get("defer") is True:
        return out
    if out.get("defer") is None:
        out["defer"] = False
    if out.get("confidence") is None:
        out["confidence"] = coerced_confidence
    rationale = out.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        out["rationale"] = "auto-coerced from answers-only response"
    # Fill answer_is_question default when the model omits it (transitional).
    aiq = out.get("answer_is_question")
    if not isinstance(aiq, list) or len(aiq) != question_count:
        out["answer_is_question"] = [False] * question_count
    # Fill reasoning default when the model omits it.
    reasoning = out.get("reasoning")
    if not isinstance(reasoning, str) or not reasoning.strip():
        out["reasoning"] = ""
    return out


def build_veritas_response_schema(question_count: int) -> dict[str, Any]:
    """Return the per-request JSON Schema veritas sends to the LLM."""
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
            "reasoning": {"type": "string"},
            "answer_is_question": {
                "type": "array",
                "items": {"type": "boolean"},
            },
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
                    "answer_is_question": {
                        "type": "array",
                        "minItems": question_count,
                        "maxItems": question_count,
                        "items": {"type": "boolean"},
                    },
                },
                "required": ["answers", "answer_is_question"],
            },
        ],
    }


__all__ = ["VeritasAnswerSchema", "build_veritas_response_schema", "coerce_veritas_response"]
