"""Unit tests for client JSON Schema structured output helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel

from soothe.utils.llm.schema_wire import validate_response_schema
from soothe.utils.llm.structured_invoke import (
    StructuredOutputError,
    invoke_structured_chat,
    normalize_structured_result,
)
from soothe.utils.llm.wrappers import JsonSchemaModelWrapper, LimitedProviderModelWrapper

_WORD_SCHEMA = {
    "type": "object",
    "properties": {"word": {"type": "string"}},
    "required": ["word"],
    "additionalProperties": False,
}


def test_validate_response_schema_rejects_non_object() -> None:
    with pytest.raises(ValueError, match="JSON object"):
        validate_response_schema([])


def test_validate_response_schema_requires_type() -> None:
    with pytest.raises(ValueError, match='"type"'):
        validate_response_schema({"properties": {}})


def test_normalize_structured_result_pydantic() -> None:
    class _M(BaseModel):
        word: str

    assert normalize_structured_result(_M(word="ok")) == {"word": "ok"}


@pytest.mark.asyncio
async def test_invoke_structured_chat_success() -> None:
    chat = MagicMock()
    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value={"word": "OK"})
    chat.with_structured_output = MagicMock(return_value=structured)

    out = await invoke_structured_chat(
        chat,
        [HumanMessage(content="hi")],
        json_schema=_WORD_SCHEMA,
        schema_name="WordReply",
    )
    assert out == {"word": "OK"}
    chat.with_structured_output.assert_called()


@pytest.mark.asyncio
async def test_invoke_structured_chat_raises_when_all_methods_fail() -> None:
    chat = MagicMock()
    chat.with_structured_output = MagicMock(side_effect=RuntimeError("nope"))

    with pytest.raises(StructuredOutputError, match="all structured output methods failed"):
        await invoke_structured_chat(
            chat,
            [HumanMessage(content="hi")],
            json_schema=_WORD_SCHEMA,
        )


@pytest.mark.asyncio
async def test_json_schema_wrapper_dict_schema() -> None:
    inner = MagicMock()
    inner.ainvoke = AsyncMock(
        return_value=AIMessage(content='{"word": "OK"}'),
    )
    rf = {
        "type": "json_schema",
        "json_schema": {"name": "WordReply", "strict": True, "schema": _WORD_SCHEMA},
    }
    wrapper = JsonSchemaModelWrapper(inner, rf, _WORD_SCHEMA, strict=True)

    out = await wrapper.ainvoke([])
    assert out == {"word": "OK"}


def test_limited_provider_wrapper_dict_schema() -> None:
    inner = MagicMock(spec=["with_structured_output"])
    wrapped = LimitedProviderModelWrapper(inner, "lmstudio")
    out = wrapped.with_structured_output(
        _WORD_SCHEMA,
        schema_name="WordReply",
        strict=True,
    )
    assert isinstance(out, JsonSchemaModelWrapper)
