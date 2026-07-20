"""Tests for shared AIMessage text/JSON extraction helpers."""

from __future__ import annotations

from langchain_core.messages import AIMessage

from soothe_nano.utils.llm.response_text import (
    llm_response_text,
    parse_json_object,
    text_from_message_content,
)


def test_text_from_message_content_flattens_blocks() -> None:
    content = [
        {"type": "thinking", "thinking": "plan"},
        {"type": "text", "text": '{"word": "GOJSON"}'},
    ]
    assert text_from_message_content(content) == '{"word": "GOJSON"}'


def test_llm_response_text_uses_reasoning_when_content_empty() -> None:
    msg = AIMessage(
        content="",
        additional_kwargs={"reasoning_content": '{"queries": []}'},
    )
    assert llm_response_text(msg) == '{"queries": []}'


def test_parse_json_object_from_fence() -> None:
    raw = 'prefix\n```json\n{"queries": [{"query": "test"}]}\n```'
    parsed = parse_json_object(raw)
    assert parsed == {"queries": [{"query": "test"}]}
