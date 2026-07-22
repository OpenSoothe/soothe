"""Tests for dynamic response-language hint builder."""

from soothe.prompts.system_templates import (
    RESPONSE_LANGUAGE_HINT_FALLBACK,
    build_response_language_hint,
)
from soothe.sloop.intention.models import ResponseLanguage


def test_build_response_language_hint_zh() -> None:
    hint = build_response_language_hint(ResponseLanguage.ZH)
    assert "Chinese (zh)" in hint
    assert "<RESPONSE_LANGUAGE_HINT>" in hint


def test_build_response_language_hint_fallback_for_other() -> None:
    assert build_response_language_hint(ResponseLanguage.OTHER) == RESPONSE_LANGUAGE_HINT_FALLBACK
    assert build_response_language_hint(None) == RESPONSE_LANGUAGE_HINT_FALLBACK


def test_pick_generic_chitchat_fallback_uses_structured_language() -> None:
    from soothe.sloop.chitchat_fallbacks import (
        GENERIC_CHITCHAT_FALLBACKS_ZH,
        pick_generic_chitchat_fallback,
    )

    reply = pick_generic_chitchat_fallback(ResponseLanguage.ZH)
    assert reply in GENERIC_CHITCHAT_FALLBACKS_ZH
