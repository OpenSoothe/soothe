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

    from soothe.config import SootheConfig
    from soothe.core.unified_classifier import UnifiedClassification
    from soothe.protocols.context import ContextProjection
    from soothe.protocols.memory import MemoryItem

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

    def _get_base_prompt_core(self, complexity: str) -> str:
        """Behavioral system prompt for complexity (no volatile date line; RFC-104 cache order)."""
        from soothe.config import _DEFAULT_SYSTEM_PROMPT, _MEDIUM_SYSTEM_PROMPT, _SIMPLE_SYSTEM_PROMPT

        if complexity == "chitchat":
            return _SIMPLE_SYSTEM_PROMPT.format(assistant_name=self._config.assistant_name)
        if complexity == "medium":
            return _MEDIUM_SYSTEM_PROMPT.format(assistant_name=self._config.assistant_name)
        if self._config.system_prompt:
            return self._config.system_prompt.format(assistant_name=self._config.assistant_name)
        return _DEFAULT_SYSTEM_PROMPT.format(assistant_name=self._config.assistant_name)

    @staticmethod
    def _current_date_line() -> str:
        now = dt.datetime.now(dt.UTC).astimezone()
        return f"Today's date is {now.strftime('%Y-%m-%d')}."

    def _get_prompt_for_complexity(self, complexity: str, state: dict[str, Any] | None = None) -> str:
        """Get prompt with XML context sections for complexity level.

        Args:
            complexity: One of "chitchat", "medium", "complex".
            state: Request state with context information (workspace, git_status, etc.).

        Returns:
            Base prompt with appended XML sections for medium/complex.
        """
        from soothe.core.prompts.context_xml import build_context_sections_for_complexity

        base_core = self._get_base_prompt_core(complexity)
        date_line = self._current_date_line()

        # Chitchat: no context injection
        if complexity == "chitchat":
            return f"{base_core}\n\n{date_line}"

        # Build sections list
        sections = [base_core]

        # Environment, workspace, thread, protocols (existing logic)
        sections.extend(
            build_context_sections_for_complexity(
                config=self._config,
                complexity=complexity,  # type: ignore[arg-type]
                state=state or {},
                include_workspace_extras=False,
            )
        )

        # NEW (RFC-208): Context projection and memories (medium/complex only)
        if state:
            projection = state.get("context_projection")
            if projection and projection.entries:
                sections.append(self._build_context_section(projection))

            memories = state.get("recalled_memories")
            if memories:
                sections.append(self._build_memory_section(memories))

        sections.append(date_line)
        return "\n\n".join(sections)

    def _get_domain_scoped_prompt(
        self, classification: UnifiedClassification, state: dict[str, Any] | None = None
    ) -> str:
        """Build a prompt for the given classification.

        Falls back to complexity-only optimization since capability_domains
        were removed in RFC-0016 (unified planning).

        Args:
            classification: LLM classification with task_complexity.
            state: Request state with context information.

        Returns:
            Formatted prompt based on complexity level with XML sections.
        """
        return self._get_prompt_for_complexity(classification.task_complexity, state)

    def _build_context_section(self, projection: ContextProjection) -> str:
        """Build <context> XML for context projection entries.

        Args:
            projection: Context projection with relevance-ranked entries.

        Returns:
            XML section string with top 10 entries, 200 chars each.

        Example:
            >>> projection = ContextProjection(entries=[
            ...     ContextEntry(source="tool", content="Found 5 files", ...)
            ... ])
            >>> print(self._build_context_section(projection))
            <context>
            - [tool] Found 5 files
            </context>
        """
        entries = projection.entries[:10]
        lines = [f"- [{e.source}] {e.content[:200]}" for e in entries]
        joined = "\n".join(lines)
        return f"<context>\n{joined}\n</context>"

    def _build_memory_section(self, memories: list[MemoryItem]) -> str:
        """Build <memory> XML for recalled memories.

        Args:
            memories: Recalled memory items from MemoryProtocol.

        Returns:
            XML section string with top 5 memories, 200 chars each.

        Example:
            >>> memories = [MemoryItem(content="User prefers Python", ...)]
            >>> print(self._build_memory_section(memories))
            <memory>
            - [thread_123] User prefers Python
            </memory>
        """
        lines = [f"- [{m.source_thread or 'unknown'}] {m.content[:200]}" for m in memories[:5]]
        joined = "\n".join(lines)
        return f"<memory>\n{joined}\n</memory>"

    def modify_request(self, request: ModelRequest[ContextT]) -> ModelRequest[ContextT]:
        """Replace system prompt based on LLM classification.

        Uses complexity-based prompt optimization with XML context injection.

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
            return request

        complexity = classification.task_complexity
        logger.info(
            "Optimizing prompt: complexity=%s, plan_only=%s",
            complexity,
            classification.is_plan_only if hasattr(classification, "is_plan_only") else False,
        )

        # Extract state for XML section building
        state_dict: dict[str, Any] = {}
        if hasattr(request.state, "get"):
            state_dict = {
                "workspace": request.state.get("workspace"),
                "git_status": request.state.get("git_status"),
                "thread_context": request.state.get("thread_context", {}),
                "protocol_summary": request.state.get("protocol_summary", {}),
            }

        optimized_prompt = self._get_prompt_for_complexity(complexity, state_dict)

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
