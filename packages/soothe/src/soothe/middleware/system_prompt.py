"""System prompt middleware based on LLM query classification."""

from __future__ import annotations

import logging
from contextvars import Token
from typing import TYPE_CHECKING, Annotated, Any, NotRequired

from langchain.agents.middleware.types import AgentMiddleware, ContextT, ModelRequest, ModelResponse
from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from soothe.skills.registry import merge_skill_activation
from soothe.toolkits.progressive.registry import merge_tool_activation
from soothe.utils.text_preview import preview_first

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from soothe.config import SootheConfig
    from soothe.foundation.sloop.intention import RoutingClassification  # IG-226
    from soothe.middleware._tool_context import ToolContextRegistry, ToolTriggerRegistry
    from soothe.protocols.memory import MemoryItem

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


def _configurable_goal_synthesis() -> bool:
    """Return True when CoreAgent is running goal-completion synthesis (read-only).

    ``SynthesisGenerator`` sets ``soothe_goal_synthesis`` in ``config.configurable``.
    """
    try:
        from langgraph.config import get_config

        lg_cfg = get_config()
    except Exception:
        return False
    if not isinstance(lg_cfg, dict):
        return False
    conf = lg_cfg.get("configurable")
    if not isinstance(conf, dict):
        return False
    return bool(conf.get("soothe_goal_synthesis"))


def _configurable_step_subagent() -> str | None:
    """Return StrangeLoop per-step subagent hint from LangGraph RunnableConfig when set.

    Executor passes ``soothe_step_subagent`` in ``config.configurable`` (from wire
    ``preferred_subagent`` when ``routing_hint=subagent``). This must drive the same task-only enforcement as
    wire ``routing_hint=subagent`` (IG-386).

    Returns:
        Stripped subagent name, or None if unset/blank or config unavailable.
    """
    try:
        from langgraph.config import get_config

        lg_cfg = get_config()
    except Exception:
        return None
    if not isinstance(lg_cfg, dict):
        return None
    conf = lg_cfg.get("configurable")
    if not isinstance(conf, dict):
        return None
    raw = conf.get("soothe_step_subagent")
    if not isinstance(raw, str):
        return None
    stripped = raw.strip()
    return stripped or None


def _last_message_is_human(messages: list[AnyMessage] | None) -> bool:
    """True when the model is about to produce the first reply to the latest user turn."""
    if not messages:
        return False
    return isinstance(messages[-1], HumanMessage)


def _filter_tools_to_task_only(
    tools: list[Any],
) -> list[Any]:
    """Keep only the ``task`` tool so the model cannot substitute ``search_web`` etc."""
    kept: list[Any] = []
    for tool in tools:
        name: str | None
        if isinstance(tool, dict):
            name = tool.get("name")
        else:
            name = getattr(tool, "name", None)
        if name == _TASK_TOOL_NAME:
            kept.append(tool)
    return kept


