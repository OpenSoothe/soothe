"""Unit tests for client JSON Schema structured output helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel

from soothe.utils.llm.schema_wire import validate_response_schema
from soothe.utils.llm.structured_invoke import (
    StructuredOutputError,
    ensure_json_keyword_in_messages,
    invoke_structured_chat,
    messages_contain_json_keyword,
    normalize_structured_result,
    wrap_json_keyword_safe,
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


def test_messages_contain_json_keyword() -> None:
    assert messages_contain_json_keyword([HumanMessage(content="Return JSON output")])
    assert not messages_contain_json_keyword([HumanMessage(content="hello")])


def test_ensure_json_keyword_in_messages_appends_hint() -> None:
    original = [SystemMessage(content="plan"), HumanMessage(content="Assess status")]
    updated = ensure_json_keyword_in_messages(original)
    assert len(updated) == len(original) + 1
    assert "json" in updated[-1].content.lower()


def test_ensure_json_keyword_in_messages_noop_when_present() -> None:
    messages = [HumanMessage(content="Respond in JSON format")]
    assert ensure_json_keyword_in_messages(messages) is messages


@pytest.mark.asyncio
async def test_wrap_json_keyword_safe_injects_on_invoke() -> None:
    inner = MagicMock()
    inner.ainvoke = AsyncMock(return_value={"word": "OK"})
    wrapped = wrap_json_keyword_safe(inner)

    await wrapped.ainvoke([HumanMessage(content="hi")])

    sent_messages = inner.ainvoke.await_args.args[0]
    assert any("json" in str(getattr(m, "content", "")).lower() for m in sent_messages)


@pytest.mark.asyncio
async def test_invoke_structured_chat_injects_json_keyword() -> None:
    chat = MagicMock()
    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value={"word": "OK"})
    chat.with_structured_output = MagicMock(return_value=structured)

    await invoke_structured_chat(
        chat,
        [HumanMessage(content="hi")],
        json_schema=_WORD_SCHEMA,
        schema_name="WordReply",
    )

    sent_messages = structured.ainvoke.await_args.args[0]
    assert any("json" in str(getattr(m, "content", "")).lower() for m in sent_messages)


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
async def test_invoke_structured_chat_retries_json_schema_after_thinking_tool_choice_error() -> (
    None
):
    """Thinking-mode models reject tool_choice; fall back to json_schema at invoke time."""
    chat = MagicMock()
    fc_runnable = MagicMock()
    thinking_err = RuntimeError(
        "tool_choice parameter does not support being set to required in thinking mode"
    )
    fc_runnable.ainvoke = AsyncMock(side_effect=thinking_err)
    json_schema_runnable = MagicMock()
    json_schema_runnable.ainvoke = AsyncMock(return_value={"word": "OK"})

    def _with_structured_output(
        _schema: object, method: str | None = None, **kwargs: object
    ) -> MagicMock:
        if method == "json_schema":
            return json_schema_runnable
        return fc_runnable

    chat.with_structured_output = MagicMock(side_effect=_with_structured_output)

    out = await invoke_structured_chat(
        chat,
        [HumanMessage(content="hi")],
        json_schema=_WORD_SCHEMA,
        schema_name="WordReply",
    )
    assert out == {"word": "OK"}
    assert json_schema_runnable.ainvoke.await_count == 1


@pytest.mark.asyncio
async def test_invoke_structured_chat_caches_working_method_per_chat() -> None:
    """Second invoke on the same chat skips the previously-failing method."""
    chat = MagicMock()
    method_calls: list[str | None] = []
    fc_runnable = MagicMock()
    fc_runnable.ainvoke = AsyncMock(
        side_effect=RuntimeError(
            "tool_choice parameter does not support being set to required in thinking mode"
        )
    )
    json_schema_runnable = MagicMock()
    json_schema_runnable.ainvoke = AsyncMock(return_value={"word": "OK"})

    def _with_structured_output(
        _schema: object, method: str | None = None, **_kwargs: object
    ) -> MagicMock:
        method_calls.append(method)
        if method == "json_schema":
            return json_schema_runnable
        return fc_runnable

    chat.with_structured_output = MagicMock(side_effect=_with_structured_output)

    out1 = await invoke_structured_chat(
        chat, [HumanMessage(content="hi")], json_schema=_WORD_SCHEMA, schema_name="WordReply"
    )
    assert out1 == {"word": "OK"}
    # First call: function_calling tried (and failed) before json_schema succeeded.
    assert "function_calling" in method_calls
    assert "json_schema" in method_calls

    method_calls.clear()
    fc_awaits_after_first = fc_runnable.ainvoke.await_count
    out2 = await invoke_structured_chat(
        chat, [HumanMessage(content="hi")], json_schema=_WORD_SCHEMA, schema_name="WordReply"
    )
    assert out2 == {"word": "OK"}
    # Second call: json_schema is tried first and succeeds; no failing-method round-trip.
    assert method_calls[0] == "json_schema"
    assert "function_calling" not in method_calls
    assert fc_runnable.ainvoke.await_count == fc_awaits_after_first


@pytest.mark.asyncio
async def test_invoke_structured_chat_json_mode_omits_strict_at_bind() -> None:
    """json_mode bind must not pass strict= (LangChain ValueError); strict applies post-parse."""
    chat = MagicMock()
    json_runnable = MagicMock()
    json_runnable.ainvoke = AsyncMock(return_value={"word": "OK"})

    def _with_structured_output(
        _schema: object, method: str | None = None, **kwargs: object
    ) -> MagicMock:
        if method == "json_mode":
            assert "strict" not in kwargs
            return json_runnable
        raise RuntimeError("unexpected method")

    chat.with_structured_output = MagicMock(side_effect=_with_structured_output)

    out = await invoke_structured_chat(
        chat,
        [HumanMessage(content="hi")],
        json_schema=_WORD_SCHEMA,
        schema_name="WordReply",
        strict=True,
    )
    assert out == {"word": "OK"}


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
