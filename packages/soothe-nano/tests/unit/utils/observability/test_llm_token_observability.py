"""Tests for LLM token extraction and Langfuse-oriented ``llm_output`` enrichment."""

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from soothe_nano.utils.llm.observability import (
    SootheTokenUsageChatModel,
    bind_llm_token_observability,
    ensure_openai_style_token_usage_on_llm_result,
    extract_token_counts_from_llm_result,
    get_llm_token_usage_callback_handler,
    merge_token_usage_callbacks,
)


def test_extract_from_usage_metadata_on_message() -> None:
    msg = AIMessage(
        content="ok",
        usage_metadata={"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
    )
    gen = ChatGeneration(message=msg)
    result = LLMResult(generations=[[gen]], llm_output=None)
    counts = extract_token_counts_from_llm_result(result)
    assert counts == {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30}


def test_ensure_llm_output_from_usage_metadata() -> None:
    msg = AIMessage(
        content="ok",
        usage_metadata={"input_tokens": 4, "output_tokens": 5, "total_tokens": 9},
    )
    gen = ChatGeneration(message=msg)
    result = LLMResult(generations=[[gen]], llm_output=None)
    ensure_openai_style_token_usage_on_llm_result(result)
    assert result.llm_output is not None
    tu = result.llm_output["token_usage"]
    assert tu["prompt_tokens"] == 4
    assert tu["completion_tokens"] == 5
    assert tu["total_tokens"] == 9


def test_ensure_skips_when_token_usage_present() -> None:
    msg = AIMessage(
        content="x",
        usage_metadata={"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
    )
    gen = ChatGeneration(message=msg)
    result = LLMResult(
        generations=[[gen]],
        llm_output={
            "token_usage": {"prompt_tokens": 9, "completion_tokens": 9, "total_tokens": 18}
        },
    )
    ensure_openai_style_token_usage_on_llm_result(result)
    assert result.llm_output["token_usage"]["prompt_tokens"] == 9


def test_soothe_token_usage_model_delegates_with_structured_output() -> None:
    """Regression: wrapper must not inherit BaseChatModel.with_structured_output (daemon IntentClassifier)."""
    from unittest.mock import MagicMock

    from soothe_nano.utils.llm.structured import _JsonKeywordSafeRunnable

    inner = MagicMock(spec=BaseChatModel)
    inner.bind_tools.side_effect = lambda *a, **k: inner
    inner.with_structured_output.return_value = "structured-runnable"
    wrapped = SootheTokenUsageChatModel(inner)
    assert type(wrapped).bind_tools is not BaseChatModel.bind_tools
    out = wrapped.with_structured_output("schema", method="json_mode")
    assert isinstance(out, _JsonKeywordSafeRunnable)
    inner.with_structured_output.assert_called_once_with("schema", method="json_mode")


def test_bind_llm_token_observability_invokes_callback() -> None:
    msg = AIMessage(
        content="done",
        usage_metadata={"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
    )
    inner = GenericFakeChatModel(messages=iter([msg]))
    wrapped = bind_llm_token_observability(inner)
    out = wrapped.invoke([HumanMessage(content="hi")])
    assert out.content == "done"


def test_merge_token_usage_callbacks_attaches_handler() -> None:
    handler = get_llm_token_usage_callback_handler()
    merged = merge_token_usage_callbacks({"metadata": {"purpose": "test"}})
    callbacks = merged.get("callbacks")
    assert callbacks is not None
    assert handler in callbacks
    assert merged.get("metadata") == {"purpose": "test"}


@pytest.mark.asyncio
async def test_json_schema_wrapper_forwards_config() -> None:
    from unittest.mock import AsyncMock, MagicMock

    from pydantic import BaseModel

    from soothe_nano.utils.llm.wrappers import JsonSchemaModelWrapper

    class _Schema(BaseModel):
        answer: str

    inner = MagicMock()
    inner.ainvoke = AsyncMock(
        return_value=AIMessage(
            content='{"answer": "yes"}',
            usage_metadata={"input_tokens": 2, "output_tokens": 3, "total_tokens": 5},
        )
    )
    rf = {"type": "json_schema", "json_schema": {"name": "x", "strict": True, "schema": {}}}
    wrapper = JsonSchemaModelWrapper(inner, rf, _Schema)

    cfg = {"metadata": {"soothe_call_purpose": "test"}}

    await wrapper.ainvoke([], config=cfg)

    inner.ainvoke.assert_called_once()
    call_kw = inner.ainvoke.call_args
    assert call_kw.kwargs.get("config") == cfg