class _SystemPromptState(TypedDict):
    """State schema for SystemPromptMiddleware.

    LangGraph merges all middleware state schemas to build the final graph state.
    Keys that no middleware declares are silently dropped on every state-update
    merge, so consumer-side reads (``modify_request``) see ``None`` even when
    upstream code wrote a value. Declaring keys here is the only way to make
    them survive across nodes.

    Declares:
      - ``routing_classification`` so StrangeLoop's complexity hint reaches the
        prompt builder (IG-383).
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
    sent_mcp_tool_names: NotRequired[set[str]]
    invoked_mcp_tools: NotRequired[dict[str, dict]]
    disabled_mcp_servers: NotRequired[set[str]]
    cached_mcp_resources: NotRequired[dict[str, str]]
    tool_activation: NotRequired[Annotated[dict[str, Any], merge_tool_activation]]
    skill_activation: NotRequired[Annotated[dict[str, Any], merge_skill_activation]]


class SystemPromptMiddleware(AgentMiddleware):
    """Dynamically adjust system prompts based on LLM query classification.

    Uses task_complexity from RoutingClassification (determined by fast LLM)
    to select appropriate prompt verbosity:
    - minimal: Minimal prompt for greetings and quick questions (chitchat intake)
    - simple: Compact execution prompt for small tasks
    - medium: Standard prompt with guidelines
    - complex: Full prompt with all context

    This middleware expects ``routing_classification`` in agent state before the
    first model call (runner / StrangeLoop inject).

    Args:
        config: Soothe configuration for resolving prompt templates.
    """

    state_schema = _SystemPromptState

    def __init__(
        self,
        config: SootheConfig,
        tool_trigger_registry: ToolTriggerRegistry | None = None,
        tool_context_registry: ToolContextRegistry | None = None,
        mcp_registry: Any | None = None,
        progressive_tool_middleware: Any | None = None,
    ) -> None:
        """Initialize the system prompt middleware.

        Args:
            config: Soothe configuration instance.
            tool_trigger_registry: Optional registry for tool→section triggers.
            tool_context_registry: Optional registry for tool→context fragments.
            mcp_registry: Optional MCPRegistry for MCP tool listing (RFC-412).
            progressive_tool_middleware: Optional ``ProgressiveToolMiddleware`` for
                deferred-tool listing from the full catalog (unfiltered).
        """
        self._config = config
        self._tool_trigger_registry = tool_trigger_registry
        self._tool_context_registry = tool_context_registry
        self._mcp_registry = mcp_registry
        self._progressive_tool_middleware = progressive_tool_middleware
        # IG-519: Instance-level caching for SkillIndex/ProgressiveSkillRegistry
        # Preserves cache across hops, avoiding re-instantiation overhead (~2.5ms/hop)
        self._skill_index: Any = None  # Type: SkillIndex (lazy import)
        self._skill_registry: Any = None  # Type: ProgressiveSkillRegistry (lazy import)

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
        from soothe.utils.observability.langfuse_system_hint import (
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
        from soothe.foundation.sloop.prompts.context_xml import build_soothe_environment_section

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
        from soothe.foundation.workspace.runtime_resolution import (
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
        from soothe.foundation.sloop.prompts.project_instructions import load_agent_instructions
        from soothe.foundation.sloop.prompts.system_templates import (
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

    def _get_base_prompt_core(self, complexity: str) -> str:
        """Behavioral system prompt for complexity (no volatile date line; RFC-104 cache order)."""
        from soothe.foundation.sloop.prompts import (
            _MEDIUM_SYSTEM_PROMPT,
            _SIMPLE_SYSTEM_PROMPT,
        )
        from soothe.foundation.sloop.prompts.system_templates import (
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
        - Subagent routing directive (when the user explicitly requests a routed subagent via slash command)
        - Agent loop output contract (execute-step only)

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
        from soothe.foundation.sloop.prompts.context_xml import (
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
        from soothe.foundation.sloop.prompts.identity import prepend_assistant_identity
        from soothe.foundation.sloop.prompts.system_templates import build_response_language_hint

        response_language = (state or {}).get("response_language")
        static_sections: list[str] = [
            prepend_assistant_identity(base_core, self._config.agent.name),
            build_response_language_hint(response_language),
        ]

        deferred_tools = state.get("_deferred_tools_for_listing") if state else None
        tools_block = self._compose_available_tools_block(state, deferred_tools=deferred_tools)
        if tools_block:
            static_sections.append(tools_block)

        if complexity != "minimal":
            static_sections.append(self._build_tool_selection_guidance_section())

        # ── Gated static blocks ─────────────────────────────────────────

        # Context projection (static — changes infrequently)
        if state and self._tool_trigger_registry:
            messages = state.get("messages", [])
            recent_tools = self._extract_recent_tool_calls(messages)
            triggered = self._tool_trigger_registry.get_triggered_sections(recent_tools)

            projection = state.get("context_projection")
            if projection and projection.entries and "context" in triggered:
                static_sections.append(self._build_context_section(projection))

        # Memory summary — long-term persona/preferences only (RFC-214)
        # Per-turn memories go in the user message envelope <RETRIEVED_KNOWLEDGE>
        if state and self._tool_trigger_registry:
            if not messages:
                messages = state.get("messages", [])
            recent_tools = self._extract_recent_tool_calls(messages)
            triggered = self._tool_trigger_registry.get_triggered_sections(recent_tools)
            memories = state.get("recalled_memories")
            if memories and "memory" in triggered:
                static_sections.append(self._build_memory_section(memories))

        # Subagent routing directive (explicit /research, /plan, or other routed subagent id)
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

        # Agent loop output contract (execute-step only)
        if state and state.get("current_decision"):
            contract_section = self._build_strange_loop_output_contract_section(self._config)
            if contract_section:
                static_sections.append(contract_section)

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

        # Scenario guidance (RFC-225: continue_loop_mode replaces intent_type plumbing)
        if state:
            continue_loop_mode = bool(state.get("continue_loop_mode"))
            goal_type = ""
            scen = (state.get("synthesis_scenario") or "").strip()
            if scen == "code_architecture_design":
                goal_type = "architecture_analysis"
            elif scen == "research_synthesis":
                goal_type = "research_synthesis"

            if continue_loop_mode or goal_type:
                scenario_section = self._build_scenario_section(continue_loop_mode, goal_type)
                if scenario_section:
                    semi_static_sections.append(scenario_section.strip())

        # Tool-specific sections from context registry (semi-static)
        if state and self._tool_context_registry:
            messages = state.get("messages", [])
            recent_tools = self._extract_recent_tool_calls(messages)
            for tool_name in recent_tools:
                tool_section = self._tool_context_registry.get_system_context(tool_name)
                if tool_section:
                    semi_static_sections.append(tool_section.strip())

        # RFC-105: Progressive skill loading blocks
        avail_block, skill_ctx_blocks = self._compose_skills_block(state)
        if avail_block:
            static_sections.append(avail_block)
        if skill_ctx_blocks:
            from soothe.foundation.sloop.prompts.system_templates import (
                SKILL_CONTEXT_ACTIVE_GUIDE,
            )

            semi_static_sections.append(SKILL_CONTEXT_ACTIVE_GUIDE)
        semi_static_sections.extend(skill_ctx_blocks)

        # RFC-412: MCP deferred tool listing
        mcp_block = self._compose_mcp_tools_block(state)
        if mcp_block:
            static_sections.append(mcp_block)

        # ── Assemble: static + semi-static + workspace tail ─────────────
        from soothe.foundation.sloop.prompts.system_templates import build_timestamp_xml_footer

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

        from soothe.foundation.sloop.prompts.context_xml import build_soothe_workspace_section

        workspace_path = Path(str(workspace)) if not isinstance(workspace, Path) else workspace
        return build_soothe_workspace_section(workspace_path)

    def _build_thread_section(self, thread_context: dict) -> str | None:
        """Build <THREAD> section via shared context_xml builder."""
        if not thread_context:
            return None
        from soothe.foundation.sloop.prompts.context_xml import build_soothe_thread_section

        return build_soothe_thread_section(thread_context)

    def _build_protocols_section(self, protocol_summary: dict) -> str | None:
        """Build <PROTOCOLS> section via shared context_xml builder."""
        if not protocol_summary:
            return None
        from soothe.foundation.sloop.prompts.context_xml import build_soothe_protocols_section

        result = build_soothe_protocols_section(protocol_summary)
        return result or None

    def _build_scenario_section(self, continue_loop_mode: bool, goal_type: str) -> str | None:
        """Build scenario-specific guidance section (RFC-225).

        Args:
            continue_loop_mode: True when the loop has prior goals.
            goal_type: Goal type classification (architecture_analysis/research_synthesis/etc).

        Returns:
            Scenario guidance text, or None if no matching scenario.
        """
        from soothe.foundation.sloop.prompts.system_templates import (
            _ARCHITECTURE_ANALYSIS_GUIDE,
            _LOOP_CONTINUATION_GUIDE,
            _RESEARCH_SYNTHESIS_GUIDE,
        )

        # Loop continuation: build on prior goal context within this loop
        if continue_loop_mode:
            return _LOOP_CONTINUATION_GUIDE

        # Architecture analysis: structured layers + components
        if goal_type == "architecture_analysis":
            return _ARCHITECTURE_ANALYSIS_GUIDE

        # Research synthesis: methodology + findings
        if goal_type == "research_synthesis":
            return _RESEARCH_SYNTHESIS_GUIDE

        # No specific scenario guidance
        return None

    def _compose_skills_block(self, state: dict[str, Any] | None) -> tuple[str | None, list[str]]:
        """RFC-105: Compose <AVAILABLE_SKILLS> static block + <SKILL_CONTEXT> semi-static blocks.

        Args:
            state: Request state dict (may contain ``skill_activation``).

        Returns:
            Tuple of (available_skills_block_or_None, list_of_skill_context_blocks).
        """
        if not state:
            return None, []
        activation = state.get("skill_activation")
        if not isinstance(activation, dict):
            return None, []

        activation.setdefault("sent", set())
        activated = activation.get("activated", set())
        invoked = activation.get("invoked", set())
        just_invoked = activation.get("just_invoked", set())
        bodies = activation.get("invoked_bodies", {})

        # IG-519: Use cached SkillIndex/ProgressiveSkillRegistry instances
        # rebuild_if_stale() checks mtime on every call, so stale files are re-parsed
        if self._skill_index is None:
            from soothe.skills.index import SkillIndex

            self._skill_index = SkillIndex()
        if self._skill_registry is None:
            from soothe.skills.registry import ProgressiveSkillRegistry, resolve_core_skill_names

            self._skill_registry = ProgressiveSkillRegistry()
        else:
            from soothe.skills.registry import resolve_core_skill_names

        entries = self._skill_index.rebuild_if_stale()
        core_names = resolve_core_skill_names(self._config.progressive_skills.core_skills)
        core_entries, _deferred = self._skill_registry.partition_core_deferred(entries, core_names)
        activated_entries = [entry for entry in entries if entry.name in activated]
        by_name = {entry.name: entry for entry in core_entries}
        by_name.update({entry.name: entry for entry in activated_entries})
        candidates = sorted(by_name.values(), key=lambda entry: entry.name.lower())

        new_entries = self._skill_registry.new_for_thread(activation, candidates)

        available_block: str | None = None
        if new_entries:
            # Exclude just-invoked skills from listing — their body is in the
            # user message this turn (via <SKILL_REFERENCE> or <SKILL_CONTEXT>).
            listing_entries = [e for e in new_entries if e.name not in just_invoked]

            ctx_limit = int(self._config.agent.loop.context_window_limit)
            budget_pct = float(self._config.progressive_skills.budget_pct)
            budget_chars = max(0, int(ctx_limit * budget_pct))
            per_entry_cap = int(self._config.progressive_skills.max_listing_chars_per_entry)
            min_per_entry = int(self._config.progressive_skills.min_listing_chars_per_entry)

            if listing_entries:
                from soothe.skills.budget import format_skills_within_budget

                text, _telemetry = format_skills_within_budget(
                    listing_entries,
                    budget_chars=budget_chars,
                    per_entry_cap_chars=per_entry_cap,
                    min_per_entry_chars=min_per_entry,
                )
                if text:
                    available_block = f"<AVAILABLE_SKILLS>\n{text}\n</AVAILABLE_SKILLS>"

            # Mark ALL new entries as sent (including just-invoked ones excluded from listing)
            self._skill_registry.mark_sent(activation, [e.name for e in new_entries])

        skill_context_blocks: list[str] = []
        for name in sorted(invoked - just_invoked):
            body = bodies.get(name)
            if not body:
                continue
            skill_context_blocks.append(f'<SKILL_CONTEXT name="{name}">\n{body}\n</SKILL_CONTEXT>')

        # Clear transient just_invoked at end of compose
        activation["just_invoked"] = set()
        state["skill_activation"] = activation

        return available_block, skill_context_blocks

    def _compose_mcp_tools_block(self, state: dict[str, Any] | None) -> str | None:
        """RFC-412: Compose <AVAILABLE_MCP_TOOLS> block for deferred MCP tools.

        Only deferred tools (defer=True) need listing — always-loaded tools
        are already in the tool array.

        Args:
            state: Request state dict (may contain ``sent_mcp_tool_names``).

        Returns:
            XML block string, or None if no MCP tools or registry.
        """
        if not self._mcp_registry or not state:
            return None

        sent = state.get("sent_mcp_tool_names", set())
        if not isinstance(sent, set):
            sent = set()

        descriptors = self._mcp_registry.deferred_tools()
        if not descriptors:
            return None

        # Filter out already-sent tools
        new_descriptors = [d for d in descriptors if d.name not in sent]
        if not new_descriptors:
            return None

        ctx_limit = int(self._config.agent.loop.context_window_limit)
        budget_pct = (
            float(self._config.progressive_mcp.budget_pct) if self._config.progressive_mcp else 0.02
        )
        budget_chars = max(0, int(ctx_limit * budget_pct))
        per_entry_cap = (
            int(self._config.progressive_mcp.max_listing_chars_per_entry)
            if self._config.progressive_mcp
            else 250
        )
        min_per_entry = (
            int(self._config.progressive_mcp.min_listing_chars_per_entry)
            if self._config.progressive_mcp
            else 20
        )

        from soothe.mcp.budget import format_mcp_tools_within_budget

        text, _telemetry = format_mcp_tools_within_budget(
            new_descriptors,
            budget_chars=budget_chars,
            per_entry_cap_chars=per_entry_cap,
            min_per_entry_chars=min_per_entry,
        )
        if not text:
            return None

        # Mark as sent
        for d in new_descriptors:
            sent.add(d.name)
        state["sent_mcp_tool_names"] = sent

        return f"<AVAILABLE_MCP_TOOLS>\n{text}\n</AVAILABLE_MCP_TOOLS>"

    def _compose_available_tools_block(
        self,
        state: dict[str, Any] | None,
        deferred_tools: list[Any] | None,
    ) -> str | None:
        """Compose ``<AVAILABLE_TOOLS>`` for deferred builtin tools."""
        if not self._config.progressive_tools.enabled or not state:
            return None

        from soothe.toolkits.progressive.budget import format_tools_within_budget
        from soothe.toolkits.progressive.registry import ProgressiveToolRegistry

        pt = self._config.progressive_tools
        core = list(pt.core_tools) if pt.core_tools else None
        if pt.search_tools_enabled:
            if core is None:
                from soothe.toolkits.progressive.registry import DEFAULT_CORE_TOOL_NAMES

                core = list(DEFAULT_CORE_TOOL_NAMES)
            elif "search_tools" not in core:
                core.append("search_tools")
        registry = ProgressiveToolRegistry(core_tools=core)

        if deferred_tools is None:
            return None

        descriptors = registry.descriptors_from_tools(deferred_tools)
        _, deferred = registry.partition(descriptors)
        if not deferred:
            return None

        activation = state.get("tool_activation")
        if not isinstance(activation, dict):
            activation = ProgressiveToolRegistry.init_activation_state()
            state["tool_activation"] = activation

        new_entries = registry.new_for_thread(activation, deferred)
        if not new_entries:
            return None

        ctx_limit = int(self._config.agent.loop.context_window_limit)
        budget_chars = max(0, int(ctx_limit * float(pt.budget_pct)))
        text, _telemetry = format_tools_within_budget(
            new_entries,
            budget_chars=budget_chars,
            per_entry_cap_chars=int(pt.max_listing_chars_per_entry),
            min_per_entry_chars=int(pt.min_listing_chars_per_entry),
            include_preamble=True,
        )
        if not text:
            return None

        registry.mark_sent(activation, [e.name for e in new_entries])
        state["tool_activation"] = activation
        from soothe.middleware.progressive_tools import stash_tool_activation_update

        stash_tool_activation_update(activation)
        return f"<AVAILABLE_TOOLS>\n{text}\n</AVAILABLE_TOOLS>"

    def _build_strange_loop_output_contract_section(
        self, config: SootheConfig | None = None
    ) -> str | None:
        """Build <STRANGE_LOOP_OUTPUT_CONTRACT> section for Layer 2 agent loop.

        Args:
            config: Optional SootheConfig to check if contract is enabled.

        Returns:
            XML section string, or None if contract is disabled.
        """
        if config is None or not config.agent.loop.strange_loop_output_contract_enabled:
            return None

        return (
            "<STRANGE_LOOP_OUTPUT_CONTRACT>\n"
            "- After tool or subagent results arrive, add at most two short wrap-up sentences in your own words.\n"
            "- Do NOT paste the full tool/subagent output again unless the user explicitly asked for a "
            "verbatim repeat.\n"
            "- If the tool output already satisfies the user-visible deliverable, stop there.\n"
            "</STRANGE_LOOP_OUTPUT_CONTRACT>"
        )

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
        routing_hint: str | None
        preferred_subagent: str | None

        if classification:
            if isinstance(classification, dict):
                complexity = classification.get("task_complexity") or "medium"
                routing_hint = classification.get("routing_hint")
                preferred_subagent = classification.get("preferred_subagent")
            else:
                complexity = classification.task_complexity
                routing_hint = getattr(classification, "routing_hint", None)
                preferred_subagent = getattr(classification, "preferred_subagent", None)
        else:
            complexity = "medium"
            routing_hint = None
            preferred_subagent = None
            logger.debug(
                "No routing_classification on state; using task_complexity=%s for system prompt",
                complexity,
            )

        if complexity not in _VALID_TASK_COMPLEXITY:
            logger.debug("Normalizing invalid task_complexity %r to medium", complexity)
            complexity = "medium"

        # Check for direct subagent routing hint (preferred_subagent + routing_hint='subagent')
        msgs_for_hop = getattr(request, "messages", None) or []
        first_after_user = _last_message_is_human(msgs_for_hop)
        explicit_subagent = routing_hint == "subagent" and bool(preferred_subagent)
        step_subagent = _configurable_step_subagent()
        # Wired step subagents stay task-only for the whole execute step so the
        # model cannot silently fall back to shell tools after an empty subagent run.
        step_enforce = step_subagent is not None
        wire_enforce = explicit_subagent and first_after_user

        goal_synthesis = _configurable_goal_synthesis()

        # Per-step hint wins over wire routing when both apply (IG-386).
        if goal_synthesis:
            logger.info("Goal synthesis read-only: disabling model tools")
        elif step_enforce:
            directive = step_subagent
            logger.info(
                "StrangeLoop step subagent hint (enforce): soothe_step_subagent=%s",
                step_subagent,
            )
            request.state["_subagent_routing_directive"] = directive
        elif wire_enforce:
            directive = (
                preferred_subagent.strip()
                if isinstance(preferred_subagent, str)
                else preferred_subagent
            )
            logger.info(
                "Explicit subagent routing (enforce): preferred_subagent=%s",
                directive,
            )
            request.state["_subagent_routing_directive"] = directive
        else:
            try:
                request.state.pop("_subagent_routing_directive", None)
            except (AttributeError, TypeError):
                pass

        # Extract state for XML section building
        state_dict: dict[str, Any] = {}
        if hasattr(request.state, "get"):
            effective_messages = self._effective_messages_for_prompt(request)
            state_dict = {
                "workspace": request.state.get("workspace"),
                "thread_context": request.state.get("thread_context", {}),
                "protocol_summary": request.state.get("protocol_summary", {}),
                "messages": effective_messages,
                "active_goals": request.state.get("active_goals", []),
                "context_projection": request.state.get("context_projection"),
                "recalled_memories": request.state.get("recalled_memories"),
                "_subagent_routing_directive": request.state.get("_subagent_routing_directive"),
                "continue_loop_mode": request.state.get("continue_loop_mode"),
                "synthesis_scenario": request.state.get("synthesis_scenario"),
                "skill_activation": request.state.get("skill_activation"),
                "tool_activation": request.state.get("tool_activation"),
                "response_language": request.state.get("response_language"),
            }
            resolved_workspace = self._resolve_workspace_for_prompt(state_dict)
            if resolved_workspace:
                state_dict["workspace"] = resolved_workspace

        # Pass deferred tools through state so AVAILABLE_TOOLS can be inserted
        # in the correct position (between RESPONSE_LANGUAGE_HINT and WORKSPACE_RULES)
        if self._config.progressive_tools.enabled:
            listing_tools: list[Any] = getattr(request, "tools", None) or []
            if self._progressive_tool_middleware is not None:
                full_catalog = self._progressive_tool_middleware.full_tools_for_listing()
                if full_catalog:
                    listing_tools = full_catalog
            state_dict["_deferred_tools_for_listing"] = listing_tools

        optimized_prompt = self._get_prompt_for_complexity(complexity, state_dict)

        # Extract execution hints from state for user message envelope (RFC-214)
        hints_text = self._extract_execution_hints_from_state(request.state)
        if hints_text:
            request.state["_soothe_execution_hints"] = hints_text

        new_system_message = SystemMessage(content=optimized_prompt)
        overrides: dict[str, Any] = {"system_message": new_system_message}

        if goal_synthesis:
            overrides["tools"] = []
        elif step_enforce or wire_enforce:
            tool_list = getattr(request, "tools", None) or []
            task_only = _filter_tools_to_task_only(tool_list)
            if task_only:
                overrides["tools"] = task_only
                logger.info(
                    "Subagent delegation enforcement: model tools narrowed to '%s' only",
                    _TASK_TOOL_NAME,
                )
            else:
                logger.warning(
                    "Subagent delegation enforcement but '%s' tool not in request; leaving full tool set",
                    _TASK_TOOL_NAME,
                )

        return request.override(**overrides)

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
        from soothe.utils.observability.langfuse_system_hint import (
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
        from soothe.utils.observability.langfuse_system_hint import (
            clear_langfuse_system_prompt_hint,
        )

        modified_request = self.modify_request(request)
        tok = self._langfuse_system_hint_push(modified_request)
        runnable_config = self._langfuse_runnable_config()
        try:
            return await handler(modified_request)
        finally:
            clear_langfuse_system_prompt_hint(tok, runnable_config=runnable_config)
