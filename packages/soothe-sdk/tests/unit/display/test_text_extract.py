"""Tests for display text extraction helpers."""

from __future__ import annotations

from langchain_core.messages import AIMessage, AIMessageChunk

from soothe_sdk.display.text_extract import extract_ai_text_for_display


def test_extract_ai_text_strips_complete_messages() -> None:
    assert extract_ai_text_for_display(AIMessage(content="  hello  ")) == "hello"


def test_extract_ai_text_preserves_stream_chunk_whitespace() -> None:
    """Streaming deltas often carry leading spaces; stripping breaks resume text."""
    assert extract_ai_text_for_display(AIMessageChunk(content=" there")) == " there"
    assert extract_ai_text_for_display(AIMessageChunk(content="!")) == "!"
