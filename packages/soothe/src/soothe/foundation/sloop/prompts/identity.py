"""Unified assistant identity for system prompts and user-facing chitchat replies."""

from __future__ import annotations

import logging
import re

from soothe.foundation.sloop.chitchat_fallbacks import (
    GENERIC_CHITCHAT_FALLBACK,
    GENERIC_CHITCHAT_FALLBACKS,
    pick_generic_chitchat_fallback,
)
from soothe.foundation.sloop.prompts.fragments import ASSISTANT_IDENTITY_FRAGMENT

logger = logging.getLogger(__name__)

_INVENTOR_ATTRIBUTION_EN = "invented by Dr. Xiaming Chen"
_INVENTOR_ATTRIBUTION_ZH = "由 Dr. Xiaming Chen 博士发明"

_WRONG_VENDOR_IDENTITY_MARKERS = re.compile(
    r"(?i)\b("
    r"anthropic|claude|chatgpt|openai|gpt-?\d+|gemini|google\s+ai|"
    r"meta\s+ai|llama|copilot|microsoft\s+copilot|deepseek|qwen"
    r")\b"
)


def normalize_assistant_name(assistant_name: str) -> str:
    """Return a non-empty configured assistant display name."""
    name = (assistant_name or "Soothe").strip()
    return name or "Soothe"


def _normalize_social_kind(social_kind: str | None) -> str:
    if isinstance(social_kind, str) and social_kind.strip():
        return social_kind.strip().lower()
    return "other"


def build_identity_reply(assistant_name: str, query: str) -> str:
    """Build a direct user-facing identity answer for chitchat fast path."""
    name = normalize_assistant_name(assistant_name)
    lowered = query.strip().lower()
    is_origin = (
        "from" in lowered
        or "born" in lowered
        or "come" in lowered
        or "哪" in query
        or "从" in query
    )
    if any("\u4e00" <= ch <= "\u9fff" for ch in query):
        if is_origin:
            return (
                f"我是{name}，{_INVENTOR_ATTRIBUTION_ZH}的云端 AI 助手，"
                "没有实体所在地。有什么我可以帮你的吗？"
            )
        return f"我是{name}，{_INVENTOR_ATTRIBUTION_ZH}的 AI 助手。有什么我可以帮你的吗？"
    if is_origin:
        return (
            f"I'm {name}, a cloud-based AI assistant {_INVENTOR_ATTRIBUTION_EN} — "
            "I don't have a physical location. How can I help you today?"
        )
    return f"I'm {name}, an AI assistant {_INVENTOR_ATTRIBUTION_EN}. How can I help you today?"


def strip_vendor_identity_markers(text: str) -> str:
    """Remove third-party vendor model names from chitchat text."""
    cleaned = _WRONG_VENDOR_IDENTITY_MARKERS.sub("", text)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,.-")
    return cleaned.strip()


def build_assistant_identity_block(assistant_name: str) -> str:
    """Build the cache-stable ``<ASSISTANT_IDENTITY>`` XML block.

    Args:
        assistant_name: Configured assistant display name (e.g. ``Soothe``).

    Returns:
        Formatted identity block (single source of truth for prompt injection).
    """
    name = normalize_assistant_name(assistant_name)
    return ASSISTANT_IDENTITY_FRAGMENT.format(assistant_name=name).strip()


def prepend_assistant_identity(system_body: str, assistant_name: str) -> str:
    """Prepend the canonical identity block to a system prompt body.

    Use for any single-string system message (intake classifiers, social reply,
    ``resolve_system_prompt``). For multi-section prompts (CoreAgent middleware),
    keep the identity block as the first section via ``build_assistant_identity_block``.

    Args:
        system_body: Phase-specific instructions without identity.
        assistant_name: Configured assistant display name.

    Returns:
        Identity block followed by the body.
    """
    identity = build_assistant_identity_block(assistant_name)
    body = system_body.strip()
    if not body:
        return identity
    return f"{identity}\n\n{body}"


def claims_wrong_vendor_identity(response: str) -> bool:
    """Return True when text identifies as a third-party model vendor."""
    return _WRONG_VENDOR_IDENTITY_MARKERS.search(response.strip()) is not None


def finalize_chitchat_response(
    query: str,
    response: str | None,
    *,
    assistant_name: str = "Soothe",
    generic_fallback: str | None = None,
    social_kind: str | None = None,
) -> str:
    """Normalize any user-facing chitchat text to the configured assistant identity.

    Pass 1 ``social_kind`` drives identity enforcement.

    Args:
        query: Original user message.
        response: LLM reply text (may be empty).
        assistant_name: Configured assistant display name.
        generic_fallback: Reply when text is missing for non-identity social turns.
        social_kind: Pass 1 social sub-kind (identity, greeting, etc.).

    Returns:
        User-facing chitchat string.
    """
    name = normalize_assistant_name(assistant_name)
    fallback = generic_fallback or pick_generic_chitchat_fallback(query)
    kind = _normalize_social_kind(social_kind)
    is_identity = kind == "identity"

    text = (response or "").strip()
    if is_identity:
        if not text or claims_wrong_vendor_identity(text):
            if text and claims_wrong_vendor_identity(text):
                logger.info("Chitchat identity reply used wrong vendor identity; applying rewrite")
            return build_identity_reply(name, query)
        return text

    if text and claims_wrong_vendor_identity(text):
        logger.info("Chitchat reply used wrong vendor identity; stripping vendor markers")
        stripped = strip_vendor_identity_markers(text)
        if stripped:
            return stripped
        return fallback
    if text:
        return text
    return fallback


__all__ = [
    "GENERIC_CHITCHAT_FALLBACK",
    "GENERIC_CHITCHAT_FALLBACKS",
    "build_assistant_identity_block",
    "build_identity_reply",
    "claims_wrong_vendor_identity",
    "finalize_chitchat_response",
    "normalize_assistant_name",
    "pick_generic_chitchat_fallback",
    "prepend_assistant_identity",
    "strip_vendor_identity_markers",
]
