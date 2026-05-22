"""Structured chat invocation for client-provided JSON Schema."""

from __future__ import annotations

import logging
from typing import Any

import jsonschema
from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel

from soothe.utils.llm.schema_wire import resolve_schema_name, validate_response_schema

logger = logging.getLogger(__name__)


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


def _create_structured_runnable(
    chat: BaseChatModel,
    json_schema: dict[str, Any],
    *,
    schema_name: str,
    strict: bool,
) -> Any:
    """Build a structured-output runnable, mirroring IntentClassifier method order."""
    # Inject top-level title if missing (langchain requires it for function calling)
    schema_with_title = dict(json_schema)
    if "title" not in schema_with_title:
        schema_with_title["title"] = schema_name

    for method in ("function_calling", None, "json_mode"):
        try:
            kwargs: dict[str, Any] = {"strict": strict}
            if method is None:
                # json_mode doesn't support strict parameter
                return chat.with_structured_output(schema_with_title)
            return chat.with_structured_output(schema_with_title, method=method, **kwargs)
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
    invoke_cfg = config or {}

    structured = _create_structured_runnable(
        chat,
        schema,
        schema_name=name,
        strict=strict,
    )
    try:
        result = await structured.ainvoke(messages, config=invoke_cfg)
    except StructuredOutputError:
        raise
    except Exception as exc:
        msg = f"structured model invoke failed: {exc}"
        raise StructuredOutputError(msg) from exc

    data = normalize_structured_result(result)
    if strict:
        post_validate_structured_dict(data, schema)
    return data


__all__ = [
    "StructuredOutputError",
    "invoke_structured_chat",
    "normalize_structured_result",
    "post_validate_structured_dict",
]
