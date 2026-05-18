"""Integration tests for client JSON Schema structured output (IG-419)."""

from __future__ import annotations

import json

import pytest
from langchain_core.messages import HumanMessage
from soothe.config import SootheConfig

from soothe.utils.llm.structured_invoke import StructuredOutputError, invoke_structured_chat

WORD_REPLY_SCHEMA = {
    "type": "object",
    "properties": {
        "word": {
            "type": "string",
            "description": "Single-word reply",
        }
    },
    "required": ["word"],
    "additionalProperties": False,
}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_invoke_structured_chat_live_default_model(
    integration_config: SootheConfig,
    requires_llm_api,
) -> None:
    """Structured invoke against the configured default chat model."""
    chat = integration_config.create_chat_model("default")
    data = await invoke_structured_chat(
        chat,
        [HumanMessage(content='Return JSON with word set exactly to "PING".')],
        json_schema=WORD_REPLY_SCHEMA,
        schema_name="WordReply",
        strict=True,
    )
    assert isinstance(data, dict)
    assert isinstance(data.get("word"), str)
    assert data["word"].strip()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_invoke_structured_chat_rejects_invalid_provider_output(
    integration_config: SootheConfig,
    requires_llm_api,
) -> None:
    """Post-validation fails when strict schema cannot be satisfied."""
    chat = integration_config.create_chat_model("default")
    strict_schema = {
        "type": "object",
        "properties": {
            "count": {"type": "integer", "minimum": 1000},
        },
        "required": ["count"],
        "additionalProperties": False,
    }
    with pytest.raises(StructuredOutputError):
        await invoke_structured_chat(
            chat,
            [HumanMessage(content='Return JSON {"count": 1} only.')],
            json_schema=strict_schema,
            schema_name="StrictCount",
            strict=True,
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_invoke_structured_chat_roundtrip_json(
    integration_config: SootheConfig,
    requires_llm_api,
) -> None:
    """Result serializes to valid JSON for daemon-style wire responses."""
    chat = integration_config.create_chat_model("fast")
    data = await invoke_structured_chat(
        chat,
        [HumanMessage(content='Return JSON with word set exactly to "OK".')],
        json_schema=WORD_REPLY_SCHEMA,
        schema_name="WordReply",
    )
    raw = json.dumps(data, ensure_ascii=False)
    parsed = json.loads(raw)
    assert parsed["word"].strip()
