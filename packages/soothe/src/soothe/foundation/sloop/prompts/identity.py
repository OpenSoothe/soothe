"""Unified assistant identity block for all system prompts."""

from __future__ import annotations

import re

from soothe.foundation.sloop.prompts.fragments import ASSISTANT_IDENTITY_FRAGMENT

_INVENTOR_ATTRIBUTION_EN = "invented by Dr. Xiaming Chen"
_INVENTOR_ATTRIBUTION_ZH = "由 Dr. Xiaming Chen 博士发明"

_IDENTITY_QUERY_MARKERS = re.compile(
    r"^(?:"
    r"who\s+are\s+(?:you|u)|"
    r"what\s+are\s+(?:you|u)|"
    r"what(?:'s|\s+is)\s+your\s+name|"
    r"what\s+do\s+(?:you|u)\s+call\s+(?:yourself|yourselves)|"
    r"introduce\s+(?:yourself|yourselves)|"
    r"where\s+are\s+(?:you|u)\s+from|"
    r"where\s+do\s+(?:you|u)\s+come\s+from|"
    r"where\s+(?:were\s+)?(?:you|u)\s+born|"
    r"who\s+(?:invented|created|made|built|developed)\s+(?:you|u)|"
    r"who\s+is\s+your\s+(?:creator|inventor|author|developer|maker)|"
    r"你\s*是\s*谁|你是谁|介绍一下\s*你|你\s*叫\s*什么|"
    r"你\s*从\s*哪\s*来|你\s*是\s*哪\s*里\s*人|"
    r"谁\s*(?:发明|创造|开发|设计|做)\s*了?\s*(?:你|您)|"
    r"你的\s*(?:发明者|创造者|开发者|作者)\s*是\s*谁"
    r")[!.?\s]*$",
    re.IGNORECASE,
)


def normalize_assistant_name(assistant_name: str) -> str:
    """Return a non-empty configured assistant display name."""
    name = (assistant_name or "Soothe").strip()
    return name or "Soothe"


def is_identity_query(query: str) -> bool:
    """Return True when the user is asking who the assistant is."""
    text = query.strip()
    if not text:
        return False
    return _IDENTITY_QUERY_MARKERS.match(text) is not None


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


def build_assistant_identity_block(assistant_name: str) -> str:
    """Build the cache-stable assistant identity block prepended to system prompts.

    Used by ``SystemPromptMiddleware`` (CoreAgent) and intake classification
    so identity/self-description rules stay consistent across paths.

    Args:
        assistant_name: Configured assistant display name (e.g. ``Soothe``).

    Returns:
        Formatted ``<ASSISTANT_IDENTITY>`` XML block.
    """
    name = normalize_assistant_name(assistant_name)
    return ASSISTANT_IDENTITY_FRAGMENT.format(assistant_name=name).strip()


__all__ = [
    "build_assistant_identity_block",
    "build_identity_reply",
    "is_identity_query",
    "normalize_assistant_name",
]
