"""Pass 1 ``social_response`` salvage and schema helpers for LLM-only intake."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from soothe.foundation.sloop.prompts.identity import GENERIC_CHITCHAT_FALLBACK

from .models import IntakePass1LLMResult

_REASONING_SALVAGE_PATTERNS = (
    re.compile(r"(?i)requested\s+social_response\s*:\s*(.+)$"),
    re.compile(r"(?i)social_response\s*:\s*(.+)$"),
    re.compile(r"(?i)\breply\s*:\s*(.+)$"),
)


class Pass1SocialReplyLLMResult(BaseModel):
    """Structured output for the dedicated Pass 1 social-reply fallback call."""

    social_response: str = Field(
        description="Direct friendly reply to the user's social message",
    )


def pass1_json_schema(*, require_social_response: bool = False) -> dict[str, Any]:
    """Build Pass 1 wire schema with optional ``social_response`` required."""
    schema = dict(IntakePass1LLMResult.model_json_schema())
    required = {"is_task", "confidence", "reasoning"}
    if require_social_response:
        required.add("social_response")
    schema["required"] = sorted(required)
    return schema


def salvage_social_response_from_reasoning(reasoning: str) -> str | None:
    """Extract a user reply mistakenly placed in Pass 1 ``reasoning``."""
    text = reasoning.strip()
    if not text:
        return None
    for pattern in _REASONING_SALVAGE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        candidate = match.group(1).strip().strip("\"'")
        if candidate:
            return candidate
    return None


def coalesce_pass1_dict(result_dict: dict[str, Any]) -> dict[str, Any]:
    """Promote salvaged reply text into ``social_response`` for social verdicts."""
    if result_dict.get("is_task") is True:
        return result_dict
    if (result_dict.get("social_response") or "").strip():
        return result_dict
    salvaged = salvage_social_response_from_reasoning(str(result_dict.get("reasoning") or ""))
    if not salvaged:
        return result_dict
    merged = dict(result_dict)
    merged["social_response"] = salvaged
    return merged


def resolve_pass1_chitchat_response(
    pass1_result: IntakePass1LLMResult,
    *,
    generic_fallback: str = GENERIC_CHITCHAT_FALLBACK,
) -> str:
    """Resolve chitchat text from Pass 1 (salvage + fallback only).

    Identity enforcement runs once at runner emit via ``finalize_chitchat_response``.
    """
    direct = (pass1_result.social_response or "").strip()
    if direct:
        return direct
    salvaged = salvage_social_response_from_reasoning(pass1_result.reasoning or "")
    if salvaged:
        return salvaged
    return generic_fallback


__all__ = [
    "Pass1SocialReplyLLMResult",
    "coalesce_pass1_dict",
    "pass1_json_schema",
    "resolve_pass1_chitchat_response",
    "salvage_social_response_from_reasoning",
]
