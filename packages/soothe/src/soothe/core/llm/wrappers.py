"""Generic model wrappers for limited OpenAI-compatible providers.

These wrappers handle providers with limited OpenAI API compatibility:
- Only support string tool_choice values, not object format
- Require json_schema format, not json_object format
- May return structured output in alternative fields

Note: LMStudio-specific handling is in dedicated backend `soothe.backends.lms_openai`
with specialized reasoning_content field extraction.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable

from soothe.utils.text_preview import preview_first

logger = logging.getLogger(__name__)


class JsonSchemaModelWrapper(Runnable):
    """Wrapper that injects json_schema response_format and parses JSON output.

    Limited providers require response_format={"type": "json_schema"} not {"type": "json_object"}.
    Unlike langchain's built-in structured output, we manually parse the JSON response
    into a Pydantic object.

    Note: For LMStudio providers, use `soothe.backends.lms_openai.LMSJsonSchemaWrapper`
    which checks reasoning_content field.

    Args:
        model: The base model to wrap.
        response_format: The json_schema format dict to inject.
        schema: The Pydantic model class for parsing the response.
    """

    def __init__(self, model: BaseChatModel, response_format: dict[str, Any], schema: Any) -> None:
        """Initialize the wrapper.

        Args:
            model: The base model to wrap.
            response_format: The json_schema format dict to inject on invoke.
            schema: The Pydantic model class for parsing JSON responses.
        """
        self._model = model
        self._response_format = response_format
        self._schema = schema

    def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:  # noqa: ARG002
        """Inject response_format, invoke model, and parse JSON response.

        Args:
            input: Messages or prompt to send.
            config: Runnable config (unused).
            **kwargs: Additional invoke parameters.

        Returns:
            Parsed Pydantic object from the JSON response.
        """
        kwargs["response_format"] = self._response_format
        response = self._model.invoke(input, **kwargs)

        # Extract JSON content from AIMessage and parse into Pydantic object
        try:
            if hasattr(response, "content") and response.content:
                json_str = response.content
            # Fallback: check reasoning_content field (some providers)
            elif hasattr(response, "reasoning_content") and response.reasoning_content:
                json_str = response.reasoning_content
                logger.debug("JSON found in reasoning_content field")
            else:
                json_str = str(response)

            # Check for empty response
            if not json_str or json_str.strip() == "":
                raise ValueError(
                    f"Provider returned empty response for json_schema format. "
                    f"Response object: {type(response).__name__}, "
                    f"has content: {hasattr(response, 'content')}, "
                    f"has reasoning_content: {hasattr(response, 'reasoning_content')}"
                )

            # Log response for debugging
            logger.debug(
                "Provider response for json_schema: content='%s', reasoning_content='%s'",
                preview_first(str(response.content) if hasattr(response, "content") else "", 100),
                preview_first(
                    str(response.reasoning_content)
                    if hasattr(response, "reasoning_content")
                    else "",
                    100,
                ),
            )

            # Parse and validate JSON
            json_dict = json.loads(json_str)
            return self._schema.model_validate(json_dict)
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
                    str(response.reasoning_content)
                    if hasattr(response, "reasoning_content")
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

    async def ainvoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:  # noqa: ARG002
        """Async version of invoke with response_format injection and JSON parsing.

        Args:
            input: Messages or prompt to send.
            config: Runnable config (unused).
            **kwargs: Additional invoke parameters.

        Returns:
            Parsed Pydantic object from the JSON response.
        """
        kwargs["response_format"] = self._response_format
        response = await self._model.ainvoke(input, **kwargs)

        # Extract and parse JSON
        try:
            if hasattr(response, "content") and response.content:
                json_str = response.content
            # Fallback: check reasoning_content field (some providers)
            elif hasattr(response, "reasoning_content") and response.reasoning_content:
                json_str = response.reasoning_content
                logger.debug("JSON found in reasoning_content field")
            else:
                json_str = str(response)

            # Check for empty response
            if not json_str or json_str.strip() == "":
                raise ValueError(
                    f"Provider returned empty response for json_schema format. "
                    f"Response object: {type(response).__name__}, "
                    f"has content: {hasattr(response, 'content')}, "
                    f"has reasoning_content: {hasattr(response, 'reasoning_content')}"
                )

            # Log response for debugging
            logger.debug(
                "Provider response for json_schema: content='%s', reasoning_content='%s'",
                preview_first(str(response.content) if hasattr(response, "content") else "", 100),
                preview_first(
                    str(response.reasoning_content)
                    if hasattr(response, "reasoning_content")
                    else "",
                    100,
                ),
            )

            # Parse and validate JSON
            json_dict = json.loads(json_str)
            return self._schema.model_validate(json_dict)
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
                    str(response.reasoning_content)
                    if hasattr(response, "reasoning_content")
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

    Note: For LMStudio providers, use `soothe.backends.lms_openai.LMSOpenAIModelWrapper`
    which includes reasoning_content field handling.

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
        """Convert json_mode to json_schema format for limited provider compatibility.

        Limited providers reject response_format={"type": "json_object"} but accept
        response_format={"type": "json_schema", "json_schema": {...}}.

        Args:
            schema: Pydantic model class defining the output schema.
            **kwargs: Method parameter ('json_mode' intercepted and converted).

        Returns:
            Runnable with structured output using json_schema format.
        """
        method = kwargs.get("method", "json_mode")

        logger.debug(
            "LimitedProviderModelWrapper converting json_mode to json_schema for provider '%s'",
            self._provider_name,
        )

        if method == "json_mode":
            # Convert pydantic schema to JSON schema format
            try:
                json_schema = schema.model_json_schema()

                # Build the response_format dict that limited providers accept
                response_format = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema.__name__,
                        "strict": True,
                        "schema": json_schema,
                    },
                }

                # Inject response_format into the model's invoke kwargs
                return JsonSchemaModelWrapper(self._model, response_format, schema)
            except Exception:
                logger.debug(
                    "Failed to convert schema to json_schema format, falling back",
                    exc_info=True,
                )
                # Fallback: return the model and hope the caller handles it
                return self._model

        # For other methods, just delegate (they will likely fail but let caller handle)
        return self._model.with_structured_output(schema, **kwargs)

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


def wrap_model_if_needed(
    model: BaseChatModel,
    provider_name: str,
    supports_advanced_tool_choice: bool = True,  # noqa: ARG001
) -> BaseChatModel:
    """Compatibility helper - no longer wraps models.

    Args:
        model: The original model (returned unchanged).
        provider_name: Provider name (unused).
        supports_advanced_tool_choice: Ignored (unused).

    Returns:
        Original model unchanged.
    """
    return model
