"""Structured chat invocation for client-provided JSON Schema."""

from __future__ import annotations

import logging
from typing import Any

import jsonschema
from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel

from soothe.utils.llm.schema_wire import resolve_schema_name, validate_response_schema

logger = logging.getLogger(__name__)

# json_schema before json_mode: thinking models reject tool_choice (function_calling/None)
# but accept response_format; json_mode cannot take strict=True at bind time.
_STRUCTURED_METHODS: tuple[str | None, ...] = (
    "function_calling",
    None,
    "json_schema",
    "json_mode",
)


class StructuredOutputError(Exception):
    """Raised when structured output cannot be produced for a requested schema."""


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
    """Build a structured-output runnable for a single method, or raise."""
    if method is None:
        return chat.with_structured_output(schema_with_title)
    if method == "json_mode":
        # LangChain rejects strict= with json_mode; post-validate in invoke_structured_chat.
        return chat.with_structured_output(schema_with_title, method="json_mode")
    return chat.with_structured_output(schema_with_title, method=method, strict=strict)


def _is_retriable_structured_invoke_error(exc: Exception) -> bool:
    """Return True when another structured-output method may succeed (e.g. thinking models)."""
    msg = str(exc).lower()
    return "tool_choice" in msg and "thinking mode" in msg


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
) -> dict[str, Any]:
    """Invoke chat with strict structured output enforced by ``json_schema``.

    Args:
        chat: LangChain chat model (may be LimitedProviderModelWrapper).
        messages: Message list for ``ainvoke``.
        json_schema: Client JSON Schema dict.
        schema_name: Optional provider schema name override.
        strict: When True, post-validate with jsonschema after parsing.
        config: Optional RunnableConfig (Langfuse tracing, etc.).

    Returns:
        Parsed and validated output as a dict.

    Raises:
        StructuredOutputError: On provider or validation failure.
    """
    schema = validate_response_schema(json_schema)
    name = resolve_schema_name(schema, schema_name)
    schema_with_title = _schema_with_title(schema, name)
    invoke_cfg = config or {}

    last_exc: Exception | None = None
    for method in _STRUCTURED_METHODS:
        try:
            structured = _try_create_structured_runnable(
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

        try:
            result = await structured.ainvoke(messages, config=invoke_cfg)
        except StructuredOutputError:
            raise
        except Exception as exc:
            last_exc = exc
            if method != _STRUCTURED_METHODS[-1] and _is_retriable_structured_invoke_error(exc):
                logger.debug(
                    "structured invoke retrying after method=%s failure",
                    method,
                    exc_info=True,
                )
                continue
            msg = f"structured model invoke failed: {exc}"
            raise StructuredOutputError(msg) from exc

        data = normalize_structured_result(result)
        if strict:
            post_validate_structured_dict(data, schema)
        return data

    if last_exc is not None:
        msg = f"structured model invoke failed: {last_exc}"
        raise StructuredOutputError(msg) from last_exc

    msg = "all structured output methods failed for the configured model"
    raise StructuredOutputError(msg)


__all__ = [
    "StructuredOutputError",
    "invoke_structured_chat",
    "normalize_structured_result",
    "post_validate_structured_dict",
]
