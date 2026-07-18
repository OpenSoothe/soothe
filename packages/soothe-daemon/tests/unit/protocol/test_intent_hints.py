"""Unit tests for daemon intent_hint validation."""

from __future__ import annotations

import pytest

from soothe_daemon.protocol.intent_hints import (
    IMAGE_TO_TEXT,
    TEXT_COMPLETION,
    is_daemon_intent_hint,
    validate_and_normalize_intent_hint,
)


@pytest.mark.parametrize(
    ("hint", "expected"),
    [
        ("text_completion", True),
        ("image_to_text", True),
        ("direct_llm", False),
        ("direct_model", False),
        ("ocr", True),
        ("embed", True),
        ("quiz", False),
        (None, False),
    ],
)
def test_is_daemon_intent_hint(hint: str | None, expected: bool) -> None:
    assert is_daemon_intent_hint(hint) is expected


@pytest.mark.parametrize(
    "hint",
    ["direct_llm", "quiz", "direct_model"],
)
def test_removed_intent_hints_rejected(hint: str) -> None:
    normalized, err = validate_and_normalize_intent_hint(
        hint,
        prompt_text="hello",
        has_attachments=False,
        has_response_schema=False,
    )
    assert normalized is None
    assert err is not None
    assert "removed" in err


def test_text_completion_rejects_attachments() -> None:
    _, err = validate_and_normalize_intent_hint(
        TEXT_COMPLETION,
        prompt_text="hello",
        has_attachments=True,
        has_response_schema=False,
    )
    assert err is not None
    assert "image_to_text" in err


def test_response_schema_allowed_for_image_to_text() -> None:
    hint, err = validate_and_normalize_intent_hint(
        IMAGE_TO_TEXT,
        prompt_text="describe",
        has_attachments=True,
        has_response_schema=True,
    )
    assert err is None
    assert hint == IMAGE_TO_TEXT


def test_response_schema_rejected_for_embed() -> None:
    _, err = validate_and_normalize_intent_hint(
        "embed",
        prompt_text="hello",
        has_attachments=False,
        has_response_schema=True,
    )
    assert err is not None
    assert "text_completion" in err


def test_agent_pass_through_hint_allowed() -> None:
    hint, err = validate_and_normalize_intent_hint(
        "agent",
        prompt_text="hello",
        has_attachments=False,
        has_response_schema=False,
    )
    assert err is None
    assert hint == "agent"
