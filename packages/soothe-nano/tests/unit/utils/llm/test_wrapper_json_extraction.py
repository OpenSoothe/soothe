"""Regression tests for ``_extract_json_str_from_response`` / ``_strip_json_text``.

Local OpenAI-compatible providers (oMLX, GLM, gemma) sometimes wrap
``json_schema`` output in a markdown fence (````` ```json ... ``` `````) or
prefix it with prose. The extractor must normalize those to a string that
``json.loads`` accepts, or ``JsonSchemaModelWrapper._parse_response`` raises
``Expecting value: line 2 column 1 (char 1)`` and breaks structured
``direct_llm`` turns.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from soothe_nano.utils.llm.wrappers import JsonSchemaModelWrapper, _strip_json_text


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Raw JSON — passes through unchanged.
        ('{"word": "GOJSON"}', {"word": "GOJSON"}),
        # Markdown-fenced json.
        ('```json\n{\n  "word": "GOJSON"\n}\n```', {"word": "GOJSON"}),
        # Bare fence (no language tag).
        ('```\n{"word": "GOJSON"}\n```', {"word": "GOJSON"}),
        # Prose prefix before the object.
        ('Here is the JSON: {"word": "GOJSON"}', {"word": "GOJSON"}),
        # Fence with leading newline (observed from gemma on oMLX).
        ('\n```json\n{\n  "word": "GOJSON"\n}\n```', {"word": "GOJSON"}),
    ],
)
def test_strip_json_text_parses_wrapped_output(raw: str, expected: dict) -> None:
    assert json.loads(_strip_json_text(raw)) == expected


def _make_response(content: str) -> MagicMock:
    msg = MagicMock()
    msg.content = content
    msg.additional_kwargs = {}
    return msg


def test_parse_response_handles_markdown_fence() -> None:
    """``JsonSchemaModelWrapper._parse_response`` must accept fenced JSON."""
    schema = {
        "type": "object",
        "title": "WordReply",
        "properties": {"word": {"type": "string"}},
        "required": ["word"],
        "additionalProperties": False,
    }
    wrapper = JsonSchemaModelWrapper(
        MagicMock(),
        {
            "type": "json_schema",
            "json_schema": {"name": "WordReply", "strict": True, "schema": schema},
        },
        schema,
        strict=False,
    )
    response = _make_response('\n```json\n{\n  "word": "GOJSON"\n}\n```')
    assert wrapper._parse_response(response) == {"word": "GOJSON"}


def test_parse_response_empty_content_raises_value_error() -> None:
    schema = {"type": "object", "properties": {"word": {"type": "string"}}, "required": ["word"]}
    wrapper = JsonSchemaModelWrapper(
        MagicMock(),
        {
            "type": "json_schema",
            "json_schema": {"name": "WordReply", "strict": True, "schema": schema},
        },
        schema,
        strict=False,
    )
    with pytest.raises(ValueError):
        wrapper._parse_response(SimpleNamespace(content="", additional_kwargs={}))


def test_parse_response_falls_back_to_reasoning_content() -> None:
    """When ``content`` is empty, JSON in ``reasoning_content`` is used."""
    schema = {"type": "object", "properties": {"word": {"type": "string"}}, "required": ["word"]}
    wrapper = JsonSchemaModelWrapper(
        MagicMock(),
        {
            "type": "json_schema",
            "json_schema": {"name": "WordReply", "strict": True, "schema": schema},
        },
        schema,
        strict=False,
    )
    response = MagicMock()
    response.content = ""
    response.additional_kwargs = {"reasoning_content": '```json\n{"word": "GOJSON"}\n```'}
    assert wrapper._parse_response(response) == {"word": "GOJSON"}


def test_parse_response_extracts_json_from_content_blocks() -> None:
    schema = {"type": "object", "properties": {"word": {"type": "string"}}, "required": ["word"]}
    wrapper = JsonSchemaModelWrapper(
        MagicMock(),
        {
            "type": "json_schema",
            "json_schema": {"name": "WordReply", "strict": True, "schema": schema},
        },
        schema,
        strict=False,
    )
    response = MagicMock()
    response.content = [
        {"type": "thinking", "thinking": "plan"},
        {"type": "text", "text": '{"word": "GOJSON"}'},
    ]
    response.additional_kwargs = {}
    assert wrapper._parse_response(response) == {"word": "GOJSON"}
