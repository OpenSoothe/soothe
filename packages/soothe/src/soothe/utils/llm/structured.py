"""Structured chat invocation for client-provided JSON Schema.

`invoke_structured_chat` is the sanctioned entry point for structured LLM output
in Soothe. It walks `function_calling -> json_schema -> json_mode` at invoke time,
caches the working method per chat model, and post-validates against the schema.

`BaseChatModel.with_structured_output` is treated as an internal primitive: it is
called only from inside this module and the wrapper classes that override it
(`OpenAICompatModelWrapper`, `SootheTokenUsageChatModel`). New code should
call `invoke_structured_chat` or `invoke_structured_chat_typed` instead.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any, TypeVar
from weakref import WeakKeyDictionary

import jsonschema
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from soothe.utils.llm.schema_wire import resolve_schema_name, validate_response_schema

T = TypeVar("T", bound=BaseModel)

_JSON_KEYWORD_HINT = "Respond with JSON matching the required schema."

logger = logging.getLogger(__name__)

# json_schema before json_mode: thinking models reject tool_choice (function_calling/None)
# but accept response_format; json_mode cannot take strict=True at bind time.
_STRUCTURED_METHODS: tuple[str | None, ...] = (
    "function_calling",
    None,
    "json_schema",
    "json_mode",
)

# Per-chat-model cache of the structured-output method that last produced a result.
# Lets thinking-mode providers skip the function_calling round-trip on every call.
# WeakKeyDictionary so cached entries don't pin chat models the caller has discarded.
_MISSING: Any = object()
_METHOD_CACHE: WeakKeyDictionary[BaseChatModel, str | None] = WeakKeyDictionary()


def _ordered_structured_methods(chat: BaseChatModel) -> tuple[str | None, ...]:
    """Return ``_STRUCTURED_METHODS`` with the cached working method moved to the front."""
    try:
        cached = _METHOD_CACHE.get(chat, _MISSING)
    except TypeError:
        # Unhashable chat model (e.g., SootheTokenUsageChatModel wrapper) — skip cache
        return _STRUCTURED_METHODS
    if cached is _MISSING or cached == _STRUCTURED_METHODS[0]:
        return _STRUCTURED_METHODS
    if cached not in _STRUCTURED_METHODS:
        return _STRUCTURED_METHODS
    return (cached, *(m for m in _STRUCTURED_METHODS if m != cached))


def _remember_structured_method(chat: BaseChatModel, method: str | None) -> None:
    """Record the method that just produced a result; tolerate non-weakrefable objects."""
    try:
        _METHOD_CACHE[chat] = method
    except TypeError:
        pass


class StructuredOutputError(Exception):
    """Raised when structured output cannot be produced for a requested schema."""


def _message_text(message: Any) -> str:
    """Extract plain text from a LangChain message for keyword checks."""
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "\n".join(parts)
    return str(content)


def messages_contain_json_keyword(messages: list[Any]) -> bool:
    """Return True when any message already mentions JSON (case-insensitive)."""
    return any("json" in _message_text(message).lower() for message in messages)


def ensure_json_keyword_in_messages(messages: list[Any]) -> list[Any]:
    """Ensure messages mention JSON for providers that require it with json_object mode.

    DashScope and some other OpenAI-compatible APIs reject ``response_format`` of type
    ``json_object`` unless the word ``json`` appears somewhere in the prompt messages.
    """
    if not messages or messages_contain_json_keyword(messages):
        return messages
    return [*messages, HumanMessage(content=_JSON_KEYWORD_HINT)]


class _JsonKeywordSafeRunnable:
    """Wrap a structured-output runnable to satisfy json_object prompt requirements."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
        if isinstance(input, list):
            input = ensure_json_keyword_in_messages(input)
        return self._inner.invoke(input, config=config, **kwargs)

    async def ainvoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
        if isinstance(input, list):
            input = ensure_json_keyword_in_messages(input)
        return await self._inner.ainvoke(input, config=config, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def wrap_json_keyword_safe(runnable: Any) -> Any:
    """Wrap a structured-output runnable so prompts satisfy json_object providers."""
    return _JsonKeywordSafeRunnable(runnable)


def normalize_structured_result(result: Any) -> dict[str, Any]:
    """Coerce structured LLM output to a plain dict."""
    if isinstance(result, BaseModel):
        return result.model_dump(mode="python")
    if isinstance(result, dict):
        return result
    msg = f"structured output returned unexpected type: {type(result).__name__}"
    raise StructuredOutputError(msg)


def post_validate_structured_dict(data: dict[str, Any], json_schema: dict[str, Any]) -> None:
    """Post-validate parsed output against the client JSON Schema."""
    try:
        jsonschema.validate(instance=data, schema=json_schema)
    except jsonschema.ValidationError as exc:
        msg = f"structured_output_validation_failed: {exc.message}"
        raise StructuredOutputError(msg) from exc


def _schema_with_title(json_schema: dict[str, Any], schema_name: str) -> dict[str, Any]:
    schema_with_title = dict(json_schema)
    if "title" not in schema_with_title:
        schema_with_title["title"] = schema_name
    return schema_with_title


def _try_create_structured_runnable(
    chat: BaseChatModel,
    schema_with_title: dict[str, Any],
    *,
    method: str | None,
    strict: bool,
) -> Any:
    """Build a structured-output runnable for a single method, or raise.

    For function_calling method, uses tool_choice='auto' instead of the default
    object format. Thinking-mode models (MiniMax, glm-5, Moonshot) reject
    tool_choice in object format but accept string values like 'auto'.
    """
    if method is None:
        return chat.with_structured_output(schema_with_title)
    if method == "json_mode":
        # LangChain rejects strict= with json_mode; post-validate in invoke_structured_chat.
        return chat.with_structured_output(schema_with_title, method="json_mode")
    if method == "function_calling":
        # Use tool_choice='auto' for thinking-model compatibility.
        # Default function_calling uses object format which thinking models reject.
        # With 'auto', the model can reason then decide to call the tool.
        return chat.with_structured_output(
            schema_with_title, method=method, strict=strict, tool_choice="auto"
        )
    return chat.with_structured_output(schema_with_title, method=method, strict=strict)


def _is_retriable_structured_invoke_error(exc: Exception) -> bool:
    """Return True when another structured-output method may succeed (e.g. thinking models)."""
    import json as _json

    if isinstance(exc, _json.JSONDecodeError):
        return True
    msg = str(exc).lower()
    if "tool_choice" in msg and "thinking mode" in msg:
        return True
    if "json_object" in msg and "must contain" in msg and "json" in msg:
        return True
    return "jsondecodeerror" in msg or "unterminated string" in msg


def _create_structured_runnable(
    chat: BaseChatModel,
    json_schema: dict[str, Any],
    *,
    schema_name: str,
    strict: bool,
) -> Any:
    """Build a structured-output runnable, mirroring IntentClassifier method order."""
    schema_with_title = _schema_with_title(json_schema, schema_name)

    for method in _STRUCTURED_METHODS:
        try:
            return _try_create_structured_runnable(
                chat,
                schema_with_title,
                method=method,
                strict=strict,
            )
        except Exception:
            logger.debug(
                "with_structured_output failed for method=%s",
                method,
                exc_info=True,
            )
            continue

    msg = "all structured output methods failed for the configured model"
    raise StructuredOutputError(msg)


async def invoke_structured_chat(
    chat: BaseChatModel,
    messages: list[Any],
    *,
    json_schema: dict[str, Any],
    schema_name: str | None = None,
    strict: bool = True,
    config: dict[str, Any] | None = None,
    normalize: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Invoke chat with strict structured output enforced by ``json_schema``.

    Args:
        chat: LangChain chat model (may be OpenAICompatModelWrapper).
        messages: Message list for ``ainvoke``.
        json_schema: Client JSON Schema dict.
        schema_name: Optional provider schema name override.
        strict: When True, post-validate with jsonschema after parsing.
        config: Optional RunnableConfig (Langfuse tracing, etc.).
        normalize: Optional pre-validation dict normalizer (e.g. coerce missing fields).

    Returns:
        Parsed and validated output as a dict.

    Raises:
        StructuredOutputError: On provider or validation failure.
    """
    from soothe.utils.llm.observability import merge_token_usage_callbacks

    schema = validate_response_schema(json_schema)
    name = resolve_schema_name(schema, schema_name)
    schema_with_title = _schema_with_title(schema, name)
    invoke_cfg = merge_token_usage_callbacks(config)

    methods = _ordered_structured_methods(chat)
    last_method = methods[-1]
    prepared_messages = ensure_json_keyword_in_messages(messages)
    # When a normalizer is supplied, defer wire-schema validation until after it
    # runs — JsonSchemaModelWrapper validates on parse and would reject
    # answers-only payloads that coerce_veritas_response can repair.
    bind_strict = strict if normalize is None else False

    last_exc: Exception | None = None
    for method in methods:
        try:
            structured = _try_create_structured_runnable(
                chat,
                schema_with_title,
                method=method,
                strict=bind_strict,
            )
        except Exception:
            logger.debug(
                "with_structured_output failed for method=%s",
                method,
                exc_info=True,
            )
            continue

        try:
            result = await structured.ainvoke(prepared_messages, config=invoke_cfg)
        except StructuredOutputError:
            raise
        except Exception as exc:
            last_exc = exc
            if method != last_method and _is_retriable_structured_invoke_error(exc):
                logger.debug(
                    "structured invoke: method=%s rejected by provider, falling back",
                    method,
                )
                continue
            msg = f"structured model invoke failed: {exc}"
            raise StructuredOutputError(msg) from exc

        _remember_structured_method(chat, method)
        if result is None:
            # Provider returned nothing (e.g. model skipped the tool call / JSON
            # response).  Treat as a retriable failure so we fall through to the
            # next structured-output method.
            logger.debug(
                "structured invoke: method=%s returned None, falling back",
                method,
            )
            last_exc = StructuredOutputError(f"method={method!r} returned None")
            continue
        data = normalize_structured_result(result)
        if normalize is not None:
            data = normalize(data)
        if strict:
            post_validate_structured_dict(data, schema)
        return data

    if last_exc is not None:
        msg = f"structured model invoke failed: {last_exc}"
        raise StructuredOutputError(msg) from last_exc

    msg = "all structured output methods failed for the configured model"
    raise StructuredOutputError(msg)


async def invoke_structured_chat_typed(
    chat: BaseChatModel,
    messages: list[Any],
    schema: type[T],
    *,
    strict: bool = True,
    config: dict[str, Any] | None = None,
    normalize: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> T:
    """Invoke `invoke_structured_chat` and return a typed Pydantic instance.

    Convenience wrapper for the common case where the caller already has a
    Pydantic schema class. Derives `json_schema` from `schema.model_json_schema()`
    and uses the class name as the schema name.

    Args:
        chat: LangChain chat model.
        messages: Message list for `ainvoke`.
        schema: Pydantic class describing the expected output.
        strict: Post-validate the parsed dict against the wire schema.
        config: Optional RunnableConfig (Langfuse tracing, etc.).
        normalize: Optional pre-validation dict normalizer.

    Returns:
        Validated `schema` instance.

    Raises:
        StructuredOutputError: On provider or validation failure.
    """
    json_schema = schema.model_json_schema()
    result_dict = await invoke_structured_chat(
        chat,
        messages,
        json_schema=json_schema,
        schema_name=schema.__name__,
        strict=strict,
        config=config,
        normalize=normalize,
    )
    return schema(**result_dict)


def invoke_structured_chat_sync(
    chat: BaseChatModel,
    messages: list[Any],
    *,
    json_schema: dict[str, Any],
    schema_name: str | None = None,
    strict: bool = True,
    config: dict[str, Any] | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Sync wrapper for `invoke_structured_chat` (must not run inside a live loop).

    Intended for sync middleware paths (e.g., LangGraph sync `wrap_model_call`).
    Internally calls `asyncio.run`, optionally bounded by `asyncio.wait_for` so
    timeouts cancel the underlying coroutine instead of leaking a thread.

    Args:
        chat: LangChain chat model.
        messages: Message list.
        json_schema: Client JSON Schema dict.
        schema_name: Optional provider schema name override.
        strict: Post-validate parsed output.
        config: Optional RunnableConfig.
        timeout: Optional seconds; raises `TimeoutError` on overshoot.

    Returns:
        Parsed and validated output as a dict.

    Raises:
        StructuredOutputError: On provider or validation failure.
        TimeoutError: When the bounded call exceeds `timeout`.
        RuntimeError: If invoked from inside a running event loop.
    """

    async def _run() -> dict[str, Any]:
        coro = invoke_structured_chat(
            chat,
            messages,
            json_schema=json_schema,
            schema_name=schema_name,
            strict=strict,
            config=config,
        )
        if timeout is None:
            return await coro
        return await asyncio.wait_for(coro, timeout=timeout)

    try:
        return asyncio.run(_run())
    except TimeoutError as exc:
        msg = f"structured model invoke timed out after {timeout:.0f}s"
        raise TimeoutError(msg) from exc


def invoke_structured_chat_sync_typed(
    chat: BaseChatModel,
    messages: list[Any],
    schema: type[T],
    *,
    strict: bool = True,
    config: dict[str, Any] | None = None,
    timeout: float | None = None,
) -> T:
    """Sync `invoke_structured_chat_typed` for sync middleware paths."""
    data = invoke_structured_chat_sync(
        chat,
        messages,
        json_schema=schema.model_json_schema(),
        schema_name=schema.__name__,
        strict=strict,
        config=config,
        timeout=timeout,
    )
    return schema(**data)


async def invoke_structured(
    factory: Any,
    messages: list[Any],
    json_schema: dict[str, Any],
    *,
    role: str = "default",
    schema_name: str | None = None,
    strict: bool = True,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create model from factory and invoke structured output.

    Convenience wrapper combining factory model creation with structured output invocation.
    Use when you have a factory but don't need to reuse the model for multiple calls.

    Args:
        factory: LLMFactory instance (typed as Any to avoid circular import).
        messages: Message list for invoke.
        json_schema: Client JSON Schema dict.
        role: Model role to use (default, fast, think, image, embedding).
        schema_name: Optional provider schema name.
        strict: Post-validate parsed output.
        config: Optional RunnableConfig.

    Returns:
        Parsed and validated dict.

    Raises:
        StructuredOutputError: On provider or validation failure.
    """
    chat = factory.create_chat_model(role)
    return await invoke_structured_chat(
        chat,
        messages,
        json_schema=json_schema,
        schema_name=schema_name,
        strict=strict,
        config=config,
    )


__all__ = [
    "StructuredOutputError",
    "ensure_json_keyword_in_messages",
    "invoke_structured",
    "invoke_structured_chat",
    "invoke_structured_chat_sync",
    "invoke_structured_chat_sync_typed",
    "invoke_structured_chat_typed",
    "messages_contain_json_keyword",
    "normalize_structured_result",
    "post_validate_structured_dict",
    "wrap_json_keyword_safe",
]
