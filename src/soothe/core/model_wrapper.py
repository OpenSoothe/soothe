"""Model wrapper for limited OpenAI-compatible provider support.

Intercepts with_structured_output calls and forces json_mode for providers
that don't support the full OpenAI-style tool_choice object format (LMStudio, Ollama, etc.).

This prevents BadRequestError: "Invalid tool_choice type: 'object'. Supported string values: none, auto, required"
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)


class LimitedProviderModelWrapper(BaseChatModel):
    """Wrapper that forces json_mode for structured output on limited providers.

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

        # Copy all properties from the wrapped model
        for attr in ("_llm_type", "_identifying_params", "_model_name"):
            if hasattr(model, attr):
                setattr(self, attr, getattr(model, attr))

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
        """Force json_mode for structured output on limited providers.

        Args:
            schema: The schema for structured output.
            **kwargs: Additional arguments (method is intercepted and ignored).

        Returns:
            Model with json_mode forced for structured output.
        """
        logger.debug(
            "LimitedProviderModelWrapper forcing json_mode for structured output (provider=%s)",
            self._provider_name,
        )

        # Force json_mode instead of function calling
        try:
            return self._model.with_structured_output(schema, method="json_mode")
        except Exception:
            logger.debug("json_mode init failed, falling back to default method", exc_info=True)
            # Fallback: try without specifying method
            return self._model.with_structured_output(schema)

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
        """Delegate tool binding to wrapped model."""
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
            "Wrapping model for limited provider '%s' (json_mode will be forced for structured output)",
            provider_name,
        )
        return LimitedProviderModelWrapper(model, provider_name)

    return model
