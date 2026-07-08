"""Tests for assistant identity prompt helpers."""

from __future__ import annotations

from soothe.foundation.sloop.prompts.identity import (
    build_assistant_identity_block,
    normalize_assistant_name,
    prepend_assistant_identity,
)


def test_normalize_assistant_name_defaults_to_soothe() -> None:
    assert normalize_assistant_name("") == "Soothe"
    assert normalize_assistant_name("  MyBot  ") == "MyBot"


def test_build_assistant_identity_block_includes_name() -> None:
    block = build_assistant_identity_block("Soothe")
    assert "Soothe" in block
    assert "ASSISTANT_IDENTITY" in block


def test_prepend_assistant_identity() -> None:
    out = prepend_assistant_identity("Do the task.", "Soothe")
    assert "Soothe" in out
    assert "Do the task." in out
