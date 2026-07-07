"""Randomized generic chitchat fallbacks when LLM social replies are missing."""

from __future__ import annotations

import random

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

GENERIC_CHITCHAT_FALLBACKS: tuple[str, ...] = (
    *GENERIC_CHITCHAT_FALLBACKS_EN,
    *GENERIC_CHITCHAT_FALLBACKS_ZH,
)

# Backward-compatible default (first English fallback).
GENERIC_CHITCHAT_FALLBACK = GENERIC_CHITCHAT_FALLBACKS_EN[0]


def query_prefers_chinese(query: str | None) -> bool:
    """Return True when the user message contains Chinese characters."""
    if not query:
        return False
    return any("\u4e00" <= ch <= "\u9fff" for ch in query)


def pick_generic_chitchat_fallback(query: str | None = None) -> str:
    """Return a random friendly chitchat fallback matched to query language."""
    pool = (
        GENERIC_CHITCHAT_FALLBACKS_ZH
        if query_prefers_chinese(query)
        else GENERIC_CHITCHAT_FALLBACKS_EN
    )
    return random.choice(pool)


__all__ = [
    "GENERIC_CHITCHAT_FALLBACK",
    "GENERIC_CHITCHAT_FALLBACKS",
    "GENERIC_CHITCHAT_FALLBACKS_EN",
    "GENERIC_CHITCHAT_FALLBACKS_ZH",
    "pick_generic_chitchat_fallback",
    "query_prefers_chinese",
]
