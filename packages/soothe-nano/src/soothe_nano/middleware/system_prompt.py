"""System prompt middleware based on LLM query classification."""

from __future__ import annotations

import logging
from contextvars import Token
from typing import TYPE_CHECKING, Annotated, Any, NotRequired

from langchain.agents.middleware.types import AgentMiddleware, ContextT, ModelRequest, ModelResponse
from langchain_core.messages import AnyMessage, SystemMessage, ToolMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from soothe_nano.utils.text_preview import preview_first

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from soothe_sdk.intention.models import RoutingClassification  # IG-226
    from soothe_sdk.protocols.memory import MemoryItem

    from soothe_nano.config import SootheConfig
    from soothe_nano.middleware._tool_context import ToolContextRegistry, ToolTriggerRegistry

logger = logging.getLogger(__name__)

# Soothe main graph: subagents are invoked only via this tool name.
_TASK_TOOL_NAME = "task"
# Layer 2 executor appends execution hints using this prefix (must stay in sync).
_EXECUTION_HINTS_MARKER = "\n\nExecution hints:"
_VALID_TASK_COMPLEXITY = frozenset({"minimal", "simple", "medium", "complex"})

# `_extract_recent_tool_calls` window/cap.
# Window must absorb a parallel-wave step (1 AIMessage + N ToolMessages) plus
# loop-continuation bootstrap injects without dropping older tool signals.
# Cap >= number of distinct sections in the trigger registry, with headroom.
RECENT_TOOL_MESSAGE_WINDOW = 25
RECENT_TOOL_NAME_CAP = 10


class _SystemPromptState(TypedDict):
    """State schema for SystemPromptMiddleware.

    LangGraph merges all middleware state schemas to build the final graph state.
    Keys that no middleware declares are silently dropped on every state-update
    merge, so consumer-side reads (``modify_request``) see ``None`` even when
    upstream code wrote a value. Declaring keys here is the only way to make
    them survive across nodes.

    Declares:
      - ``routing_classification`` so task complexity reaches the prompt builder.
      - ``workspace`` so the executor's ``_execute_graph_input``
        and ``WorkspaceContextMiddleware.abefore_agent`` writes propagate to
        ``modify_request``. Without this declaration, ``state.get("workspace")``
        returns ``None`` and WORKSPACE_RULES / AGENT_INSTRUCTIONS / the
        <WORKSPACE> block all disappear from the execute-step system prompt.
      - Four MCP keys for cross-call MCP state.
      - ``skill_activation`` so turn-0 prefetch and invoke_skill bodies survive
        LangGraph state merges and reach ``modify_request`` / tool middleware.

    The ``messages`` key MUST use ``Annotated[..., add_messages]`` to preserve
    the reducer from the base ``AgentState``.  A plain ``list`` annotation
    silently downgrades the channel to ``LastValue``, which raises
    ``InvalidUpdateError`` when parallel tool calls return in the same step.
    """

    messages: Annotated[list[AnyMessage], add_messages]
    routing_classification: NotRequired[Any]  # Type: RoutingClassification
    response_language: NotRequired[Any]  # Type: ResponseLanguage
    workspace: NotRequired[str | None]
    _available_tools_block: NotRequired[str]
    _available_skills_block: NotRequired[str]
    _skill_context_blocks: NotRequired[list[str]]
    _available_mcp_tools_block: NotRequired[str]


