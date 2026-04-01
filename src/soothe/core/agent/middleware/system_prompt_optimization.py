"""System prompt optimization middleware based on LLM query classification."""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import platform as platform_module
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, NotRequired

from langchain.agents.middleware.types import AgentMiddleware, ContextT, ModelRequest, ModelResponse
from langchain_core.messages import AnyMessage, SystemMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from soothe.config import SootheConfig
    from soothe.core.unified_classifier import UnifiedClassification

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

    # -----------------------------------------------------------------------
    # XML Section Builders (RFC-104)
    # -----------------------------------------------------------------------

    def _build_environment_section(self) -> str:
        """Build <SOOTHE_ENVIRONMENT> section.

        Returns:
            Formatted XML section string with platform/shell/model info.
        """
        from soothe.config.models import get_knowledge_cutoff

        platform_name = platform_module.system()
        shell = os.environ.get("SHELL", "unknown")
        os_version = platform_module.platform()
        model = self._config.resolve_model("default")
        cutoff = get_knowledge_cutoff(model)

        content = [
            f"Platform: {platform_name}",
            f"Shell: {shell}",
            f"OS Version: {os_version}",
            f"Model: {model}",
            f"Knowledge cutoff: {cutoff}",
        ]
        return "<SOOTHE_ENVIRONMENT>\n" + "\n".join(content) + "\n</SOOTHE_ENVIRONMENT>"

    def _build_workspace_section(self, workspace: Path | None, git_status: dict[str, Any] | None) -> str:
        """Build <SOOTHE_WORKSPACE> section.

        Args:
            workspace: Current workspace path (from ContextVar or cwd).
            git_status: Git repository status dict (from runner).

        Returns:
            Formatted XML section string.
        """
        cwd = str(workspace or Path.cwd())
        is_git = git_status is not None

        content = [
            f"Primary working directory: {cwd}",
            f"Is a git repository: {is_git}",
        ]

        if git_status:
            content.append(f"Current branch: {git_status.get('branch', 'unknown')}")
            content.append(f"Main branch: {git_status.get('main_branch', 'main')}")
            status = git_status.get("status", "")
            if status:
                content.append(f"Status:\n{status}")
            commits = git_status.get("recent_commits", "")
            if commits:
                content.append(f"Recent commits:\n{commits}")

        return "<SOOTHE_WORKSPACE>\n" + "\n".join(content) + "\n</SOOTHE_WORKSPACE>"

    def _build_thread_section(self, thread_context: dict[str, Any]) -> str:
        """Build <SOOTHE_THREAD> section.

        Args:
            thread_context: Thread state dict from runner.

        Returns:
            Formatted XML section string.
        """
        thread_id = thread_context.get("thread_id", "unknown")
        goals = thread_context.get("active_goals", [])
        turns = thread_context.get("conversation_turns", 0)
        plan = thread_context.get("current_plan")

        content = [
            f"Thread ID: {thread_id}",
            f"Conversation turns: {turns}",
        ]

        if goals:
            # Limit goals to 5 items for token budget
            goals_preview = goals[:5]
            content.append(f"Active goals: {json.dumps(goals_preview)}")
        if plan:
            # Truncate plan to 100 chars
            plan_preview = str(plan)[:100]
            content.append(f"Current plan: {plan_preview}")

        return "<SOOTHE_THREAD>\n" + "\n".join(content) + "\n</SOOTHE_THREAD>"

    def _build_protocols_section(self, protocol_summary: dict[str, Any]) -> str:
        """Build <SOOTHE_PROTOCOLS> section.

        Args:
            protocol_summary: Protocol state dict from runner.

        Returns:
            Formatted XML section string, or empty string if no protocols active.
        """
        content = []

        proto_names = ["context", "memory", "planner", "policy"]
        for proto_name in proto_names:
            proto_info = protocol_summary.get(proto_name)
            if proto_info:
                proto_type = proto_info.get("type", "unknown")
                stats = proto_info.get("stats", "")
                if stats:
                    content.append(f"{proto_name.capitalize()}: {proto_type} ({stats})")
                else:
                    content.append(f"{proto_name.capitalize()}: {proto_type}")

        if not content:
            return ""  # Skip empty section

        return "<SOOTHE_PROTOCOLS>\n" + "\n".join(content) + "\n</SOOTHE_PROTOCOLS>"

    def _get_base_prompt_for_complexity(self, complexity: str) -> str:
        """Get base prompt template for complexity level (without XML sections).

        Args:
            complexity: One of "chitchat", "medium", "complex" (from LLM classification).

        Returns:
            Formatted base prompt string with assistant_name and current date.
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

    def _get_prompt_for_complexity(self, complexity: str, state: dict[str, Any] | None = None) -> str:
        """Get prompt with XML context sections for complexity level.

        Args:
            complexity: One of "chitchat", "medium", "complex".
            state: Request state with context information (workspace, git_status, etc.).

        Returns:
            Base prompt with appended XML sections for medium/complex.
        """
        base_prompt = self._get_base_prompt_for_complexity(complexity)

        # Chitchat: no context injection
        if complexity == "chitchat":
            return base_prompt

        # Medium and complex: inject context sections
        state = state or {}
        sections = []

        # Environment section (always for medium/complex)
        sections.append(self._build_environment_section())

        # Workspace section
        workspace = state.get("workspace")
        git_status = state.get("git_status")
        sections.append(self._build_workspace_section(workspace, git_status))

        # Thread and protocols only for complex
        if complexity == "complex":
            thread_context = state.get("thread_context", {})
            if thread_context:
                sections.append(self._build_thread_section(thread_context))

            protocol_summary = state.get("protocol_summary", {})
            if protocol_summary:
                proto_section = self._build_protocols_section(protocol_summary)
                if proto_section:
                    sections.append(proto_section)

        return base_prompt + "\n\n" + "\n\n".join(sections)

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
