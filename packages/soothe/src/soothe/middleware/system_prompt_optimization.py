"""System prompt optimization middleware based on LLM query classification."""

from __future__ import annotations

import logging
from contextvars import Token
from typing import TYPE_CHECKING, Annotated, Any, NotRequired

from langchain.agents.middleware.types import AgentMiddleware, ContextT, ModelRequest, ModelResponse
from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from soothe.utils.text_preview import preview_first

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from soothe.config import SootheConfig
    from soothe.core.context.tool_registry import ToolContextRegistry
    from soothe.core.context.trigger_registry import ToolTriggerRegistry
    from soothe.core.intention import RoutingClassification  # IG-226
    from soothe.protocols.memory import MemoryItem

logger = logging.getLogger(__name__)

# deepagents / Soothe main graph: subagents are invoked only via this tool name.
_TASK_TOOL_NAME = "task"
# Layer 2 ``ExecutionHintsMiddleware`` appends using this prefix (must stay in sync).
_EXECUTION_HINTS_MARKER = "\n\nExecution hints:"
_VALID_TASK_COMPLEXITY = frozenset({"chitchat", "simple", "medium", "complex"})


def _configurable_step_subagent() -> str | None:
    """Return AgentLoop per-step subagent hint from LangGraph RunnableConfig when set.

    Executor passes ``soothe_step_subagent`` in ``config.configurable`` (from
    ``StepAction.subagent``). This must drive the same task-only enforcement as
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


class _OptimizationState(TypedDict):
    """State schema for SystemPromptOptimizationMiddleware.

    LangGraph merges all middleware state schemas to build the final graph state.
    This schema declares ``routing_classification`` so it propagates correctly (IG-383).

    The ``messages`` key MUST use ``Annotated[..., add_messages]`` to preserve
    the reducer from the base ``AgentState``.  A plain ``list`` annotation
    silently downgrades the channel to ``LastValue``, which raises
    ``InvalidUpdateError`` when parallel tool calls return in the same step.
    """

    messages: Annotated[list[AnyMessage], add_messages]
    routing_classification: NotRequired[Any]  # Type: RoutingClassification


class SystemPromptOptimizationMiddleware(AgentMiddleware):
    """Dynamically adjust system prompts based on LLM query classification.

    Uses task_complexity from RoutingClassification (determined by fast LLM)
    to select appropriate prompt verbosity:
    - chitchat: Minimal prompt for greetings and quick questions
    - simple: Compact execution prompt for small tasks
    - medium: Standard prompt with guidelines
    - complex: Full prompt with all context

    This middleware expects ``routing_classification`` in agent state before the
    first model call (runner / AgentLoop inject). Legacy key ``unified_classification``
    is still read as a fallback.

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

    @staticmethod
    def _langfuse_system_hint_push(request: ModelRequest[ContextT]) -> Token | None:
        """Push effective system prompt for Langfuse generation input (IG-385).

        Returns:
            ContextVar reset token from :func:`push_langfuse_system_prompt_hint`, or None.
        """
        from soothe.utils.observability.langfuse_system_hint import push_langfuse_system_prompt_hint

        sm = request.system_message
        if sm is None:
            return None
        try:
            text = str(sm.text).strip()
        except Exception:
            text = ""
        if not text and isinstance(sm.content, str):
            text = sm.content.strip()
        return push_langfuse_system_prompt_hint(text) if text else None

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

    def _get_base_prompt_core(self, complexity: str) -> str:
        """Behavioral system prompt for complexity (no volatile date line; RFC-104 cache order)."""
        from soothe.core.prompts import (
            _DEFAULT_SYSTEM_PROMPT,
            _MEDIUM_SYSTEM_PROMPT,
            _SIMPLE_SYSTEM_PROMPT,
        )

        if complexity == "chitchat":
            return _SIMPLE_SYSTEM_PROMPT.format(assistant_name=self._config.assistant_name)
        if complexity == "simple":
            return _SIMPLE_SYSTEM_PROMPT.format(assistant_name=self._config.assistant_name)
        if complexity == "medium":
            return _MEDIUM_SYSTEM_PROMPT.format(assistant_name=self._config.assistant_name)
        if self._config.system_prompt:
            return self._config.system_prompt.format(assistant_name=self._config.assistant_name)
        return _DEFAULT_SYSTEM_PROMPT.format(assistant_name=self._config.assistant_name)

    def _get_prompt_for_complexity(
        self, complexity: str, state: dict[str, Any] | None = None
    ) -> str:
        """Build volatility-tiered system prompt (RFC-214).

        Static Tier (session-stable, maximum cache hits):
        - Base behavioral prompt + tool orchestration guide
        - Execution policies
        - Subagent routing directive (when user explicitly requests /browser, /claude, etc.)
        - Agent loop output contract (execute-step only)

        Semi-Static Tier (goal-stable, changes infrequently):
        - Workspace rules
        - Workspace metadata
        - Environment
        - Memory summary (long-term persona/preferences)
        - Context projection
        - Thread context (complex only)
        - Protocol summary (complex only)
        - Scenario guidance

        NOT in system prompt (moved to user message envelope):
        - Date/time → <CONTEXT_INFO>
        - Execution hints → <EXECUTION_HINTS>
        - Current goal context → <CURRENT_GOAL>
        - Per-turn recalled memories → <RETRIEVED_KNOWLEDGE><MEMORY>

        Args:
            complexity: One of "chitchat", "simple", "medium", "complex".
            state: Request state with context information.

        Returns:
            Volatility-ordered system prompt string.
        """
        from soothe.core.prompts.context_xml import build_context_sections_for_complexity

        base_core = self._get_base_prompt_core(complexity)

        # Chitchat: only base + ENVIRONMENT (no date line — date is in user envelope)
        if complexity == "chitchat":
            env_section = self._build_environment_section()
            return f"{base_core}\n\n{env_section}"

        # ── Static Tier (session-stable) ──────────────────────────────
        static_sections: list[str] = [base_core]

        # ENVIRONMENT in static tier for non-chitchat
        env_sections = build_context_sections_for_complexity(
            config=self._config,
            complexity=complexity,  # type: ignore[arg-type]
            state=state or {},
            include_workspace_extras=False,
        )
        for section in env_sections:
            if section.strip().startswith("<ENVIRONMENT"):
                static_sections.append(section)
                break

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

        # Subagent routing directive (explicit /browser, /claude, /research, /explore)
        subagent_directive = state.get("_subagent_routing_directive") if state else None
        if subagent_directive:
            directive_section = (
                f"<SUBAGENT_ROUTING_DIRECTIVE>\n"
                f"The user explicitly requested the **{subagent_directive}** subagent. You MUST use the "
                f"'{_TASK_TOOL_NAME}' tool with subagent_type='{subagent_directive}' for this request.\n"
                f"\n"
                f"CRITICAL INSTRUCTION:\n"
                f"- The subagent_type argument MUST be exactly '{subagent_directive}' (not 'claude', 'browser', etc.)\n"
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
            contract_section = self._build_agent_loop_output_contract_section(self._config)
            if contract_section:
                static_sections.append(contract_section)

        # ── Semi-Static Tier (goal-stable) ────────────────────────────
        semi_static_sections: list[str] = []

        # Workspace rules
        workspace = state.get("workspace") if state else None
        if workspace:
            semi_static_sections.append(
                "<WORKSPACE_RULES>\n"
                "The open project root (absolute path) is under <WORKSPACE><root> above.\n\n"
                "Rules:\n"
                "- Use file tools (list_files, read_file, grep, glob, run_command) against this directory.\n"
                "- For goals about architecture, structure, or the codebase: inspect this directory immediately.\n"
                "- Do NOT ask the user for a local path, GitHub URL, or file upload unless the goal explicitly names "
                "a different project outside this directory.\n"
                "- Do NOT tell the user you need them to share the project first — it is already available here.\n"
                "</WORKSPACE_RULES>"
            )

        # Workspace metadata
        if state and self._should_inject_workspace(state):
            ws_section = self._build_workspace_section(
                state.get("workspace"), state.get("git_status")
            )
            if ws_section:
                semi_static_sections.append(ws_section)

        # Environment section (already added to static above for non-chitchat;
        # for semi-static tier we include workspace-related context)

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

        # Scenario guidance
        if state:
            intent_type = (state.get("intent_type") or "").strip()
            goal_type = ""
            scen = (state.get("synthesis_scenario") or "").strip()
            if scen == "code_architecture_design":
                goal_type = "architecture_analysis"
            elif scen == "research_synthesis":
                goal_type = "research_synthesis"

            classification = state.get("routing_classification") or state.get(
                "unified_classification"
            )
            if not intent_type and classification:
                if isinstance(classification, dict):
                    intent_type = (classification.get("intent_type") or "").strip()
                else:
                    intent_type = (getattr(classification, "intent_type", "") or "").strip()

            if intent_type or goal_type:
                scenario_section = self._build_scenario_section(intent_type, goal_type)
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

        # ── Assemble: static + semi-static (no date line, no execution hints) ──
        parts = ["\n\n".join(static_sections)]
        if semi_static_sections:
            parts.append("\n\n".join(semi_static_sections))

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

    def _build_workspace_section(self, workspace: Any, git_status: dict | None) -> str | None:
        """Build <WORKSPACE> section via shared context_xml builder."""
        if not workspace:
            return None
        from pathlib import Path

        from soothe.core.prompts.context_xml import build_soothe_workspace_section

        workspace_path = Path(str(workspace)) if not isinstance(workspace, Path) else workspace
        return build_soothe_workspace_section(workspace_path, git_status)

    def _build_thread_section(self, thread_context: dict) -> str | None:
        """Build <THREAD> section via shared context_xml builder."""
        if not thread_context:
            return None
        from soothe.core.prompts.context_xml import build_soothe_thread_section

        return build_soothe_thread_section(thread_context)

    def _build_protocols_section(self, protocol_summary: dict) -> str | None:
        """Build <PROTOCOLS> section via shared context_xml builder."""
        if not protocol_summary:
            return None
        from soothe.core.prompts.context_xml import build_soothe_protocols_section

        result = build_soothe_protocols_section(protocol_summary)
        return result or None

    def _build_scenario_section(self, intent_type: str, goal_type: str) -> str | None:
        """Build scenario-specific guidance section (IG-268).

        Injects targeted guidance based on intent classification and goal type.

        Args:
            intent_type: Intent classification (chitchat/quiz/continue_thread/new_goal).
            goal_type: Goal type classification (architecture_analysis/research_synthesis/etc).

        Returns:
            Scenario guidance text, or None if no matching scenario.
        """
        from soothe.core.prompts.system_templates import (
            _ARCHITECTURE_ANALYSIS_GUIDE,
            _QUIZ_RESPONSE_GUIDE,
            _RESEARCH_SYNTHESIS_GUIDE,
            _THREAD_CONTINUATION_GUIDE,
        )

        # Quiz intent: concise factual answers
        if intent_type == "quiz":
            return _QUIZ_RESPONSE_GUIDE

        # Continue-thread: build on prior context
        if intent_type == "continue_thread":
            return _THREAD_CONTINUATION_GUIDE

        # Architecture analysis: structured layers + components
        if goal_type == "architecture_analysis":
            return _ARCHITECTURE_ANALYSIS_GUIDE

        # Research synthesis: methodology + findings
        if goal_type == "research_synthesis":
            return _RESEARCH_SYNTHESIS_GUIDE

        # No specific scenario guidance
        return None

    def _build_agent_loop_output_contract_section(
        self, config: SootheConfig | None = None
    ) -> str | None:
        """Build <AGENT_LOOP_OUTPUT_CONTRACT> section for Layer 2 agent loop.

        Args:
            config: Optional SootheConfig to check if contract is enabled.

        Returns:
            XML section string, or None if contract is disabled.
        """
        if config is None or not config.agent_loop.agent_loop_output_contract_enabled:
            return None

        return (
            "<AGENT_LOOP_OUTPUT_CONTRACT>\n"
            "- After tool or subagent results arrive, add at most two short wrap-up sentences in your own words.\n"
            "- Do NOT paste the full tool/subagent output again unless the user explicitly asked for a "
            "verbatim repeat.\n"
            "- If the tool output already satisfies the user-visible deliverable, stop there.\n"
            "</AGENT_LOOP_OUTPUT_CONTRACT>"
        )

    @staticmethod
    def _extract_execution_hints_from_state(state: Any) -> str | None:
        """Extract execution hints text from state for user message envelope (RFC-214).

        ``ExecutionHintsMiddleware`` appends hints to ``state['system_prompt']``.
        Instead of merging into the system prompt (which breaks cache), we extract
        them here so the executor can place them in the user message envelope.

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
        ) or request.state.get("unified_classification")

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
        step_enforce = step_subagent is not None and first_after_user
        wire_enforce = explicit_subagent and first_after_user

        # Per-step hint wins over wire routing when both apply (IG-386).
        if step_enforce:
            directive = step_subagent
            logger.info(
                "AgentLoop step subagent hint (enforce): soothe_step_subagent=%s",
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
            # Drop directive after the first model hop so follow-up synthesis can use normal tools.
            try:
                request.state.pop("_subagent_routing_directive", None)
            except (AttributeError, TypeError):
                pass

        # Extract state for XML section building
        state_dict: dict[str, Any] = {}
        if hasattr(request.state, "get"):
            state_dict = {
                "workspace": request.state.get("workspace"),
                "git_status": request.state.get("git_status"),
                "thread_context": request.state.get("thread_context", {}),
                "protocol_summary": request.state.get("protocol_summary", {}),
                "messages": request.state.get("messages", []),
                "active_goals": request.state.get("active_goals", []),
                "context_projection": request.state.get("context_projection"),
                "recalled_memories": request.state.get("recalled_memories"),
                "_subagent_routing_directive": request.state.get("_subagent_routing_directive"),
                "intent_type": request.state.get("intent_type"),
                "synthesis_scenario": request.state.get("synthesis_scenario"),
            }

        optimized_prompt = self._get_prompt_for_complexity(complexity, state_dict)

        # Extract execution hints from state for user message envelope (RFC-214)
        hints_text = self._extract_execution_hints_from_state(request.state)
        if hints_text:
            request.state["_soothe_execution_hints"] = hints_text

        new_system_message = SystemMessage(content=optimized_prompt)
        overrides: dict[str, Any] = {"system_message": new_system_message}

        if step_enforce or wire_enforce:
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
            reset_langfuse_system_prompt_hint,
        )

        modified_request = self.modify_request(request)
        tok = self._langfuse_system_hint_push(modified_request)
        try:
            return handler(modified_request)
        finally:
            reset_langfuse_system_prompt_hint(tok)

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
            reset_langfuse_system_prompt_hint,
        )

        modified_request = self.modify_request(request)
        tok = self._langfuse_system_hint_push(modified_request)
        try:
            return await handler(modified_request)
        finally:
            reset_langfuse_system_prompt_hint(tok)
