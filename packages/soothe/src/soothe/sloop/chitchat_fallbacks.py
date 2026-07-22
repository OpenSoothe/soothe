"""Randomized generic chitchat fallbacks when LLM social replies are missing."""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from soothe.sloop.intention.models import ResponseLanguage

GENERIC_CHITCHAT_FALLBACKS_EN: tuple[str, ...] = (
    "Hello! How can I help you today?",
    "Hi there! What would you like to work on?",
    "Hey! Ready when you are — what's on your mind?",
    "Good to hear from you. How can I assist?",
    "Hello! Let me know if there's anything I can help with.",
    "Hi! What can I do for you today?",
)

GENERIC_CHITCHAT_FALLBACKS_ZH: tuple[str, ...] = (
    "你好！有什么我可以帮你的吗？",
    "嗨！今天想聊点什么？",
    "你好，有需要帮忙的吗？",
    "我在，有什么可以帮到你？",
    "你好！随时告诉我你需要什么。",
)


def pick_generic_chitchat_fallback(language: ResponseLanguage | None = None) -> str:
    """Return a random friendly chitchat fallback for the detected response language."""
    from soothe.sloop.intention.models import ResponseLanguage

    if language == ResponseLanguage.ZH:
        pool = GENERIC_CHITCHAT_FALLBACKS_ZH
    else:
        pool = GENERIC_CHITCHAT_FALLBACKS_EN
    return random.choice(pool)


__all__ = [
    "GENERIC_CHITCHAT_FALLBACKS_EN",
    "GENERIC_CHITCHAT_FALLBACKS_ZH",
    "pick_generic_chitchat_fallback",
]
