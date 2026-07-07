"""Pass 1 ``social_response`` schema helpers for LLM-only intake."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from soothe.foundation.sloop.chitchat_fallbacks import pick_generic_chitchat_fallback

from .models import IntakePass1LLMResult, IntakePass1SocialKind


class Pass1SocialReplyLLMResult(BaseModel):
    """Structured output for the dedicated Pass 1 social-reply fallback call."""

    social_response: str = Field(
        description="Direct friendly reply to the user's social message",
    )
    social_kind: IntakePass1SocialKind = Field(
        default=IntakePass1SocialKind.OTHER,
        description="Social sub-kind: greeting, thanks, identity, banter, or other",
    )


def pass1_json_schema(*, require_social_response: bool = False) -> dict[str, Any]:
    """Build Pass 1 wire schema with optional ``social_response`` required."""
    schema = dict(IntakePass1LLMResult.model_json_schema())
    required = {"is_task", "confidence", "reasoning", "social_kind"}
    if require_social_response:
        required.add("social_response")
    schema["required"] = sorted(required)
    return schema


def coalesce_pass1_dict(result_dict: dict[str, Any]) -> dict[str, Any]:
    """Normalize Pass 1 dict fields after structured output parsing."""
    merged = dict(result_dict)
    raw_kind = merged.get("social_kind")
    if raw_kind is None or not str(raw_kind).strip():
        merged["social_kind"] = IntakePass1SocialKind.OTHER.value
    return merged


def resolve_pass1_chitchat_response(
    pass1_result: IntakePass1LLMResult,
    *,
    query: str | None = None,
    generic_fallback: str | None = None,
) -> str:
    """Resolve chitchat text from Pass 1 (direct field + generic fallback only).

    Identity enforcement runs once at runner emit via ``finalize_chitchat_response``.
    """
    direct = (pass1_result.social_response or "").strip()
    if direct:
        return direct
    return generic_fallback or pick_generic_chitchat_fallback(query)


__all__ = [
    "Pass1SocialReplyLLMResult",
    "coalesce_pass1_dict",
    "pass1_json_schema",
    "resolve_pass1_chitchat_response",
]