class SystemPromptMiddleware(AgentMiddleware):
    """Dynamically adjust system prompts based on LLM query classification.

    Uses task_complexity from RoutingClassification (determined by fast LLM)
    to select appropriate prompt verbosity:
    - minimal: Minimal prompt for greetings and quick questions
    - simple: Compact execution prompt for small tasks
    - medium: Standard prompt with guidelines
    - complex: Full prompt with all context

    This middleware expects ``routing_classification`` in agent state before the
    first model call (host inject).

    Args:
        config: Soothe configuration for resolving prompt templates.
    """

    state_schema = _SystemPromptState

    def __init__(
        self,
        config: SootheConfig,
        tool_trigger_registry: ToolTriggerRegistry | None = None,
        tool_context_registry: ToolContextRegistry | None = None,
    ) -> None:
        """Initialize the system prompt middleware.

        Args:
            config: Soothe configuration instance.
            tool_trigger_registry: Optional registry for tool→section triggers.
            tool_context_registry: Optional registry for tool→context fragments.
        """
        self._config = config
        self._tool_trigger_registry = tool_trigger_registry
        self._tool_context_registry = tool_context_registry

    @staticmethod
    def _langfuse_runnable_config() -> dict[str, Any] | None:
        """Best-effort RunnableConfig for Langfuse hint registration (execute-step forks)."""
        try:
            from langgraph.config import get_config

            cfg = get_config()
            return cfg if isinstance(cfg, dict) else None
        except Exception:
            return None

    @staticmethod
    def _langfuse_system_hint_push(request: ModelRequest[ContextT]) -> Token | None:
        """Push effective system prompt for Langfuse generation input (IG-385).

        Returns:
            ContextVar reset token from :func:`publish_langfuse_system_prompt_hint`, or None.
        """
        from soothe_sdk.observability.langfuse.system_hint import (
            publish_langfuse_system_prompt_hint,
        )

        sm = request.system_message
        if sm is None:
            return None
        try:
            text = str(sm.text).strip()
        except Exception:
            text = ""
        if not text and isinstance(sm.content, str):
            text = sm.content.strip()
        if not text:
            return None
        return publish_langfuse_system_prompt_hint(
            text,
            runnable_config=SystemPromptMiddleware._langfuse_runnable_config(),
        )

    def _build_environment_section(self) -> str:
        """Build <ENVIRONMENT> section (static, always present for medium/complex).

        Returns:
            XML section with platform, shell, model, knowledge cutoff.
        """
        from soothe_nano.prompts.context_xml import build_soothe_environment_section

        model = self._config.resolve_model("default")
        return build_soothe_environment_section(model=model)

    def _extract_recent_tool_calls(
        self,
        messages: list[AnyMessage],
        window: int = RECENT_TOOL_MESSAGE_WINDOW,
    ) -> list[str]:
        """Extract unique tool names from recent tool activity.

        Inspects both ``ToolMessage.name`` (the result) AND
        ``AIMessage.tool_calls[*].name`` (the invocation). The invocation side
        matters for loop-continuation bootstrap: the predecessor-branch
        replay preserves Human/AI envelopes but strips ToolMessage rows, so
        the AIMessage's structured ``tool_calls`` is the only surviving
        signal of prior tool use.

        Args:
            messages: Conversation message history.
            window: Number of recent messages to inspect.

        Returns:
            Unique tool names, most recent first, capped at
            ``RECENT_TOOL_NAME_CAP``.
        """
        if not messages:
            return []

        recent_messages = messages[-window:] if len(messages) > window else messages

        def _names_from(msg: AnyMessage) -> list[str]:
            out: list[str] = []
            if isinstance(msg, ToolMessage) and msg.name:
                out.append(msg.name)
            for tc in getattr(msg, "tool_calls", None) or []:
                name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
                if name:
                    out.append(name)
            return out

        ordered_names: list[str] = []
        for msg in reversed(recent_messages):
            ordered_names.extend(_names_from(msg))

        # Dedup preserves most-recent-first insertion order; cap as a final guard.
        return list(dict.fromkeys(ordered_names))[:RECENT_TOOL_NAME_CAP]

    @staticmethod
    def _effective_messages_for_prompt(
        request: ModelRequest[ContextT],
    ) -> list[AnyMessage]:
        """Merge graph state messages with the in-flight ModelRequest message list.

        On the first model hop of an execute step, ``LoopHumanMessage.workspace``
        often appears only on ``request.messages`` before LangGraph merges state.
        """
        state_messages: list[AnyMessage] = []
        if hasattr(request.state, "get"):
            raw = request.state.get("messages")
            if isinstance(raw, list):
                state_messages = raw
        request_messages = list(getattr(request, "messages", None) or [])
        if len(request_messages) > len(state_messages):
            return request_messages
        return state_messages or request_messages

    def _resolve_workspace_for_prompt(self, state: dict[str, Any] | None) -> str | None:
        """Resolve workspace for system-prompt assembly (config, state, messages).

        Execute-step graph input often carries workspace on ``configurable`` or on
        the latest ``LoopHumanMessage`` rather than ``state['workspace']`` after
        LangGraph merges. ``modify_request`` merges ``request.messages`` into the
        resolution state so first-hop execute steps still receive workspace blocks.
        """
        if not state:
            return None
        from soothe_nano.workspace.workspace_api import (
            resolve_workspace_for_tool_execution,
        )

        resolved = resolve_workspace_for_tool_execution(
            state=state,
            use_langgraph_config=True,
        )
        if resolved is None:
            return None
        return str(resolved)

    def _build_workspace_tail_sections(
        self,
        workspace: str,
        *,
        env_section: str,
    ) -> list[str]:
        """Workspace-stable blocks appended at the system-prompt tail (RFC-214).

        Order: ENVIRONMENT → WORKSPACE_RULES → WORKSPACE → AGENT_INSTRUCTIONS.
        """
        from soothe_nano.prompts.project_instructions import load_agent_instructions
        from soothe_nano.prompts.system_templates import (
            EXECUTE_WORKSPACE_RULES_FRAGMENT,
        )

        tail: list[str] = [env_section, EXECUTE_WORKSPACE_RULES_FRAGMENT]

        ws_section = self._build_workspace_section(workspace)
        if ws_section:
            tail.append(ws_section)

        headline_cap = int(self._config.agent.agent_instructions_max_chars)
        agent_instructions = load_agent_instructions(
            workspace,
            headline_max_chars=headline_cap,
        )
        if agent_instructions:
            tail.append(agent_instructions)

        return tail

    def _should_inject_workspace(self, state: dict[str, Any]) -> bool:
        """Determine if WORKSPACE section should be injected.

        Always inject when a workspace is bound to the request. The companion
        WORKSPACE_RULES block is already unconditional on the same predicate;
        gating WORKSPACE on prior tool use produced hallucinated paths when the
        user asked about the workspace before any tool ran (trace fe0d).

        Args:
            state: Request state.

        Returns:
            True when ``state["workspace"]`` is set.
        """
        return bool(self._resolve_workspace_for_prompt(state))

    def _should_inject_thread(self, state: dict[str, Any]) -> bool:
        """Determine if THREAD section should be injected.

        Conditions:
        1. Multi-turn conversation (messages > 1)

        Args:
            state: Request state.

        Returns:
            True if THREAD should be injected.
        """
        messages = state.get("messages", [])
        return len(messages) > 1

    def _get_base_prompt_core(self, complexity: str) -> str:
        """Behavioral system prompt for complexity (no volatile date line; RFC-104 cache order)."""
        from soothe_nano.prompts import (
            _MEDIUM_SYSTEM_PROMPT,
            _SIMPLE_SYSTEM_PROMPT,
        )
        from soothe_nano.prompts.system_templates import (
            format_complex_agent_system_prompt_core,
        )

        # Handle both enum and string values
        complexity_str = str(complexity) if hasattr(complexity, "value") else complexity

        if complexity_str == "minimal":
            return _SIMPLE_SYSTEM_PROMPT.format(assistant_name=self._config.agent.name)
        if complexity_str == "simple":
            return _SIMPLE_SYSTEM_PROMPT.format(assistant_name=self._config.agent.name)
        if complexity_str == "medium":
            return _MEDIUM_SYSTEM_PROMPT.format(assistant_name=self._config.agent.name)
        return format_complex_agent_system_prompt_core(
            self._config.agent.system_prompt,
            self._config.agent.name,
        )

    def _get_prompt_for_complexity(
        self, complexity: str, state: dict[str, Any] | None = None
    ) -> str:
        """Build volatility-tiered system prompt (RFC-214).

        Static Tier (session-stable, maximum cache hits):
        - Base behavioral prompt + tool orchestration guide
        - Execution policies
        - Subagent routing directive (when the host requests a preferred subagent)

        Semi-Static Tier (goal-stable, changes infrequently):
        - Thread context (complex only)
        - Protocol summary (complex only)
        - Scenario guidance

        Workspace tail (execute-step; when workspace resolved):
        - ENVIRONMENT, WORKSPACE_RULES, WORKSPACE metadata, AGENT_INSTRUCTIONS

        NOT in system prompt (moved to user message):
        - Execution hints → EXPECTED OUTPUT / INSTRUCTIONS / EXECUTION METADATA in user envelope
        - Current goal context → ledger / plan turns (not repeated on execute-step message)
        - Per-turn recalled memories → <RETRIEVED_KNOWLEDGE><MEMORY>

        Volatile clock → ``<TIMESTAMP>`` XML footer on the system prompt (not user/ledger).

        Args:
            complexity: One of "minimal", "simple", "medium", "complex". All
                tiers share the same assembly; gated sections (thread,
                protocols, tool-triggered) opt themselves in independently.
            state: Request state with context information.

        Returns:
            Volatility-ordered system prompt string.
        """
        from soothe_nano.prompts.context_xml import (
            build_context_sections_for_complexity,
        )

        base_core = self._get_base_prompt_core(complexity)

        # Build ENVIRONMENT once; placed mid-prelude (after the workspace
        # rules and project instructions, before the WORKSPACE metadata).
        # `build_context_sections_for_complexity` returns an empty list for
        # the minimal tier, so fall back to the direct ENVIRONMENT builder.
        env_sections = build_context_sections_for_complexity(
            config=self._config,
            complexity=complexity,  # type: ignore[arg-type]
            state=state or {},
            include_workspace_extras=False,
        )
        env_section: str | None = None
        for section in env_sections:
            if section.strip().startswith("<ENVIRONMENT"):
                env_section = section
                break
        if env_section is None:
            env_section = self._build_environment_section()

        workspace = self._resolve_workspace_for_prompt(state)

        # ── Static prelude (behavioral core; workspace blocks live at tail) ─
        # Block order:
        #   1. base_core
        #   2. <RESPONSE_LANGUAGE_HINT>    (always)
        #   3. <AVAILABLE_TOOLS>           (when progressive tools enabled)
        # Gated blocks (context/memory/directive/contract) and semi-static
        # sections follow. Workspace tail (when bound):
        #   ENVIRONMENT → WORKSPACE_RULES → WORKSPACE → AGENT_INSTRUCTIONS
        from soothe_nano.prompts.identity import prepend_assistant_identity
        from soothe_nano.prompts.system_templates import build_response_language_hint

        response_language = (state or {}).get("response_language")
        static_sections: list[str] = [
            prepend_assistant_identity(base_core, self._config.agent.name),
            build_response_language_hint(response_language),
        ]

        tools_block = state.get("_available_tools_block") if state else None
        if tools_block:
            static_sections.append(tools_block)

        if complexity != "minimal":
            static_sections.append(self._build_tool_selection_guidance_section())

        # ── Gated static blocks ─────────────────────────────────────────

        # Memory summary — long-term persona/preferences only (RFC-214)
        if state and self._tool_trigger_registry:
            messages = state.get("messages", [])
            recent_tools = self._extract_recent_tool_calls(messages)
            triggered = self._tool_trigger_registry.get_triggered_sections(recent_tools)
            memories = state.get("recalled_memories")
            if memories and "memory" in triggered:
                static_sections.append(self._build_memory_section(memories))

        # Subagent routing directive (explicit /deep_research, /browser_use, etc.)
        subagent_directive = state.get("_subagent_routing_directive") if state else None
        if subagent_directive:
            directive_section = (
                f"<SUBAGENT_ROUTING_DIRECTIVE>\n"
                f"The user explicitly requested the **{subagent_directive}** subagent. You MUST use the "
                f"'{_TASK_TOOL_NAME}' tool with subagent_type='{subagent_directive}' for this request.\n"
                f"\n"
                f"CRITICAL INSTRUCTION:\n"
                f"- The subagent_type argument MUST be exactly '{subagent_directive}' (use this id verbatim)\n"
                f"- Do NOT substitute or override this choice with a different subagent\n"
                f"- The user selected {subagent_directive} for a specific reason and will be confused if you use a different one\n"
                f"\n"
                f"Do not use search_web, filesystem, shell, or other tools at the root agent — delegate "
                f"via '{_TASK_TOOL_NAME}' only. Provide a detailed task description in the tool call.\n"
                f"</SUBAGENT_ROUTING_DIRECTIVE>"
            )
            static_sections.append(directive_section)

        # Agent loop output contract removed from nano (L2-only).

        # ── Semi-Static Tier (goal-stable) ────────────────────────────
        semi_static_sections: list[str] = []

        # Thread context (complex only)
        if complexity == "complex" and state and self._should_inject_thread(state):
            thread_section = self._build_thread_section(state.get("thread_context", {}))
            if thread_section:
                semi_static_sections.append(thread_section)

        # Protocol summary (complex only)
        if complexity == "complex" and state and self._tool_trigger_registry:
            messages = state.get("messages", [])
            recent_tools = self._extract_recent_tool_calls(messages)
            triggered = self._tool_trigger_registry.get_triggered_sections(recent_tools)
            if "PROTOCOLS" in triggered:
                proto_section = self._build_protocols_section(state.get("protocol_summary", {}))
                if proto_section:
                    semi_static_sections.append(proto_section)

        # Scenario guidance removed from nano (L2-only).

        # Tool-specific sections from context registry (semi-static)
        if state and self._tool_context_registry:
            messages = state.get("messages", [])
            recent_tools = self._extract_recent_tool_calls(messages)
            for tool_name in recent_tools:
                tool_section = self._tool_context_registry.get_system_context(tool_name)
                if tool_section:
                    semi_static_sections.append(tool_section.strip())

        # RFC-105: Progressive skill loading blocks
        avail_block = state.get("_available_skills_block") if state else None
        skill_ctx_blocks = (state.get("_skill_context_blocks") or []) if state else []
        if avail_block:
            static_sections.append(avail_block)
        if skill_ctx_blocks:
            from soothe_nano.prompts.system_templates import (
                SKILL_CONTEXT_ACTIVE_GUIDE,
            )

            semi_static_sections.append(SKILL_CONTEXT_ACTIVE_GUIDE)
        semi_static_sections.extend(skill_ctx_blocks)

        # RFC-412: MCP deferred tool listing
        mcp_block = state.get("_available_mcp_tools_block") if state else None
        if mcp_block:
            static_sections.append(mcp_block)

        # ── Assemble: static + semi-static + workspace tail ─────────────
        from soothe_nano.prompts.system_templates import build_timestamp_xml_footer

        parts = ["\n\n".join(static_sections)]
        if semi_static_sections:
            parts.append("\n\n".join(semi_static_sections))

        if workspace:
            workspace_tail = self._build_workspace_tail_sections(
                workspace,
                env_section=env_section,
            )
            parts.append("\n\n".join(workspace_tail))
        else:
            parts.append(env_section)

        parts.append(build_timestamp_xml_footer())

        return "\n\n".join(parts)

    def _get_domain_scoped_prompt(
        self, classification: RoutingClassification, state: dict[str, Any] | None = None
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

    @staticmethod
    def _build_tool_selection_guidance_section() -> str:
        """Build static builtin-tool naming guidance to reduce hallucinated tool names."""
        return (
            "<TOOL_SELECTION>\n"
            "Builtin tool naming (use exact names; aliases do not exist):\n"
            "- Shell commands and pipelines: run_command (not read_command or shell)\n"
            "- Search text inside files: grep\n"
            "- Find files by path pattern: glob (prefer narrow paths; on timeout use grep or ls)\n"
            "- List a directory: ls with path in args (not in the tool name)\n"
            "- Read file contents: read_file with file_path in args\n"
            "</TOOL_SELECTION>"
        )

    def _build_memory_section(self, memories: list[MemoryItem]) -> str:
        """Build <MEMORY_SUMMARY> XML for long-term memories (RFC-214).

        Only long-term persona/preferences go here (semi-static, goal-stable).
        Per-turn situational recall belongs in the user message envelope
        <RETRIEVED_KNOWLEDGE><MEMORY>.

        Args:
            memories: Recalled memory items from MemoryProtocol.

        Returns:
            XML section string with top 5 memories, 200 chars each.
        """
        lines = [
            f"- [{m.source_thread or 'unknown'}] {preview_first(m.content, 200)}"
            for m in memories[:5]
        ]
        joined = "\n".join(lines)
        return f"<MEMORY_SUMMARY>\n{joined}\n</MEMORY_SUMMARY>"

    def _build_workspace_section(self, workspace: Any) -> str | None:
        """Build <WORKSPACE> section via shared context_xml builder."""
        if not workspace:
            return None
        from pathlib import Path

        from soothe_nano.prompts.context_xml import build_soothe_workspace_section

        workspace_path = Path(str(workspace)) if not isinstance(workspace, Path) else workspace
        return build_soothe_workspace_section(workspace_path)

    def _build_thread_section(self, thread_context: dict) -> str | None:
        """Build <THREAD> section via shared context_xml builder."""
        if not thread_context:
            return None
        from soothe_nano.prompts.context_xml import build_soothe_thread_section

        return build_soothe_thread_section(thread_context)

    def _build_protocols_section(self, protocol_summary: dict) -> str | None:
        """Build <PROTOCOLS> section via shared context_xml builder."""
        if not protocol_summary:
            return None
        from soothe_nano.prompts.context_xml import build_soothe_protocols_section

        result = build_soothe_protocols_section(protocol_summary)
        return result or None

    @staticmethod
    def _extract_execution_hints_from_state(state: Any) -> str | None:
        """Extract execution hints text from state for user message envelope (RFC-214).

        The executor builds hints directly into the user message envelope
        (UserMessageBuilder.build_execute_step_message), not via middleware.

        Returns:
            Hints text without the marker prefix, or None if no hints present.
        """
        if not hasattr(state, "get"):
            return None
        raw = state.get("system_prompt")
        if not isinstance(raw, str) or _EXECUTION_HINTS_MARKER not in raw:
            return None
        idx = raw.find(_EXECUTION_HINTS_MARKER)
        # Return just the hints content (after the marker prefix)
        return raw[idx + len(_EXECUTION_HINTS_MARKER) :].strip()

    def modify_request(self, request: ModelRequest[ContextT]) -> ModelRequest[ContextT]:
        """Replace system prompt based on LLM classification (RFC-214 volatility tiers).

        Builds the system prompt using static + semi-static tiers only.
        Execution hints are extracted from state and stored in
        ``request.state["_soothe_execution_hints"]`` for the executor to
        include in the user message envelope.

        Args:
            request: Model request to modify.

        Returns:
            Modified request with optimized system prompt.
        """
        classification: RoutingClassification | dict | None = request.state.get(
            "routing_classification"
        )

        complexity: str
        if classification:
            if isinstance(classification, dict):
                complexity = classification.get("task_complexity") or "medium"
            else:
                complexity = classification.task_complexity
        else:
            complexity = "medium"
            logger.debug(
                "No routing_classification on state; using task_complexity=%s for system prompt",
                complexity,
            )

        if complexity not in _VALID_TASK_COMPLEXITY:
            logger.debug("Normalizing invalid task_complexity %r to medium", complexity)
            complexity = "medium"

        # Extract state for XML section building
        state_dict: dict[str, Any] = {}
        if hasattr(request.state, "get"):
            effective_messages = self._effective_messages_for_prompt(request)
            state_dict = {
                "workspace": request.state.get("workspace"),
                "thread_context": request.state.get("thread_context", {}),
                "protocol_summary": request.state.get("protocol_summary", {}),
                "messages": effective_messages,
                "recalled_memories": request.state.get("recalled_memories"),
                "_subagent_routing_directive": request.state.get("_subagent_routing_directive"),
                "skill_activation": request.state.get("skill_activation"),
                "tool_activation": request.state.get("tool_activation"),
                "mcp_activation": request.state.get("mcp_activation"),
                "response_language": request.state.get("response_language"),
                "_available_tools_block": request.state.get("_available_tools_block"),
                "_available_skills_block": request.state.get("_available_skills_block"),
                "_skill_context_blocks": request.state.get("_skill_context_blocks"),
                "_available_mcp_tools_block": request.state.get("_available_mcp_tools_block"),
            }
            resolved_workspace = self._resolve_workspace_for_prompt(state_dict)
            if resolved_workspace:
                state_dict["workspace"] = resolved_workspace

        optimized_prompt = self._get_prompt_for_complexity(complexity, state_dict)

        # Extract execution hints from state for user message envelope (RFC-214)
        hints_text = self._extract_execution_hints_from_state(request.state)
        if hints_text:
            request.state["_soothe_execution_hints"] = hints_text

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
        from soothe_sdk.observability.langfuse.system_hint import (
            clear_langfuse_system_prompt_hint,
        )

        modified_request = self.modify_request(request)
        tok = self._langfuse_system_hint_push(modified_request)
        runnable_config = self._langfuse_runnable_config()
        try:
            return handler(modified_request)
        finally:
            clear_langfuse_system_prompt_hint(tok, runnable_config=runnable_config)

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
        from soothe_sdk.observability.langfuse.system_hint import (
            clear_langfuse_system_prompt_hint,
        )

        modified_request = self.modify_request(request)
        tok = self._langfuse_system_hint_push(modified_request)
        runnable_config = self._langfuse_runnable_config()
        try:
            return await handler(modified_request)
        finally:
            clear_langfuse_system_prompt_hint(tok, runnable_config=runnable_config)
