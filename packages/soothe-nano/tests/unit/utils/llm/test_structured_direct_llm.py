"""Unit tests for client JSON Schema structured output helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel

from soothe_nano.utils.llm.schema_wire import validate_response_schema
from soothe_nano.utils.llm.structured import (
    StructuredOutputError,
    ensure_json_keyword_in_messages,
    invoke_structured_chat,
    messages_contain_json_keyword,
    normalize_structured_result,
    wrap_json_keyword_safe,
)
from soothe_nano.utils.llm.wrappers import JsonSchemaModelWrapper, OpenAICompatModelWrapper

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


@pytest.mark.asyncio
async def test_invoke_structured_chat_applies_normalize_before_validation() -> None:
    """Answers-only provider payloads reach normalize before jsonschema validation."""
    from soothe.subagents.veritas.schemas import (
        build_veritas_response_schema,
        coerce_veritas_response,
    )

    schema = build_veritas_response_schema(1)
    inner = MagicMock()
    inner.ainvoke = AsyncMock(
        return_value=AIMessage(content='{"answers": ["pushed commit to origin"]}'),
    )
    fc_runnable = MagicMock()
    fc_runnable.ainvoke = AsyncMock(
        side_effect=RuntimeError(
            "tool_choice parameter does not support being set to required in thinking mode"
        )
    )
    json_mode_runnable = MagicMock()
    json_mode_runnable.ainvoke = AsyncMock(
        side_effect=RuntimeError("json_object must contain the word json")
    )

    def _with_structured_output(
        _schema: object, method: str | None = None, **_kwargs: object
    ) -> MagicMock:
        if method == "function_calling":
            return fc_runnable
        if method == "json_mode":
            return json_mode_runnable
        return json_mode_runnable

    inner.with_structured_output = MagicMock(side_effect=_with_structured_output)
    chat = OpenAICompatModelWrapper(inner, provider_name="test")

    out = await invoke_structured_chat(
        chat,
        [HumanMessage(content="Respond in JSON format")],
        json_schema=schema,
        schema_name="VeritasAnswer",
        strict=True,
        normalize=lambda data: coerce_veritas_response(data, 1),
    )
    assert out["defer"] is False
    assert out["answers"] == ["pushed commit to origin"]
    assert out["confidence"] == pytest.approx(0.7)


def test_limited_provider_wrapper_dict_schema() -> None:
    inner = MagicMock(spec=["with_structured_output"])
    wrapped = OpenAICompatModelWrapper(inner, "lmstudio")
    out = wrapped.with_structured_output(
        _WORD_SCHEMA,
        schema_name="WordReply",
        strict=True,
        method="json_schema",
    )
    assert isinstance(out, JsonSchemaModelWrapper)


def test_limited_provider_wrapper_delegates_function_calling() -> None:
    inner = MagicMock(spec=["with_structured_output"])
    inner.with_structured_output.return_value = "fc-runnable"
    wrapped = OpenAICompatModelWrapper(inner, "dashscope")
    out = wrapped.with_structured_output(
        _WORD_SCHEMA,
        method="function_calling",
        strict=True,
        tool_choice="auto",
    )
    assert out == "fc-runnable"
    inner.with_structured_output.assert_called_once_with(
        _WORD_SCHEMA,
        method="function_calling",
        strict=True,
        tool_choice="auto",
    )


def test_limited_provider_wrapper_delegates_json_mode_without_strict() -> None:
    """json_mode bind must not pass strict= through the compat wrapper."""
    inner = MagicMock(spec=["with_structured_output"])
    inner.with_structured_output.return_value = "json-mode-runnable"
    wrapped = OpenAICompatModelWrapper(inner, "dashscope")

    out = wrapped.with_structured_output(_WORD_SCHEMA, method="json_mode", strict=True)
    assert out == "json-mode-runnable"
    inner.with_structured_output.assert_called_once_with(
        _WORD_SCHEMA,
        method="json_mode",
    )

    inner.with_structured_output.reset_mock()
    out_default = wrapped.with_structured_output(_WORD_SCHEMA, strict=True)
    assert out_default == "json-mode-runnable"
    inner.with_structured_output.assert_called_once_with(_WORD_SCHEMA, method="json_mode")


@pytest.mark.asyncio
async def test_invoke_structured_chat_binds_json_mode_through_compat_wrapper() -> None:
    """method=None/json_mode must bind on OpenAICompatModelWrapper (no strict=)."""
    inner = MagicMock()
    json_mode_runnable = MagicMock()
    json_mode_runnable.ainvoke = AsyncMock(return_value={"word": "OK"})
    fc_runnable = MagicMock()
    fc_runnable.ainvoke = AsyncMock(side_effect=[None, None])

    def _with_structured_output(
        _schema: object, method: str | None = None, **kwargs: object
    ) -> MagicMock:
        assert "strict" not in kwargs or method == "function_calling"
        if method == "json_mode" or method is None:
            return json_mode_runnable
        if method == "function_calling":
            return fc_runnable
        raise RuntimeError(f"unexpected method {method!r}")

    inner.with_structured_output = MagicMock(side_effect=_with_structured_output)
    chat = OpenAICompatModelWrapper(inner, "dashscope")

    out = await invoke_structured_chat(
        chat,
        [HumanMessage(content="hi")],
        json_schema=_WORD_SCHEMA,
        schema_name="WordReply",
    )
    assert out == {"word": "OK"}
    assert json_mode_runnable.ainvoke.await_count == 1


@pytest.mark.asyncio
async def test_invoke_structured_chat_retries_function_calling_after_none() -> None:
    """Thinking models may skip the tool call once; retry before method fallback."""
    chat = MagicMock()
    fc_runnable = MagicMock()
    fc_runnable.ainvoke = AsyncMock(side_effect=[None, {"word": "OK"}])
    json_schema_runnable = MagicMock()
    json_schema_runnable.ainvoke = AsyncMock(
        side_effect=ValueError(
            "Provider returned empty response for json_schema format. Response object: AIMessage"
        )
    )

    def _with_structured_output(
        _schema: object, method: str | None = None, **_kwargs: object
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
    assert fc_runnable.ainvoke.await_count == 2
    json_schema_runnable.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_invoke_structured_chat_retries_empty_json_schema_once() -> None:
    """Empty json_schema output may succeed on immediate retry (thinking models)."""
    chat = MagicMock()
    json_schema_runnable = MagicMock()
    empty_err = ValueError(
        "Provider returned empty response for json_schema format. Response object: AIMessage"
    )
    json_schema_runnable.ainvoke = AsyncMock(side_effect=[empty_err, {"word": "OK"}])

    def _with_structured_output(
        _schema: object, method: str | None = None, **_kwargs: object
    ) -> MagicMock:
        if method == "json_schema":
            return json_schema_runnable
        raise RuntimeError(f"unexpected method {method!r}")

    chat.with_structured_output = MagicMock(side_effect=_with_structured_output)

    out = await invoke_structured_chat(
        chat,
        [HumanMessage(content="hi")],
        json_schema=_WORD_SCHEMA,
        schema_name="WordReply",
    )
    assert out == {"word": "OK"}
    assert json_schema_runnable.ainvoke.await_count == 2


@pytest.mark.asyncio
async def test_invoke_structured_chat_retries_after_empty_json_schema_response() -> None:
    """Empty json_schema output is retriable so thinking models can fall back."""
    chat = MagicMock()
    json_schema_runnable = MagicMock()
    fc_runnable = MagicMock()
    thinking_err = RuntimeError(
        "tool_choice parameter does not support being set to required in thinking mode"
    )

    def _with_structured_output(
        _schema: object, method: str | None = None, **_kwargs: object
    ) -> MagicMock:
        if method == "json_schema":
            return json_schema_runnable
        if method == "function_calling":
            return fc_runnable
        raise RuntimeError(f"unexpected method {method!r}")

    chat.with_structured_output = MagicMock(side_effect=_with_structured_output)

    # Prime cache: function_calling fails, json_schema succeeds.
    fc_runnable.ainvoke = AsyncMock(side_effect=thinking_err)
    json_schema_runnable.ainvoke = AsyncMock(return_value={"word": "cached"})
    await invoke_structured_chat(
        chat,
        [HumanMessage(content="hi")],
        json_schema=_WORD_SCHEMA,
        schema_name="WordReply",
    )

    empty_err = ValueError(
        "Provider returned empty response for json_schema format. Response object: AIMessage"
    )
    json_schema_runnable.ainvoke = AsyncMock(side_effect=empty_err)
    fc_runnable.ainvoke = AsyncMock(return_value={"word": "OK"})
    fc_calls_before = fc_runnable.ainvoke.await_count

    out = await invoke_structured_chat(
        chat,
        [HumanMessage(content="hi")],
        json_schema=_WORD_SCHEMA,
        schema_name="WordReply",
    )
    assert out == {"word": "OK"}
    assert fc_runnable.ainvoke.await_count == fc_calls_before + 1


@pytest.mark.asyncio
async def test_json_schema_wrapper_repairs_truncated_json() -> None:
    """Truncated json_schema provider output should parse after repair."""
    inner = MagicMock()
    inner.ainvoke = AsyncMock(
        return_value=AIMessage(
            content='{"is_task":false,"confidence":"high","social_response":"Hello'
        ),
    )
    pass1_schema = {
        "type": "object",
        "properties": {
            "is_task": {"type": "boolean"},
            "confidence": {"type": "string"},
            "social_response": {"type": "string"},
        },
        "required": ["is_task", "confidence"],
        "additionalProperties": True,
    }
    rf = {
        "type": "json_schema",
        "json_schema": {"name": "Pass1", "strict": False, "schema": pass1_schema},
    }
    wrapper = JsonSchemaModelWrapper(inner, rf, pass1_schema, strict=False)

    out = await wrapper.ainvoke([])
    assert out["is_task"] is False
    assert out["social_response"] == "Hello"
