"""Generic model wrappers for limited OpenAI-compatible providers.

These wrappers handle providers with limited OpenAI API compatibility:
- Only support string tool_choice values, not object format
- Require json_schema format, not json_object format
- May return structured output in alternative fields (reasoning_content)

Limited OpenAI providers (provider_type='limited_openai'):
- LMStudio, MLXServer, certain GLM deployments
- Return structured JSON in reasoning_content field (thinking tokens)
- Accept json_schema response_format but may return empty content field
"""

from __future__ import annotations

import json
import logging
from typing import Any

import jsonschema
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable
from pydantic import BaseModel

from soothe.utils.llm.schema_wire import build_json_schema_response_format, validate_response_schema
from soothe.utils.text_preview import preview_first

logger = logging.getLogger(__name__)


def _extract_json_str_from_response(response: Any) -> str:
    """Extract JSON text from an AIMessage-like provider response."""
    if hasattr(response, "content") and response.content:
        return str(response.content)
    if (
        hasattr(response, "additional_kwargs")
        and "reasoning_content" in response.additional_kwargs
        and response.additional_kwargs["reasoning_content"]
    ):
        logger.debug("JSON found in reasoning_content field (additional_kwargs)")
        return str(response.additional_kwargs["reasoning_content"])
    return str(response)


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
        json_dict = json.loads(json_str)
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


class LimitedProviderModelWrapper(BaseChatModel):
    """Wrapper that converts json_mode to json_schema for limited provider compatibility.

    Handles providers with limited OpenAI API support:
    - Rejects response_format={"type": "json_object"}
    - Accepts response_format={"type": "json_schema", ...}
    - Only accepts string tool_choice values: "none", "auto", "required"

    Limited OpenAI providers (provider_type='limited_openai'):
    - LMStudio, MLXServer, GLM deployments with thinking tokens
    - Return structured JSON in reasoning_content field

    Args:
        model: The original BaseChatModel to wrap.
        provider_name: Provider name for logging purposes.
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
        """Convert all methods to json_schema format for limited provider compatibility.

        Limited OpenAI providers MUST use json_schema format because:
        - Reject response_format={"type": "json_object"}
        - Return structured JSON in reasoning_content (additional_kwargs)
        - Langchain's default function_calling/json_mode don't handle reasoning_content

        We intercept ALL methods and convert to JsonSchemaModelWrapper which:
        - Injects response_format={"type": "json_schema", ...}
        - Checks additional_kwargs["reasoning_content"] for JSON parsing

        Args:
            schema: Pydantic model class or client JSON Schema dict.
            **kwargs: ``schema_name``, ``strict``, and method (intercepted).

        Returns:
            JsonSchemaModelWrapper with reasoning_content handling.
        """
        method = kwargs.pop("method", "json_mode")
        schema_name = kwargs.pop("schema_name", None)
        strict = kwargs.pop("strict", True)

        logger.debug(
            "LimitedProviderModelWrapper converting method='%s' to json_schema for provider '%s'",
            method,
            self._provider_name,
        )

        # ALWAYS use JsonSchemaModelWrapper for limited_openai providers
        # This ensures we check additional_kwargs["reasoning_content"] field
        try:
            if isinstance(schema, dict):
                wire_schema = validate_response_schema(schema)
                from soothe.utils.llm.schema_wire import resolve_schema_name

                name = resolve_schema_name(wire_schema, schema_name)
                response_format = build_json_schema_response_format(
                    wire_schema,
                    name=name,
                    strict=bool(strict),
                )
                return JsonSchemaModelWrapper(
                    self._model,
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
                self._model,
                response_format,
                schema,
                strict=bool(strict),
            )
        except Exception:
            logger.debug(
                "Failed to convert schema to json_schema format, falling back",
                exc_info=True,
            )
            # Fallback: delegate to base model (may fail with reasoning_content)
            return self._model.with_structured_output(schema, method=method, **kwargs)

    def bind_tools(self, tools: list[Any], **kwargs: Any) -> Any:
        """Intercept tool_choice parameter for limited providers.

        Removes object-form tool_choice and converts to string if needed.
        Limited providers only accept string values: "none", "auto", "required".

        Args:
            tools: List of tool definitions.
            **kwargs: Additional parameters (tool_choice intercepted).

        Returns:
            Model with sanitized tool_choice.
        """
        # Intercept tool_choice parameter
        if "tool_choice" in kwargs:
            tool_choice = kwargs["tool_choice"]

            # If tool_choice is a dict/object, sanitize it for limited providers
            if isinstance(tool_choice, dict):
                logger.debug(
                    "LimitedProviderModelWrapper sanitizing object-form tool_choice for %s (provider=%s)",
                    tool_choice,
                    self._provider_name,
                )
                # Convert to "auto" for best compatibility
                kwargs["tool_choice"] = "auto"

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
        """Delegate async streaming to wrapped model."""
        return await self._model._astream(messages, stop=stop, run_manager=run_manager, **kwargs)

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
