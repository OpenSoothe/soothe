"""Integration tests for client JSON Schema structured output (IG-419)."""

from __future__ import annotations

import json

import pytest
from langchain_core.messages import HumanMessage

from soothe_nano.config import SootheConfig
from soothe_nano.utils.llm.structured import invoke_structured_chat

pytestmark = pytest.mark.integration

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
async def test_invoke_structured_chat_enforces_schema_constraints(
    integration_config: SootheConfig,
    requires_llm_api,
) -> None:
    """Structured output enforces schema constraints even when prompt asks to violate them.

    Modern structured-output models with strict=True will satisfy schema constraints
    (e.g., minimum: 1000) even when prompted to return invalid values. This test verifies
    that the structured output enforcement is working correctly - the model returns a
    valid response that satisfies the schema, not the invalid value requested in the prompt.
    """
    chat = integration_config.create_chat_model("default")
    strict_schema = {
        "type": "object",
        "properties": {
            "count": {"type": "integer", "minimum": 1000},
        },
        "required": ["count"],
        "additionalProperties": False,
    }
    # Prompt asks for count=1, but schema requires minimum=1000
    # A well-behaved structured output model will return count >= 1000
    data = await invoke_structured_chat(
        chat,
        [HumanMessage(content='Return JSON {"count": 1} only.')],
        json_schema=strict_schema,
        schema_name="StrictCount",
        strict=True,
    )
    # Verify the model satisfied the schema constraint (count >= 1000)
    # rather than returning the invalid value requested in the prompt
    assert isinstance(data, dict)
    assert "count" in data
    assert data["count"] >= 1000, (
        f"Structured output should enforce minimum=1000 constraint, got count={data['count']}"
    )


@pytest.mark.asyncio
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
