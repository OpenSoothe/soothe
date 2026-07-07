"""Tests for assistant identity query detection and replies."""

from __future__ import annotations

from soothe.foundation.sloop.chitchat_fallbacks import (
    GENERIC_CHITCHAT_FALLBACK,
    GENERIC_CHITCHAT_FALLBACKS,
    GENERIC_CHITCHAT_FALLBACKS_EN,
    GENERIC_CHITCHAT_FALLBACKS_ZH,
    pick_generic_chitchat_fallback,
)
from soothe.foundation.sloop.prompts.identity import (
    build_identity_reply,
    claims_wrong_vendor_identity,
    finalize_chitchat_response,
    is_identity_query,
    prepend_assistant_identity,
)


def test_is_identity_query_matches_who_are_u() -> None:
    assert is_identity_query("who are u")


def test_is_identity_query_matches_where_are_u_from() -> None:
    assert is_identity_query("where are u from")


def test_is_identity_query_rejects_task() -> None:
    assert not is_identity_query("list files in this directory")


def test_build_identity_reply_english() -> None:
    assert build_identity_reply("Soothe", "who are u") == (
        "I'm Soothe, an AI assistant invented by Dr. Xiaming Chen. How can I help you today?"
    )


def test_build_identity_reply_origin_english() -> None:
    reply = build_identity_reply("Soothe", "where are u from")
    assert "Soothe" in reply
    assert "cloud-based" in reply
    assert "Dr. Xiaming Chen" in reply


def test_build_identity_reply_inventor_english() -> None:
    assert is_identity_query("who invented you")
    reply = build_identity_reply("Soothe", "who invented you")
    assert "invented by Dr. Xiaming Chen" in reply


def test_build_identity_reply_chinese() -> None:
    reply = build_identity_reply("Soothe", "你是谁")
    assert "Soothe" in reply
    assert "Dr. Xiaming Chen" in reply


def test_prepend_assistant_identity_adds_block() -> None:
    prompt = prepend_assistant_identity("<TASK>Do work</TASK>", "Soothe")
    assert prompt.startswith("<ASSISTANT_IDENTITY>")
    assert "<TASK>Do work</TASK>" in prompt


def test_claims_wrong_vendor_identity_detects_claude() -> None:
    assert claims_wrong_vendor_identity("I'm Claude, an AI assistant made by Anthropic.")
    assert not claims_wrong_vendor_identity("I'm doing well, thanks for asking!")


def test_finalize_chitchat_response_overrides_identity_query() -> None:
    reply = finalize_chitchat_response(
        "what is your name",
        "I'm Claude, an AI assistant made by Anthropic. Nice to meet you!",
        assistant_name="Soothe",
    )
    assert "Soothe" in reply
    assert "Dr. Xiaming Chen" in reply
    assert "Claude" not in reply
    assert "Anthropic" not in reply


def test_finalize_chitchat_response_is_idempotent_for_identity_query() -> None:
    first = finalize_chitchat_response("who are u", "I'm Claude", assistant_name="Soothe")
    second = finalize_chitchat_response("who are u", first, assistant_name="Soothe")
    assert first == second


def test_pick_generic_chitchat_fallback_english_pool() -> None:
    for _ in range(20):
        reply = pick_generic_chitchat_fallback("hello")
        assert reply in GENERIC_CHITCHAT_FALLBACKS_EN


def test_pick_generic_chitchat_fallback_chinese_pool() -> None:
    for _ in range(20):
        reply = pick_generic_chitchat_fallback("你好")
        assert reply in GENERIC_CHITCHAT_FALLBACKS_ZH


def test_pick_generic_chitchat_fallback_varies() -> None:
    replies = {pick_generic_chitchat_fallback("hi") for _ in range(30)}
    assert len(replies) > 1


def test_generic_chitchat_fallback_alias() -> None:
    assert GENERIC_CHITCHAT_FALLBACK == GENERIC_CHITCHAT_FALLBACKS_EN[0]
    assert len(GENERIC_CHITCHAT_FALLBACKS) == len(GENERIC_CHITCHAT_FALLBACKS_EN) + len(
        GENERIC_CHITCHAT_FALLBACKS_ZH
    )


def test_finalize_chitchat_response_random_fallback_on_empty() -> None:
    reply = finalize_chitchat_response("thanks", None, assistant_name="Soothe")
    assert reply in GENERIC_CHITCHAT_FALLBACKS_EN


def test_finalize_chitchat_response_random_fallback_on_wrong_vendor() -> None:
    reply = finalize_chitchat_response(
        "how are you",
        "I'm Claude from Anthropic.",
        assistant_name="Soothe",
    )
    assert reply in GENERIC_CHITCHAT_FALLBACKS_EN
