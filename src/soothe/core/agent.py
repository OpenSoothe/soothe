"""Soothe CoreAgent -- Layer 1 runtime (RFC-0023).

This module defines CoreAgent, a self-contained Layer 1 module with a clear
exposed interface for executing tools/subagents via LangGraph's
Model → Tools → Model loop.

Reference: RFC-0023 Layer 1 CoreAgent Runtime Architecture
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from deepagents import create_deep_agent
from langchain_core.language_models import BaseChatModel

from soothe.config import SootheConfig
from soothe.core.resolver import (
    SUBAGENT_FACTORIES,
    resolve_context,
    resolve_memory,
    resolve_planner,
    resolve_policy,
    resolve_subagents,
    resolve_tools,
)
from soothe.middleware.execution_hints import ExecutionHintsMiddleware
from soothe.middleware.parallel_tools import ParallelToolsMiddleware
from soothe.middleware.policy import SoothePolicyMiddleware
from soothe.middleware.subagent_context import SubagentContextMiddleware
from soothe.middleware.system_prompt_optimization import SystemPromptOptimizationMiddleware
from soothe.middleware.workspace_context import WorkspaceContextMiddleware
from soothe.skills import get_built_in_skills_paths


# ---------------------------------------------------------------------------
# Patch: deepagents SummarizationMiddleware._apply_event_to_messages does not
# handle langgraph's Overwrite wrapper that PatchToolCallsMiddleware may leave
# in request.messages.  Unwrap it so ``list(messages)`` succeeds.
# ---------------------------------------------------------------------------
def _patch_summarization_overwrite_handling() -> None:
    try:
        from deepagents.middleware.summarization import SummarizationMiddleware
        from langgraph.types import Overwrite
    except ImportError:
        return

    _original = SummarizationMiddleware._apply_event_to_messages

    @staticmethod  # type: ignore[misc]
    def _patched(messages: Any, event: Any) -> list[Any]:
        if isinstance(messages, Overwrite):
            messages = messages.value
        return _original(messages, event)

    SummarizationMiddleware._apply_event_to_messages = _patched  # type: ignore[assignment]


_patch_summarization_overwrite_handling()

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Sequence

    from deepagents.backends.protocol import BackendFactory, BackendProtocol
    from deepagents.middleware.subagents import CompiledSubAgent, SubAgent
    from langchain.agents.middleware import InterruptOnConfig
    from langchain.agents.middleware.types import AgentMiddleware
    from langchain_core.runnables import RunnableConfig
    from langchain_core.tools import BaseTool
    from langgraph.graph.state import CompiledStateGraph
    from langgraph.store.base import BaseStore
    from langgraph.types import Checkpointer

    from soothe.protocols.context import ContextProtocol
    from soothe.protocols.memory import MemoryProtocol
    from soothe.protocols.planner import PlannerProtocol
    from soothe.protocols.policy import PolicyProtocol

logger = logging.getLogger(__name__)

_SUBAGENT_FACTORIES = SUBAGENT_FACTORIES


class CoreAgent:
    """Layer 1 CoreAgent runtime (RFC-0023).

    Self-contained module wrapping CompiledStateGraph with explicit typed
    protocol properties. Pure execution runtime for tools, subagents, and
    middlewares - NO goal infrastructure (Layer 3 responsibility).

    Attributes:
        graph: Underlying CompiledStateGraph for advanced LangGraph operations.
        config: SootheConfig used to create this agent.
        context: ContextProtocol instance for context injection/persistence.
        memory: MemoryProtocol instance for memory recall/persistence.
        planner: PlannerProtocol instance for planning decisions.
        policy: PolicyProtocol instance for action policy checking.
        subagents: List of configured subagents available for delegation.

    Execution Interface:
        Use `astream(input, config)` for Layer 1 streaming execution.

        config.configurable may include Layer 2 hints (advisory):
            - soothe_step_tools: suggested tools for this step
            - soothe_step_subagent: suggested subagent for this step
            - soothe_step_expected_output: expected result description

    Example:
        config = SootheConfig.from_file("config.yml")
        agent = create_soothe_agent(config)

        # Layer 1 execution
        async for chunk in agent.astream("query", {"thread_id": "123"}):
            print(chunk)

        # Access protocols via typed properties
        context = agent.context
        memory = agent.memory

        # Advanced LangGraph operations via graph
        result = agent.graph.invoke({"messages": [...]})
    """

    def __init__(
        self,
        graph: CompiledStateGraph,
        config: SootheConfig,
        context: ContextProtocol | None = None,
        memory: MemoryProtocol | None = None,
        planner: PlannerProtocol | None = None,
        policy: PolicyProtocol | None = None,
        subagents: list[SubAgent | CompiledSubAgent] | None = None,
    ) -> None:
        """Initialize CoreAgent with graph and protocol instances.

        Args:
            graph: CompiledStateGraph from deepagents create_deep_agent().
            config: SootheConfig used for agent creation.
            context: ContextProtocol instance (or None if disabled).
            memory: MemoryProtocol instance (or None if disabled).
            planner: PlannerProtocol instance (or None if disabled).
            policy: PolicyProtocol instance (or None if disabled).
            subagents: List of configured subagents.
        """
        self._graph = graph
        self._config = config
        self._context = context
        self._memory = memory
        self._planner = planner
        self._policy = policy
        self._subagents = list(subagents) if subagents else []

    # --- Explicit typed properties ---
    @property
    def graph(self) -> CompiledStateGraph:
        """Underlying CompiledStateGraph for advanced LangGraph operations."""
        return self._graph

    @property
    def config(self) -> SootheConfig:
        """SootheConfig used to create this agent."""
        return self._config

    @property
    def context(self) -> ContextProtocol | None:
        """ContextProtocol instance for context injection/persistence."""
        return self._context

    @property
    def memory(self) -> MemoryProtocol | None:
        """MemoryProtocol instance for memory recall/persistence."""
        return self._memory

    @property
    def planner(self) -> PlannerProtocol | None:
        """PlannerProtocol instance for planning decisions."""
        return self._planner

    @property
    def policy(self) -> PolicyProtocol | None:
        """PolicyProtocol instance for action policy checking."""
        return self._policy

    @property
    def subagents(self) -> list[SubAgent | CompiledSubAgent]:
        """List of configured subagents available for delegation."""
        return self._subagents

    # --- Execution interface ---
    def astream(
        self,
        input_arg: str | dict,
        config: RunnableConfig | None = None,
        *,
        stream_mode: list[str] | None = None,
        subgraphs: bool = False,
    ) -> AsyncIterator[Any]:
        """Execute with Layer 1 streaming interface.

        Delegates to underlying CompiledStateGraph.astream(). Use this
        for standard Layer 1 execution from Layer 2 ACT phase or CLI/daemon.

        Args:
            input_arg: User query or execution instruction (str or dict with
                "messages" key for LangGraph format).
            config: RunnableConfig with thread_id and optional Layer 2 hints.
                Layer 2 hints in config.configurable (advisory):
                - soothe_step_tools: suggested tools for this step
                - soothe_step_subagent: suggested subagent
                - soothe_step_expected_output: expected result
            stream_mode: Optional list of stream modes (e.g., ["messages", "updates", "custom"]).
                If None, uses LangGraph defaults.
            subgraphs: Whether to include subgraph events in stream (default: False).

        Returns:
            AsyncIterator of StreamChunk events from LangGraph execution.

        Example:
            async for chunk in agent.astream(
                "Execute: Find config files",
                {"configurable": {"thread_id": "t-123"}}
            ):
                process(chunk)
        """
        # Log execution start
        thread_id = config.get("configurable", {}).get("thread_id", "unknown") if config else "unknown"
        hints = config.get("configurable", {}) if config else {}

        input_preview = input_arg if isinstance(input_arg, str) else str(input_arg)[:80]
        logger.debug(
            "[Exec] Starting execution (thread=%s): %s",
            thread_id,
            input_preview[:80],
        )

        # Log execution hints if present
        if hints.get("soothe_step_tools"):
            logger.debug("[Exec] Hint: suggested tools=%s", hints["soothe_step_tools"])
        if hints.get("soothe_step_subagent"):
            logger.debug("[Exec] Hint: suggested subagent=%s", hints["soothe_step_subagent"])

        if stream_mode:
            return self._graph.astream(input_arg, config or {}, stream_mode=stream_mode, subgraphs=subgraphs)
        return self._graph.astream(input_arg, config or {}, subgraphs=subgraphs)

    @classmethod
    def create(cls, config: SootheConfig | None = None, **kwargs: Any) -> CoreAgent:
        """Factory method - delegates to create_soothe_agent().

        Args:
            config: Soothe configuration. If None, uses defaults.
            **kwargs: Additional arguments passed to create_soothe_agent().

        Returns:
            CoreAgent instance.
        """
        return create_soothe_agent(config, **kwargs)


def create_soothe_agent(
    config: SootheConfig | None = None,
    *,
    model: str | BaseChatModel | None = None,
    tools: Sequence[BaseTool | Callable | dict[str, Any]] | None = None,
    subagents: list[SubAgent | CompiledSubAgent] | None = None,
    middleware: Sequence[AgentMiddleware] = (),
    checkpointer: Checkpointer | None = None,
    store: BaseStore | None = None,
    backend: BackendProtocol | BackendFactory | None = None,
    interrupt_on: dict[str, bool | InterruptOnConfig] | None = None,
    context: ContextProtocol | None = None,
    memory_store: MemoryProtocol | None = None,
    planner: PlannerProtocol | None = None,
    policy: PolicyProtocol | None = None,
) -> CoreAgent:
    """Factory that creates Soothe's Layer 1 CoreAgent runtime.

    Layer 1 Responsibilities:
        - Execute tools/subagents via LangGraph Model → Tools → Model loop
        - Apply middlewares (context, memory, policy, planner, hints)
        - Manage thread state (sequential vs parallel execution)
        - Consider execution hints from Layer 2 (advisory suggestions)

    Built-in Capabilities:
        - Tools: execution, websearch, research, etc.
        - Subagents: Browser, Claude, Skillify, Weaver
        - MCP servers: loaded via configuration
        - Middlewares: policy, system prompt optimization, hints, context, memory, parallel tools

    Returns CoreAgent instance with typed protocol properties:
        - agent.context: ContextProtocol instance
        - agent.memory: MemoryProtocol instance
        - agent.planner: PlannerProtocol instance
        - agent.policy: PolicyProtocol instance
        - agent.config: SootheConfig instance
        - agent.subagents: list of configured subagents
        - agent.graph: underlying CompiledStateGraph

    Execution Interface:
        agent.astream(input, config) → AsyncIterator[StreamChunk]

        config.configurable may include Layer 2 hints:
            - soothe_step_tools: suggested tools (advisory)
            - soothe_step_subagent: suggested subagent (advisory)
            - soothe_step_expected_output: expected result (advisory)

    Note: Goal management (GoalEngine, goal_tools) is NOT included.
    That is Layer 3 responsibility - resolve separately in SootheRunner.

    Args:
        config: Soothe configuration. If ``None``, uses defaults.
        model: Override the model from config. Passed to ``create_deep_agent``.
        tools: Additional tools beyond what config specifies.
        subagents: Additional subagents beyond what config specifies.
        middleware: Additional middleware appended after the standard stack.
        checkpointer: LangGraph checkpointer for persistence.
        store: LangGraph store for persistent storage.
        backend: deepagents backend for file/execution operations.
        interrupt_on: Tool interrupt configuration for human-in-the-loop.
        context: Override ContextProtocol implementation. None uses config.
        memory_store: Override MemoryProtocol implementation. None uses config.
        planner: Override PlannerProtocol implementation. None uses config.
        policy: Override PolicyProtocol implementation. None uses config.

    Returns:
        CoreAgent instance wrapping CompiledStateGraph with typed properties.
    """
    import time

    create_start = time.perf_counter()

    if config is None:
        config = SootheConfig()

    config.propagate_env()

    resolved_model: str | BaseChatModel
    resolved_model = model if model is not None else config.create_chat_model("default")

    default_model_instance = resolved_model if isinstance(resolved_model, BaseChatModel) else None

    # Resolve protocols with timing
    resolve_start = time.perf_counter()

    # Use parallel resolution when enabled and protocols not provided
    if config.performance.parallel_protocol_resolution and not any([context, memory_store, planner, policy]):
        try:
            import asyncio

            # Check if we're already in an async context before creating coroutines
            try:
                asyncio.get_running_loop()
                # We're in an async context, use sequential
                logger.debug("Parallel protocol resolution not available in async context, using sequential")
                resolved_context = context or resolve_context(config)
                resolved_memory = memory_store or resolve_memory(config)
                resolved_planner = planner or resolve_planner(config, default_model_instance)
                resolved_policy = policy or resolve_policy(config)
            except RuntimeError:
                # No running loop, safe to use asyncio.run()
                async def resolve_protocols_parallel() -> list[object]:
                    return await asyncio.gather(
                        asyncio.to_thread(resolve_context, config),
                        asyncio.to_thread(resolve_memory, config),
                        asyncio.to_thread(resolve_planner, config, default_model_instance),
                        asyncio.to_thread(resolve_policy, config),
                        return_exceptions=True,
                    )

                results = asyncio.run(resolve_protocols_parallel())
                resolved_context, resolved_memory, resolved_planner, resolved_policy = [
                    r if not isinstance(r, Exception) else None for r in results
                ]
        except RuntimeError:
            # Fallback to sequential
            logger.debug("Parallel protocol resolution failed, using sequential")
            resolved_context = context or resolve_context(config)
            resolved_memory = memory_store or resolve_memory(config)
            resolved_planner = planner or resolve_planner(config, default_model_instance)
            resolved_policy = policy or resolve_policy(config)
    else:
        # Sequential fallback
        resolved_context = context or resolve_context(config)
        resolved_memory = memory_store or resolve_memory(config)
        resolved_planner = planner or resolve_planner(config, default_model_instance)
        resolved_policy = policy or resolve_policy(config)

    resolve_ms = (time.perf_counter() - resolve_start) * 1000
    logger.debug("[Init] Protocols resolved (%.1fms)", resolve_ms)

    if resolved_context:
        logger.info("[Init] Context: %s", type(resolved_context).__name__)
    if resolved_memory:
        logger.info("[Init] Memory: %s", type(resolved_memory).__name__)
    if resolved_planner:
        logger.info("[Init] Planner: %s", type(resolved_planner).__name__)
    if resolved_policy:
        logger.info("[Init] Policy: %s", type(resolved_policy).__name__)

    # Load plugins
    import asyncio

    from soothe.plugin.global_registry import load_plugins

    plugins_start = time.perf_counter()
    try:
        # Check if we're already in an async context
        try:
            asyncio.get_running_loop()
            # Already in async context, skip for now
            # (plugins will be loaded in async context if needed)
            logger.debug("Skipping plugin loading in async context")
        except RuntimeError:
            # No running loop, safe to use asyncio.run()
            asyncio.run(load_plugins(config))
    except RuntimeError:
        logger.debug("Plugin loading failed, will load on demand")
    plugins_ms = (time.perf_counter() - plugins_start) * 1000
    logger.info("[Init] Plugins loaded (%.1fms)", plugins_ms)

    # Resolve tools (NO goal_tools - Layer 3 responsibility)
    tools_start = time.perf_counter()
    config_tools = resolve_tools(config.tools, lazy=config.performance.parallel_tool_loading, config=config)
    all_tools: list[BaseTool | Callable | dict[str, Any]] = list(config_tools)
    if tools:
        all_tools.extend(tools)
    tools_ms = (time.perf_counter() - tools_start) * 1000
    logger.info("[Init] Tools resolved: %d tools (%.1fms)", len(all_tools), tools_ms)

    subagents_start = time.perf_counter()
    config_subagents = resolve_subagents(
        config, default_model=default_model_instance, lazy=config.performance.parallel_subagent_loading
    )
    all_subagents: list[SubAgent | CompiledSubAgent] = list(config_subagents)
    if subagents:
        all_subagents.extend(subagents)
    subagents_ms = (time.perf_counter() - subagents_start) * 1000
    logger.info("[Init] Subagents resolved: %d agents (%.1fms)", len(all_subagents), subagents_ms)

    resolved_backend = backend
    if resolved_backend is None:
        from soothe.safety import FrameworkFilesystem

        # Initialize framework-wide singleton
        # Use deepagents FilesystemBackend directly with proper virtual_mode semantics
        # No wrapper needed - virtual_mode handles path containment correctly
        resolved_backend = FrameworkFilesystem.initialize(
            config=config,
            policy=resolved_policy,
        )

    default_middleware: list[AgentMiddleware] = []
    if resolved_policy:
        default_middleware.append(
            SoothePolicyMiddleware(
                policy=resolved_policy,
                profile_name=config.protocols.policy.profile,
            )
        )

    # Add system prompt optimization middleware if enabled (requires both features)
    if (
        config.performance.enabled
        and config.performance.optimize_system_prompts
        and config.performance.unified_classification
    ):
        default_middleware.append(SystemPromptOptimizationMiddleware(config=config))
        logger.info("[Init] System prompt optimization enabled")

    # Add execution hints middleware for Layer 2 → Layer 1 integration (RFC-0023)
    default_middleware.append(ExecutionHintsMiddleware())
    logger.debug("[Init] Execution hints middleware enabled")

    # Add workspace context middleware for thread-aware workspace (RFC-103)
    default_middleware.append(WorkspaceContextMiddleware())
    logger.debug("[Init] Workspace context middleware enabled")

    if resolved_context:
        default_middleware.append(SubagentContextMiddleware(context=resolved_context))

    # Add parallel tools middleware for performance (always enabled with safe defaults)
    max_parallel_tools = config.execution.concurrency.max_parallel_tools if hasattr(config, "execution") else 3
    default_middleware.append(ParallelToolsMiddleware(max_parallel_tools=max_parallel_tools))
    logger.info("[Init] Parallel tools middleware (max=%d)", max_parallel_tools)

    all_middleware: tuple[AgentMiddleware, ...] = (*default_middleware, *middleware)

    # Merge built-in skills with user-provided skills
    all_skills = get_built_in_skills_paths()
    if config.skills:
        all_skills.extend(config.skills)

    deep_agent_start = time.perf_counter()
    graph = create_deep_agent(
        model=resolved_model,
        tools=all_tools or None,
        system_prompt=config.resolve_system_prompt(),
        middleware=all_middleware,
        subagents=all_subagents or None,
        skills=all_skills or None,
        memory=config.memory or None,
        checkpointer=checkpointer,
        store=store,
        backend=resolved_backend,
        interrupt_on=interrupt_on,
        debug=config.debug,
    )
    deep_agent_ms = (time.perf_counter() - deep_agent_start) * 1000
    logger.info("[Init] Deep agent graph created (%.1fms)", deep_agent_ms)

    # Wrap graph in CoreAgent with typed protocol properties
    agent = CoreAgent(
        graph=graph,
        config=config,
        context=resolved_context,
        memory=resolved_memory,
        planner=resolved_planner,
        policy=resolved_policy,
        subagents=all_subagents,
    )

    total_ms = (time.perf_counter() - create_start) * 1000
    logger.info("[Init] ✓ CoreAgent ready (%.1fms total)", total_ms)

    return agent
