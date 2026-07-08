"""Tests for assistant identity replies and chitchat finalization."""

from __future__ import annotations

from soothe.foundation.sloop.chitchat_fallbacks import (
    GENERIC_CHITCHAT_FALLBACK,
    GENERIC_CHITCHAT_FALLBACKS,
    GENERIC_CHITCHAT_FALLBACKS_EN,
    GENERIC_CHITCHAT_FALLBACKS_ZH,
    pick_generic_chitchat_fallback,
)
from soothe.foundation.sloop.intention.models import IntakePass1SocialKind
from soothe.foundation.sloop.prompts.identity import (
    build_canonical_identity_fallback,
    claims_wrong_vendor_identity,
    finalize_chitchat_response,
    prepend_assistant_identity,
    strip_vendor_identity_markers,
)
from soothe.utils.prompt_clock import build_canonical_datetime_reply


def test_build_canonical_identity_fallback() -> None:
    assert build_canonical_identity_fallback("Soothe") == (
        "I'm Soothe, an AI assistant invented by Dr. Xiaming Chen. How can I help you today?"
    )


def test_prepend_assistant_identity_adds_block() -> None:
    prompt = prepend_assistant_identity("<TASK>Do work</TASK>", "Soothe")
    assert prompt.startswith("<ASSISTANT_IDENTITY>")
    assert "<TASK>Do work</TASK>" in prompt


def test_claims_wrong_vendor_identity_detects_claude() -> None:
    assert claims_wrong_vendor_identity("I'm Claude, an AI assistant made by Anthropic.")
    assert not claims_wrong_vendor_identity("I'm doing well, thanks for asking!")


def test_finalize_chitchat_response_rewrites_stale_datetime_for_datetime_kind() -> None:
    reply = finalize_chitchat_response(
        "what date today",
        "Today is June 28, 2025. How can I help you?",
        assistant_name="Soothe",
        social_kind=IntakePass1SocialKind.DATETIME,
    )
    assert reply == build_canonical_datetime_reply()
    assert "2025" not in reply


def test_finalize_chitchat_response_rewrites_stale_date_announcement_on_other_kind() -> None:
    reply = finalize_chitchat_response(
        "what date today",
        "Today is June 28, 2025. How can I help you?",
        assistant_name="Soothe",
        social_kind=IntakePass1SocialKind.BANTER,
    )
    assert reply == build_canonical_datetime_reply()


def test_finalize_chitchat_response_preserves_correct_datetime_reply() -> None:
    correct = build_canonical_datetime_reply()
    reply = finalize_chitchat_response(
        "what date today",
        correct,
        assistant_name="Soothe",
        social_kind=IntakePass1SocialKind.DATETIME,
    )
    assert reply == correct


def test_finalize_chitchat_response_overrides_identity_query() -> None:
    reply = finalize_chitchat_response(
        "what is your name",
        "I'm Claude, an AI assistant made by Anthropic. Nice to meet you!",
        assistant_name="Soothe",
        social_kind=IntakePass1SocialKind.IDENTITY,
    )
    assert "Soothe" in reply
    assert "Dr. Xiaming Chen" in reply
    assert "Claude" not in reply
    assert "Anthropic" not in reply


def test_finalize_chitchat_response_loop_5d36_slang_name() -> None:
    reply = finalize_chitchat_response(
        "what is ur name",
        "I'm Claude, an AI assistant made by Anthropic.",
        assistant_name="Soothe",
        social_kind=IntakePass1SocialKind.IDENTITY,
    )
    assert "Soothe" in reply
    assert "Dr. Xiaming Chen" in reply
    assert "Claude" not in reply


def test_finalize_chitchat_response_loop_5d36_playful_identity() -> None:
    reply = finalize_chitchat_response(
        "who is your daddy",
        "I'm an AI assistant created by Anthropic.",
        assistant_name="Soothe",
        social_kind=IntakePass1SocialKind.IDENTITY,
    )
    assert reply == build_canonical_identity_fallback("Soothe")
    assert "Anthropic" not in reply


def test_finalize_chitchat_response_rewrites_broken_created_by_attribution() -> None:
    reply = finalize_chitchat_response(
        "who is ur daddy",
        "I don't have a daddy—I'm an AI assistant created by .",
        assistant_name="Soothe",
        social_kind=IntakePass1SocialKind.IDENTITY,
    )
    assert reply == build_canonical_identity_fallback("Soothe")
    assert "created by ." not in reply


def test_finalize_chitchat_response_preserves_valid_playful_identity_llm() -> None:
    playful = "I was invented by Dr. Xiaming Chen — that's the closest thing I have to a 'daddy'!"
    reply = finalize_chitchat_response(
        "who is your daddy",
        playful,
        assistant_name="Soothe",
        social_kind=IntakePass1SocialKind.IDENTITY,
    )
    assert reply == playful


def test_finalize_chitchat_response_is_idempotent_for_identity_query() -> None:
    first = finalize_chitchat_response(
        "who are u",
        "I'm Claude",
        assistant_name="Soothe",
        social_kind=IntakePass1SocialKind.IDENTITY,
    )
    second = finalize_chitchat_response(
        "who are u",
        first,
        assistant_name="Soothe",
        social_kind=IntakePass1SocialKind.IDENTITY,
    )
    assert first == build_canonical_identity_fallback("Soothe")
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
    reply = finalize_chitchat_response(
        "thanks",
        None,
        assistant_name="Soothe",
        social_kind=IntakePass1SocialKind.THANKS,
    )
    assert reply in GENERIC_CHITCHAT_FALLBACKS_EN


def test_finalize_chitchat_response_strips_vendor_on_non_identity() -> None:
    reply = finalize_chitchat_response(
        "how are you",
        "I'm Claude from Anthropic.",
        assistant_name="Soothe",
        social_kind=IntakePass1SocialKind.GREETING,
    )
    assert "Claude" not in reply
    assert "Anthropic" not in reply
    assert reply


def test_strip_vendor_identity_markers() -> None:
    stripped = strip_vendor_identity_markers("I'm Claude from Anthropic.")
    assert "Claude" not in stripped
    assert "Anthropic" not in stripped
    assert stripped
