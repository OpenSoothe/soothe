"""Generic model wrappers for limited OpenAI-compatible providers.

These wrappers adapt non-standard OpenAI-compatible endpoints (DashScope, oMLX,
LMStudio, vLLM) that may:
- Only accept string ``tool_choice`` values, not object format
- Return structured JSON in ``reasoning_content`` or content block lists
- Return empty ``content`` when ``json_schema`` is used with thinking models
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import jsonschema
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable
from pydantic import BaseModel

from soothe_nano.utils.llm.response_text import text_from_message_content
from soothe_nano.utils.llm.schema_wire import (
    build_json_schema_response_format,
    validate_response_schema,
)
from soothe_nano.utils.text_preview import preview_first

logger = logging.getLogger(__name__)


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?```", re.DOTALL | re.IGNORECASE)


def _sanitize_tool_choice_for_compat(tool_choice: Any) -> Any:
    """Normalize tool_choice for limited OpenAI-compatible providers.

    Some "thinking mode" providers reject both object-form and ``"required"``
    tool choice. For compatibility, coerce those variants to ``"auto"``.
    """
    if isinstance(tool_choice, dict):
        return "auto"
    if isinstance(tool_choice, str) and tool_choice in {"required", "any"}:
        return "auto"
    # LangChain may pass bool and later coerce True -> "required".
    if tool_choice is True:
        return "auto"
    return tool_choice


def _strip_json_text(raw: str) -> str:
    """Normalize model output to a JSON-parseable string.

    Local OpenAI-compatible providers (oMLX/GLM/gemma) sometimes wrap
    ``json_schema`` output in a markdown fence (````` ```json ... ``` `````)
    or prefix it with prose even though ``response_format`` requested strict
    JSON. Strip the fence and, if prose remains, slice to the outermost JSON
    object so ``json.loads`` succeeds.
    """
    text = (raw or "").strip()
    if not text:
        return text
    fence = _JSON_FENCE_RE.search(text)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    if start > 0:
        # Leading prose before the first object — slice it off.
        text = text[start:]
    return text


def _build_json_schema_model_wrapper(
    model: BaseChatModel,
    schema: Any,
    *,
    schema_name: str | None,
    strict: bool,
) -> JsonSchemaModelWrapper:
    """Build ``JsonSchemaModelWrapper`` for wire dict or Pydantic schema."""
    if isinstance(schema, dict):
        wire_schema = validate_response_schema(schema)
        from soothe_nano.utils.llm.schema_wire import resolve_schema_name

        name = resolve_schema_name(wire_schema, schema_name)
        response_format = build_json_schema_response_format(
            wire_schema,
            name=name,
            strict=bool(strict),
        )
        return JsonSchemaModelWrapper(
            model,
            response_format,
            wire_schema,
            strict=bool(strict),
        )

    json_schema = schema.model_json_schema()
    name = (
        schema_name.strip()
        if isinstance(schema_name, str) and schema_name.strip()
        else schema.__name__
    )
    response_format = build_json_schema_response_format(
        json_schema,
        name=name,
        strict=bool(strict),
    )
    return JsonSchemaModelWrapper(
        model,
        response_format,
        schema,
        strict=bool(strict),
    )


def _extract_json_str_from_response(response: Any) -> str:
    """Extract JSON text from an AIMessage-like provider response."""
    # Check content field first (primary for AIMessage-like objects)
    if hasattr(response, "content"):
        if response.content:
            return _strip_json_text(text_from_message_content(response.content))
        # content exists but is empty — check reasoning_content before giving up
        if hasattr(response, "additional_kwargs"):
            rc = response.additional_kwargs.get("reasoning_content")
            if rc:
                logger.debug("JSON found in reasoning_content field (additional_kwargs)")
                return _strip_json_text(str(rc))
        # AIMessage-like object with empty content and no reasoning_content → empty
        return ""
    # Fallback for non-AIMessage response types (e.g., raw string)
    return _strip_json_text(str(response))


def _coerce_structured_json(
    json_dict: dict[str, Any],
    schema: Any,
    *,
    json_schema: dict[str, Any] | None = None,
    strict: bool = True,
) -> Any:
    """Validate parsed JSON against Pydantic or wire JSON Schema."""
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        return schema.model_validate(json_dict)
    if isinstance(schema, dict):
        wire_schema = json_schema if json_schema is not None else schema
        if strict:
            jsonschema.validate(instance=json_dict, schema=wire_schema)
        return json_dict
    msg = f"unsupported structured output schema type: {type(schema).__name__}"
    raise TypeError(msg)


class JsonSchemaModelWrapper(Runnable):
    """Wrapper that injects json_schema response_format and parses JSON output.

    Limited OpenAI providers require response_format={"type": "json_schema"} not {"type": "json_object"}.
    Unlike langchain's built-in structured output, we manually parse the JSON response
    into a Pydantic object, checking both content and reasoning_content fields.

    Handles providers that return structured JSON in reasoning_content field:
    - LMStudio, MLXServer, GLM deployments with thinking tokens

    Args:
        model: The base model to wrap.
        response_format: The json_schema format dict to inject.
        schema: Pydantic model class or client JSON Schema dict for parsing.
    """

    def __init__(
        self,
        model: BaseChatModel,
        response_format: dict[str, Any],
        schema: Any,
        *,
        strict: bool = True,
    ) -> None:
        """Initialize the wrapper.

        Args:
            model: The base model to wrap.
            response_format: The json_schema format dict to inject on invoke.
            schema: Pydantic model or JSON Schema dict for validation.
            strict: When True, validate dict outputs with jsonschema.
        """
        self._model = model
        self._response_format = response_format
        self._schema = schema
        self._strict = strict
        self._wire_json_schema = schema if isinstance(schema, dict) else None

    def _parse_response(self, response: Any) -> Any:
        json_str = _extract_json_str_from_response(response)
        if not json_str or json_str.strip() == "":
            raise ValueError(
                f"Provider returned empty response for json_schema format. "
                f"Response object: {type(response).__name__}"
            )
        logger.debug(
            "Provider response for json_schema: content='%s', reasoning_content='%s'",
            preview_first(str(response.content) if hasattr(response, "content") else "", 100),
            preview_first(
                str(response.additional_kwargs.get("reasoning_content", ""))
                if hasattr(response, "additional_kwargs")
                else "",
                100,
            ),
        )
        from soothe_nano.utils.json_parsing import _load_llm_json_dict

        json_dict = _load_llm_json_dict(json_str)
        return _coerce_structured_json(
            json_dict,
            self._schema,
            json_schema=self._wire_json_schema,
            strict=self._strict,
        )

    def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
        """Inject response_format, invoke model, and parse JSON response.

        Args:
            input: Messages or prompt to send.
            config: Runnable config (callbacks, metadata, Langfuse, etc.).
            **kwargs: Additional invoke parameters.

        Returns:
            Parsed Pydantic object from the JSON response.
        """
        kwargs["response_format"] = self._response_format
        response = self._model.invoke(input, config=config, **kwargs)

        try:
            return self._parse_response(response)
        except json.JSONDecodeError as e:
            logger.error(
                "Failed to parse JSON response: %s\n"
                "Response content: '%s'\n"
                "Response reasoning_content: '%s'\n"
                "Full response: %s",
                e,
                preview_first(
                    str(response.content) if hasattr(response, "content") else "N/A", 200
                ),
                preview_first(
                    str(response.additional_kwargs.get("reasoning_content", "N/A"))
                    if hasattr(response, "additional_kwargs")
                    else "N/A",
                    200,
                ),
                response,
            )
            raise
        except Exception as e:
            logger.error(
                "Failed to process provider response: %s\nResponse: %s",
                e,
                response,
            )
            raise

    async def ainvoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
        """Async version of invoke with response_format injection and JSON parsing.

        Args:
            input: Messages or prompt to send.
            config: Runnable config (callbacks, metadata, Langfuse, etc.).
            **kwargs: Additional invoke parameters.

        Returns:
            Parsed Pydantic object from the JSON response.
        """
        kwargs["response_format"] = self._response_format
        response = await self._model.ainvoke(input, config=config, **kwargs)

        try:
            return self._parse_response(response)
        except json.JSONDecodeError as e:
            logger.error(
                "Failed to parse JSON response: %s\n"
                "Response content: '%s'\n"
                "Response reasoning_content: '%s'\n"
                "Full response: %s",
                e,
                preview_first(
                    str(response.content) if hasattr(response, "content") else "N/A", 200
                ),
                preview_first(
                    str(response.additional_kwargs.get("reasoning_content", "N/A"))
                    if hasattr(response, "additional_kwargs")
                    else "N/A",
                    200,
                ),
                response,
            )
            raise
        except Exception as e:
            logger.error(
                "Failed to process provider response: %s\nResponse: %s",
                e,
                response,
            )
            raise

    def __getattr__(self, name: str) -> Any:
        """Delegate any other attributes to the wrapped model."""
        return getattr(self._model, name)


class OpenAICompatModelWrapper(BaseChatModel):
    """Route structured-output methods for limited OpenAI-compatible providers.

    - ``function_calling`` / ``json_mode``: delegate to the inner LangChain model.
    - ``json_schema``: ``JsonSchemaModelWrapper`` for ``reasoning_content`` parsing.
    - ``bind_tools``: sanitize object-form ``tool_choice`` to string values.
    """

    def __init__(self, model: BaseChatModel, provider_name: str = "unknown") -> None:
        """Initialize the wrapper.

        Args:
            model: The original BaseChatModel to wrap.
            provider_name: Provider name for logging purposes.
        """
        self._model = model
        self._provider_name = provider_name

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
        """Structured output with provider-specific method routing.

        Limited OpenAI providers differ by method:
        - ``function_calling`` / ``json_mode``: delegate to the inner model so
          thinking models (Kimi, MiniMax) can return tool args or json_object
          output instead of empty ``content`` with reasoning tokens only.
        - ``json_schema``: use ``JsonSchemaModelWrapper`` which injects
          ``response_format`` and parses ``reasoning_content`` (oMLX, GLM).

        Args:
            schema: Pydantic model class or client JSON Schema dict.
            **kwargs: ``schema_name``, ``strict``, and method (intercepted).

        Returns:
            JsonSchemaModelWrapper for ``json_schema``; inner runnable otherwise.
        """
        method = kwargs.pop("method", "json_mode")
        schema_name = kwargs.pop("schema_name", None)
        strict = kwargs.pop("strict", True)

        if method in ("function_calling", "json_mode"):
            delegate_kwargs: dict[str, Any] = {"method": method, **kwargs}
            if schema_name is not None:
                delegate_kwargs["schema_name"] = schema_name
            if method == "function_calling":
                delegate_kwargs["strict"] = strict
                sanitized_tool_choice = _sanitize_tool_choice_for_compat(kwargs.get("tool_choice"))
                if sanitized_tool_choice != kwargs.get("tool_choice"):
                    logger.debug(
                        "OpenAICompatModelWrapper sanitizing incompatible tool_choice=%r for structured output (provider=%s)",
                        kwargs.get("tool_choice"),
                        self._provider_name,
                    )
                    delegate_kwargs["tool_choice"] = sanitized_tool_choice
            # json_mode: omit strict — LangChain rejects it; invoke_structured_chat post-validates.
            return self._model.with_structured_output(schema, **delegate_kwargs)

        # json_schema (explicit) — JsonSchemaModelWrapper for reasoning_content
        try:
            return _build_json_schema_model_wrapper(
                self._model,
                schema,
                schema_name=schema_name,
                strict=strict,
            )
        except Exception:
            logger.debug(
                "Failed to convert schema to json_schema format, falling back",
                exc_info=True,
            )
            return self._model.with_structured_output(
                schema,
                method=method,
                schema_name=schema_name,
                strict=strict,
                **kwargs,
            )

    def bind_tools(self, tools: list[Any], **kwargs: Any) -> Any:
        """Intercept tool_choice parameter for limited providers.

        Coerces incompatible values (object-form and ``"required"``) to
        ``"auto"`` for provider compatibility.

        Args:
            tools: List of tool definitions.
            **kwargs: Additional parameters (tool_choice intercepted).

        Returns:
            Model with sanitized tool_choice.
        """
        # Intercept tool_choice parameter
        if "tool_choice" in kwargs:
            sanitized_tool_choice = _sanitize_tool_choice_for_compat(kwargs["tool_choice"])
            if sanitized_tool_choice != kwargs["tool_choice"]:
                logger.debug(
                    "OpenAICompatModelWrapper sanitizing incompatible tool_choice=%r (provider=%s)",
                    kwargs["tool_choice"],
                    self._provider_name,
                )
                kwargs["tool_choice"] = sanitized_tool_choice

        return self._model.bind_tools(tools, **kwargs)

    # Delegate all BaseChatModel methods to the wrapped model

    def _generate(
        self,
        messages: list[Any],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> Any:
        """Delegate generation to wrapped model."""
        return self._model._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    async def _agenerate(
        self,
        messages: list[Any],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> Any:
        """Delegate async generation to wrapped model."""
        return await self._model._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)

    def _stream(
        self,
        messages: list[Any],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> Any:
        """Delegate streaming to wrapped model."""
        return self._model._stream(messages, stop=stop, run_manager=run_manager, **kwargs)

    async def _astream(
        self,
        messages: list[Any],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> Any:
        """Delegate async streaming to wrapped model.

        ``BaseChatModel._astream`` is an async generator (it ``yield``s
        chunks). We must mirror that contract — ``yield`` each chunk from the
        wrapped model rather than ``return``-ing the generator, or langchain's
        ``astream`` will hit ``async for chunk in <coroutine>`` and fail with
        ``'async for' requires an object with __aiter__``.
        """
        async for chunk in self._model._astream(
            messages, stop=stop, run_manager=run_manager, **kwargs
        ):
            yield chunk

    @property
    def _llm_type(self) -> str:
        """Return LLM type from wrapped model."""
        return getattr(self._model, "_llm_type", "unknown")

    @property
    def _identifying_params(self) -> dict[str, Any]:
        """Return identifying params from wrapped model."""
        return getattr(self._model, "_identifying_params", {})

    @property
    def _model_name(self) -> str:
        """Return model name from wrapped model."""
        return getattr(self._model, "_model_name", "unknown")

    def __getattr__(self, name: str) -> Any:
        """Delegate any other attributes to the wrapped model."""
        return getattr(self._model, name)
