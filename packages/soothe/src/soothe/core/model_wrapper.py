"""Model wrapper for limited OpenAI-compatible provider support.

Intercepts with_structured_output calls and converts json_mode to json_schema format
for providers like LMStudio that reject response_format={"type": "json_object"}.

Also sanitizes tool_choice parameters in bind_tools to avoid object-form errors.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable

logger = logging.getLogger(__name__)


class JsonSchemaModelWrapper(Runnable):
    """Wrapper that injects json_schema response_format and parses JSON output.

    LMStudio requires response_format={"type": "json_schema"} not {"type": "json_object"}.
    Unlike langchain's built-in structured output, we manually parse the JSON response
    into a Pydantic object.

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
        import json

        # Inject response_format into kwargs
        kwargs["response_format"] = self._response_format

        # Call the base model with the injected response_format
        response = self._model.invoke(input, **kwargs)

        # Extract JSON content from AIMessage and parse into Pydantic object
        try:
            if hasattr(response, "content"):
                # response is an AIMessage, extract content string
                json_str = response.content
            else:
                # response might already be a string or dict
                json_str = str(response)

            # Parse JSON string into dict
            json_dict = json.loads(json_str)

            # Validate and convert to Pydantic object using the schema
            return self._schema.model_validate(json_dict)
        except Exception as e:
            logger.error(
                "Failed to parse JSON response from LMStudio: %s\nResponse: %s",
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
        import json

        kwargs["response_format"] = self._response_format
        response = await self._model.ainvoke(input, **kwargs)

        # Extract and parse JSON
        try:
            if hasattr(response, "content"):
                json_str = response.content
            else:
                json_str = str(response)

            json_dict = json.loads(json_str)
            return self._schema.model_validate(json_dict)
        except Exception as e:
            logger.error(
                "Failed to parse JSON response from LMStudio: %s\nResponse: %s",
                e,
                response,
            )
            raise

    def __getattr__(self, name: str) -> Any:
        """Delegate any other attributes to the wrapped model."""
        return getattr(self._model, name)


class LimitedProviderModelWrapper(BaseChatModel):
    """Wrapper that converts json_mode to json_schema for LMStudio compatibility.

    Delegates all other methods to the wrapped model.

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
        # Properties (_llm_type, _identifying_params, _model_name) are defined
        # as @property methods below and delegate to the wrapped model

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
        """Convert json_mode to json_schema format for LMStudio compatibility.

        LMStudio rejects response_format={"type": "json_object"} but accepts
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

        # If method is json_mode, we need to convert to json_schema
        # LMStudio only accepts {"type": "json_schema"} not {"type": "json_object"}
        if method == "json_mode":
            # Convert pydantic schema to JSON schema format
            try:
                # Get the JSON schema from the pydantic model
                json_schema = schema.model_json_schema()

                # Build the response_format dict that LMStudio accepts
                response_format = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema.__name__,
                        "strict": True,
                        "schema": json_schema,
                    },
                }

                # Inject response_format into the model's invoke kwargs
                # We need to wrap the model to inject this parameter and parse JSON
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

    def bind_tools(self, tools: list[Any], **kwargs: Any) -> Any:
        """Intercept tool_choice parameter for limited providers.

        Removes object-form tool_choice and converts to string if needed.
        LMStudio only accepts string values: "none", "auto", "required".
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

    def __getattr__(self, name: str) -> Any:
        """Delegate any other attributes to the wrapped model."""
        return getattr(self._model, name)


def wrap_model_if_needed(
    model: BaseChatModel,
    provider_name: str,
    supports_advanced_tool_choice: bool,
) -> BaseChatModel:
    """Wrap model if provider doesn't support advanced tool_choice.

    Args:
        model: The original model.
        provider_name: Provider name for logging.
        supports_advanced_tool_choice: Whether the provider supports full OpenAI tool_choice.

    Returns:
        Wrapped model if provider is limited, otherwise original model.
    """
    if not supports_advanced_tool_choice:
        logger.info(
            "Wrapping model for limited provider '%s' (json_mode will be converted to json_schema)",
            provider_name,
        )
        return LimitedProviderModelWrapper(model, provider_name)

    return model
