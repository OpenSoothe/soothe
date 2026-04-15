"""System prompt optimization middleware based on LLM query classification."""

from __future__ import annotations

import datetime as dt
import logging
from typing import TYPE_CHECKING, Annotated, Any, NotRequired

from langchain.agents.middleware.types import AgentMiddleware, ContextT, ModelRequest, ModelResponse
from langchain_core.messages import AnyMessage, SystemMessage, ToolMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from soothe.utils.text_preview import preview_first

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from soothe.config import SootheConfig
    from soothe.core.tool_context_registry import ToolContextRegistry
    from soothe.core.tool_trigger_registry import ToolTriggerRegistry
    from soothe.core.unified_classifier import UnifiedClassification
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

    def __init__(
        self,
        config: SootheConfig,
        tool_trigger_registry: ToolTriggerRegistry | None = None,
        tool_context_registry: ToolContextRegistry | None = None,
    ) -> None:
        """Initialize the system prompt optimization middleware.

        Args:
            config: Soothe configuration instance.
            tool_trigger_registry: Optional registry for tool→section triggers.
            tool_context_registry: Optional registry for tool→context fragments.
        """
        self._config = config
        self._tool_trigger_registry = tool_trigger_registry
        self._tool_context_registry = tool_context_registry

    def _build_environment_section(self) -> str:
        """Build <ENVIRONMENT> section (static, always present for medium/complex).

        Returns:
            XML section with platform, shell, model, knowledge cutoff.
        """
        from soothe.core.prompts.context_xml import build_soothe_environment_section

        model = self._config.resolve_model("default")
        return build_soothe_environment_section(model=model)

    def _extract_recent_tool_calls(self, messages: list[AnyMessage], window: int = 10) -> list[str]:
        """Extract unique tool names from recent ToolMessages.

        Args:
            messages: Conversation message history.
            window: Number of recent messages to inspect.

        Returns:
            Unique tool names from tool calls, most recent first.
        """
        if not messages:
            return []

        recent_messages = messages[-window:] if len(messages) > window else messages
        tool_names = []

        for msg in reversed(recent_messages):
            if isinstance(msg, ToolMessage):
                # Extract tool name from ToolMessage
                tool_name = msg.name
                if tool_name and tool_name not in tool_names:
                    tool_names.append(tool_name)

        # Limit to prevent bloat
        return tool_names[:5]

    def _should_inject_workspace(self, state: dict[str, Any]) -> bool:
        """Determine if WORKSPACE section should be injected.

        Conditions:
        1. Workspace tools were recently used
        2. Workspace is actually set

        Args:
            state: Request state.

        Returns:
            True if WORKSPACE should be injected.
        """
        if not self._tool_trigger_registry:
            return False

        messages = state.get("messages", [])
        recent_tools = self._extract_recent_tool_calls(messages)
        triggered = self._tool_trigger_registry.get_triggered_sections(recent_tools)

        if "WORKSPACE" not in triggered:
            return False

        # Check if workspace is set
        workspace = state.get("workspace")
        return workspace is not None

    def _should_inject_thread(self, state: dict[str, Any]) -> bool:
        """Determine if THREAD section should be injected.

        Conditions:
        1. Multi-turn conversation (messages > 1)
        2. OR active goals exist

        Args:
            state: Request state.

        Returns:
            True if THREAD should be injected.
        """
        # Check conversation turns
        messages = state.get("messages", [])
        if len(messages) > 1:
            return True

        # Check active goals
        active_goals = state.get("active_goals", [])
        if active_goals:
            return True

        return False

    def _build_dynamic_sections(self, state: dict[str, Any]) -> str:
        """Build all dynamic context sections based on triggers.

        Args:
            state: Request state with messages and context.

        Returns:
            Dynamic sections string with separator, or empty string.
        """
        if not state or not self._tool_trigger_registry:
            return ""

        messages = state.get("messages", [])
        recent_tools = self._extract_recent_tool_calls(messages)
        triggered_sections = self._tool_trigger_registry.get_triggered_sections(recent_tools)

        # Build sections list
        sections = []

        # WORKSPACE (tool-triggered + condition)
        if "WORKSPACE" in triggered_sections and self._should_inject_workspace(state):
            workspace_section = self._build_workspace_section(
                state.get("workspace"), state.get("git_status")
            )
            if workspace_section:
                sections.append(workspace_section)

        # THREAD (state-triggered)
        if self._should_inject_thread(state):
            thread_section = self._build_thread_section(state.get("thread_context", {}))
            if thread_section:
                sections.append(thread_section)

        # PROTOCOLS (tool-triggered)
        if "PROTOCOLS" in triggered_sections:
            protocols_section = self._build_protocols_section(state.get("protocol_summary", {}))
            if protocols_section:
                sections.append(protocols_section)

        # Tool-specific sections (from tool_context_registry)
        if self._tool_context_registry:
            for tool_name in recent_tools:
                tool_section = self._tool_context_registry.get_system_context(tool_name)
                if tool_section:
                    sections.append(tool_section.strip())

        if not sections:
            return ""

        # Join with separator (UPPERCASE)
        separator = "\n--- TOOL-SPECIFIC CONTEXT (DYNAMIC) ---\n"
        return separator + "\n\n".join(sections) + "\n"

    def _get_base_prompt_core(self, complexity: str) -> str:
        """Behavioral system prompt for complexity (no volatile date line; RFC-104 cache order)."""
        from soothe.config import (
            _DEFAULT_SYSTEM_PROMPT,
            _MEDIUM_SYSTEM_PROMPT,
            _SIMPLE_SYSTEM_PROMPT,
        )

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

    def _get_prompt_for_complexity(
        self, complexity: str, state: dict[str, Any] | None = None
    ) -> str:
        """Get prompt with separated static and dynamic context sections.

        Static Zone (always injected):
        - Base behavioral prompt
        - <ENVIRONMENT> section

        Dynamic Zone (tool/condition-triggered):
        - <WORKSPACE> when workspace tools used AND workspace set
        - <THREAD> when multi-turn or active goals
        - Tool-specific fragments when tools invoked

        Args:
            complexity: One of "chitchat", "medium", "complex".
            state: Request state with context information (workspace, git_status, etc.).

        Returns:
            Base prompt with static and dynamic sections properly separated.
        """
        from soothe.core.prompts.context_xml import build_context_sections_for_complexity

        base_core = self._get_base_prompt_core(complexity)
        date_line = self._current_date_line()

        # Chitchat: only base + ENVIRONMENT + date
        if complexity == "chitchat":
            env_section = self._build_environment_section()
            return f"{base_core}\n\n{env_section}\n\n{date_line}"

        # Build STATIC sections
        static_sections = [base_core]

        # ENVIRONMENT (always static)
        env_sections = build_context_sections_for_complexity(
            config=self._config,
            complexity=complexity,  # type: ignore[arg-type]
            state=state or {},
            include_workspace_extras=False,
        )
        # Only include ENVIRONMENT from the returned sections
        # (WORKSPACE, THREAD, PROTOCOLS will be handled dynamically)
        for section in env_sections:
            if section.strip().startswith("<ENVIRONMENT"):
                static_sections.append(section)
                break

        # Context projection and memories (conditional on tool triggers)
        if state and self._tool_trigger_registry:
            messages = state.get("messages", [])
            recent_tools = self._extract_recent_tool_calls(messages)
            triggered = self._tool_trigger_registry.get_triggered_sections(recent_tools)

            projection = state.get("context_projection")
            if projection and projection.entries and "context" in triggered:
                static_sections.append(self._build_context_section(projection))

            memories = state.get("recalled_memories")
            if memories and "memory" in triggered:
                static_sections.append(self._build_memory_section(memories))

        # Agent loop output contract (Layer 2 only)
        if state and state.get("current_decision"):
            contract_section = self._build_agent_loop_output_contract_section(self._config)
            if contract_section:
                static_sections.append(contract_section)

        # Build DYNAMIC sections
        dynamic_section = ""
        if state:
            dynamic_section = self._build_dynamic_sections(state)

        # Assemble: static + dynamic (if any) + date
        static_content = "\n\n".join(static_sections)

        if dynamic_section:
            return static_content + "\n" + dynamic_section + "\n\n" + date_line
        else:
            return static_content + "\n\n" + date_line

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
        lines = [
            f"- [{m.source_thread or 'unknown'}] {preview_first(m.content, 200)}"
            for m in memories[:5]
        ]
        joined = "\n".join(lines)
        return f"<memory>\n{joined}\n</memory>"

    def _build_workspace_section(self, workspace: Any, git_status: dict | None) -> str | None:
        """Build <WORKSPACE> section.

        Args:
            workspace: Workspace path (string or Path).
            git_status: Optional git repository status dict.

        Returns:
            XML section string, or None if workspace is None.
        """
        if not workspace:
            return None

        from pathlib import Path

        workspace_path = Path(str(workspace)) if not isinstance(workspace, Path) else workspace
        is_git = git_status is not None

        content = [
            f"<root>{workspace_path}</root>",
            f'<vcs present="{str(is_git).lower()}">',
        ]

        if git_status:
            branch = git_status.get("branch", "unknown")
            main_branch = git_status.get("main_branch", "main")
            content.append(f"  <branch>{branch}</branch>")
            content.append(f"  <main_branch>{main_branch}</main_branch>")

            status = git_status.get("status", "")
            if status:
                # Truncate to 20 lines
                status_lines = status.split("\n")[:20]
                status_text = "\n    ".join(line for line in status_lines if line)
                content.append(f"  <status>\n    {status_text}\n  </status>")

            commits = git_status.get("recent_commits", "")
            if commits:
                content.append(f"  <recent_commits>{commits}</recent_commits>")

        content.append("</vcs>")

        return "<WORKSPACE>\n" + "\n".join(content) + "\n</WORKSPACE>"

    def _build_thread_section(self, thread_context: dict) -> str | None:
        """Build <THREAD> section.

        Args:
            thread_context: Thread state dict from runner.

        Returns:
            XML section string, or None if thread_context is empty.
        """
        if not thread_context:
            return None

        thread_id = thread_context.get("thread_id", "unknown")
        goals = thread_context.get("active_goals", [])
        turns = thread_context.get("conversation_turns", 0)
        plan = thread_context.get("current_plan")

        content = [f"<thread_id>{thread_id}</thread_id>"]

        if goals:
            import json

            goals_json = json.dumps(goals)
            content.append(f"<active_goals>{goals_json}</active_goals>")

        content.append(f"<conversation_turns>{turns}</conversation_turns>")

        if plan:
            content.append(f"<current_plan>{plan}</current_plan>")

        return "<THREAD>\n" + "\n".join(content) + "\n</THREAD>"

    def _build_protocols_section(self, protocol_summary: dict) -> str | None:
        """Build <PROTOCOLS> section.

        Args:
            protocol_summary: Protocol state dict from runner.

        Returns:
            XML section string, or None if protocol_summary is empty.
        """
        if not protocol_summary:
            return None

        content = []

        for proto_name, proto_info in protocol_summary.items():
            if proto_info:
                proto_type = proto_info.get("type", "unknown")
                stats = proto_info.get("stats", "")
                if stats:
                    content.append(f'<{proto_name} type="{proto_type}" stats="{stats}"/>')
                else:
                    content.append(f'<{proto_name} type="{proto_type}"/>')

        if not content:
            return None

        return "<PROTOCOLS>\n" + "\n".join(content) + "\n</PROTOCOLS>"

    def _build_agent_loop_output_contract_section(
        self, config: SootheConfig | None = None
    ) -> str | None:
        """Build <AGENT_LOOP_OUTPUT_CONTRACT> section for Layer 2 agent loop.

        Args:
            config: Optional SootheConfig to check if contract is enabled.

        Returns:
            XML section string, or None if contract is disabled.
        """
        if config is None or not config.agentic.agent_loop_output_contract_enabled:
            return None

        return (
            "<AGENT_LOOP_OUTPUT_CONTRACT>\n"
            "- After tool or subagent results arrive, add at most two short wrap-up sentences in your own words.\n"
            "- Do NOT paste the full tool/subagent output again unless the user explicitly asked for a "
            "verbatim repeat.\n"
            "- If the tool output already satisfies the user-visible deliverable, stop there.\n"
            "</AGENT_LOOP_OUTPUT_CONTRACT>"
        )

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
                "messages": request.state.get("messages", []),  # For tool call extraction
                "active_goals": request.state.get("active_goals", []),  # For THREAD condition
                "context_projection": request.state.get("context_projection"),
                "recalled_memories": request.state.get("recalled_memories"),
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
