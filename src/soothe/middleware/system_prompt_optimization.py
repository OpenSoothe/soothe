"""System prompt optimization middleware based on LLM query classification."""

from __future__ import annotations

import datetime as dt
import logging
from typing import TYPE_CHECKING, Annotated, Any, NotRequired

from langchain.agents.middleware.types import AgentMiddleware, ContextT, ModelRequest, ModelResponse
from langchain_core.messages import AnyMessage, SystemMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from soothe.cognition import UnifiedClassification
    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)


class _OptimizationState(TypedDict):
    """State schema for SystemPromptOptimizationMiddleware.

    LangGraph merges all middleware state schemas to build the final graph state.
    This schema declares the unified_classification field so it propagates correctly.

    The ``messages`` key MUST use ``Annotated[..., add_messages]`` to preserve
    the reducer from the base ``AgentState``.  A plain ``list`` annotation
    silently downgrades the channel to ``LastValue``, which raises
    ``InvalidUpdateError`` when parallel tool calls return in the same step.
    """

    messages: Annotated[list[AnyMessage], add_messages]
    unified_classification: NotRequired[Any]  # Type: UnifiedClassification


class SystemPromptOptimizationMiddleware(AgentMiddleware):
    """Dynamically adjust system prompts based on LLM query classification.

    Uses task_complexity from UnifiedClassification (determined by fast LLM)
    to select appropriate prompt verbosity:
    - chitchat: Minimal prompt for greetings and quick questions
    - medium: Standard prompt with guidelines
    - complex: Full prompt with all context

    This middleware expects unified_classification to be present in the agent
    state before the first model call. It should be injected by the runner
    during the pre-stream phase.

    Args:
        config: Soothe configuration for resolving prompt templates.
    """

    state_schema = _OptimizationState

    def __init__(self, config: SootheConfig) -> None:
        """Initialize the system prompt optimization middleware.

        Args:
            config: Soothe configuration instance.
        """
        self._config = config

    def _get_prompt_for_complexity(self, complexity: str) -> str:
        """Get appropriate prompt template for complexity level.

        Args:
            complexity: One of "chitchat", "medium", "complex" (from LLM classification).

        Returns:
            Formatted prompt string with assistant_name and current date.
        """
        from soothe.config import _DEFAULT_SYSTEM_PROMPT, _MEDIUM_SYSTEM_PROMPT, _SIMPLE_SYSTEM_PROMPT

        if complexity == "chitchat":
            base_prompt = _SIMPLE_SYSTEM_PROMPT.format(assistant_name=self._config.assistant_name)
        elif complexity == "medium":
            base_prompt = _MEDIUM_SYSTEM_PROMPT.format(assistant_name=self._config.assistant_name)
        elif self._config.system_prompt:
            base_prompt = self._config.system_prompt.format(assistant_name=self._config.assistant_name)
        else:
            base_prompt = _DEFAULT_SYSTEM_PROMPT.format(assistant_name=self._config.assistant_name)

        now = dt.datetime.now(dt.UTC).astimezone()
        current_date = now.strftime("%Y-%m-%d")

        return f"{base_prompt}\n\nToday's date is {current_date}."

    def _get_domain_scoped_prompt(self, classification: UnifiedClassification) -> str:
        """Build a prompt for the given classification.

        Falls back to complexity-only optimization since capability_domains
        were removed in RFC-0016 (unified planning).

        Args:
            classification: LLM classification with task_complexity.

        Returns:
            Formatted prompt based on complexity level.
        """
        # Just use complexity-based prompts
        return self._get_prompt_for_complexity(classification.task_complexity)

    def modify_request(self, request: ModelRequest[ContextT]) -> ModelRequest[ContextT]:
        """Replace system prompt based on LLM classification.

        Uses complexity-based prompt optimization.

        Args:
            request: Model request to modify.

        Returns:
            Modified request with optimized system prompt.
        """
        if (
            not self._config.performance.enabled
            or not self._config.performance.optimize_system_prompts
            or not self._config.performance.unified_classification
        ):
            logger.debug(
                "System prompt optimization disabled (enabled=%s, optimize=%s, classification=%s)",
                self._config.performance.enabled,
                self._config.performance.optimize_system_prompts,
                self._config.performance.unified_classification,
            )
            return request

        classification: UnifiedClassification | None = request.state.get("unified_classification")
        if not classification:
            logger.debug(
                "No classification found in state (keys=%s), using default prompt",
                list(request.state.keys()) if hasattr(request.state, "keys") else "N/A",
            )
            return request

        complexity = classification.task_complexity
        logger.info(
            "Optimizing prompt: complexity=%s, plan_only=%s",
            complexity,
            classification.is_plan_only if hasattr(classification, "is_plan_only") else False,
        )

        optimized_prompt = self._get_prompt_for_complexity(complexity)

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
