"""System prompt optimization middleware based on LLM query classification."""

from __future__ import annotations

import datetime as dt
import logging
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware.types import AgentMiddleware, ContextT, ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from soothe.config import SootheConfig
    from soothe.core.unified_classifier import UnifiedClassification

logger = logging.getLogger(__name__)


class SystemPromptOptimizationMiddleware(AgentMiddleware):
    """Dynamically adjust system prompts based on LLM query classification.

    Uses runtime_complexity from UnifiedClassification (determined by fast LLM)
    to select appropriate prompt verbosity:
    - simple: Minimal prompt for greetings and quick questions
    - medium: Standard prompt with guidelines
    - complex: Full prompt with all context

    This middleware expects unified_classification to be present in the agent
    state before the first model call. It should be injected by the runner
    during the pre-stream phase.

    Args:
        config: Soothe configuration for resolving prompt templates.
    """

    def __init__(self, config: SootheConfig) -> None:
        """Initialize the system prompt optimization middleware.

        Args:
            config: Soothe configuration instance.
        """
        self._config = config

    def _get_prompt_for_complexity(self, complexity: str) -> str:
        """Get appropriate prompt template for complexity level.

        Args:
            complexity: One of "simple", "medium", "complex" (from LLM classification).

        Returns:
            Formatted prompt string with assistant_name and current date.
        """
        from soothe.config import _DEFAULT_SYSTEM_PROMPT, _MEDIUM_SYSTEM_PROMPT, _SIMPLE_SYSTEM_PROMPT

        # Get base prompt for complexity level
        if complexity == "simple":
            base_prompt = _SIMPLE_SYSTEM_PROMPT.format(assistant_name=self._config.assistant_name)
        elif complexity == "medium":
            base_prompt = _MEDIUM_SYSTEM_PROMPT.format(assistant_name=self._config.assistant_name)
        elif self._config.system_prompt:
            # Complex with custom prompt
            base_prompt = self._config.system_prompt.format(assistant_name=self._config.assistant_name)
        else:
            # Complex with default prompt
            base_prompt = _DEFAULT_SYSTEM_PROMPT.format(assistant_name=self._config.assistant_name)

        # Inject current date (consistent with resolve_system_prompt behavior)
        now = dt.datetime.now(dt.UTC).astimezone()
        current_date = now.strftime("%Y-%m-%d")

        return f"{base_prompt}\n\nToday's date is {current_date}."

    def modify_request(self, request: ModelRequest[ContextT]) -> ModelRequest[ContextT]:
        """Replace system prompt based on LLM classification.

        Args:
            request: Model request to modify.

        Returns:
            Modified request with optimized system prompt.
        """
        # Check if optimization is enabled
        if not self._config.performance.enabled or not self._config.performance.optimize_system_prompts:
            return request

        # Get classification from state (determined by UnifiedClassifier's LLM)
        classification: UnifiedClassification | None = request.state.get("unified_classification")
        if not classification:
            logger.debug("No classification found in state, using default prompt")
            return request

        complexity = classification.runtime_complexity
        logger.info("Optimizing system prompt for %s query based on LLM classification", complexity)

        # Get appropriate prompt
        optimized_prompt = self._get_prompt_for_complexity(complexity)

        # Replace the entire system message
        new_system_message = SystemMessage(content=optimized_prompt)

        return request.override(system_message=new_system_message)

    def wrap_model_call(
        self,
        request: ModelRequest[ContextT],
        handler: Callable[[ModelRequest[ContextT]], ModelResponse[Any]],
    ) -> ModelResponse[Any]:
        """Wrap model call to optimize system prompt.

        Args:
            request: Model request being processed.
            handler: Handler function to call with modified request.

        Returns:
            Model response from handler.
        """
        modified_request = self.modify_request(request)
        return handler(modified_request)

    async def awrap_model_call(
        self,
        request: ModelRequest[ContextT],
        handler: Callable[[ModelRequest[ContextT]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        """Async wrap model call to optimize system prompt.

        Args:
            request: Model request being processed.
            handler: Async handler function to call with modified request.

        Returns:
            Model response from handler.
        """
        modified_request = self.modify_request(request)
        return await handler(modified_request)
