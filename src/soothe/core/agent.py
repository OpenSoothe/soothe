"""Soothe agent factory -- wraps deepagents' `create_deep_agent`."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from deepagents import create_deep_agent
from langchain_core.language_models import BaseChatModel

from soothe.config import SootheConfig
from soothe.core.resolver import (
    SUBAGENT_FACTORIES,
    resolve_context,
    resolve_goal_engine,
    resolve_goal_tools,
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
    from collections.abc import Callable, Sequence

    from deepagents.backends.protocol import BackendFactory, BackendProtocol
    from deepagents.middleware.subagents import CompiledSubAgent, SubAgent
    from langchain.agents.middleware import InterruptOnConfig
    from langchain.agents.middleware.types import AgentMiddleware
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
) -> CompiledStateGraph:
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

    Protocol Attachments (attached to returned graph):
        - soothe_context: ContextProtocol instance
        - soothe_memory: MemoryProtocol instance
        - soothe_planner: PlannerProtocol instance
        - soothe_policy: PolicyProtocol instance
        - soothe_durability: DurabilityProtocol instance
        - soothe_config: SootheConfig instance
        - soothe_subagents: list of configured subagents

    Execution Interface:
        agent.astream(input, config) → AsyncIterator[StreamChunk]

        config.configurable may include Layer 2 hints:
            - soothe_step_tools: suggested tools (advisory)
            - soothe_step_subagent: suggested subagent (advisory)
            - soothe_step_expected_output: expected result (advisory)

    Wraps ``create_deep_agent()`` and wires up Soothe-specific protocols,
    subagents, tools, MCP servers, and skills from ``SootheConfig``.

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
        Compiled LangGraph agent.
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
    logger.debug("Protocols resolved in %.1fms", resolve_ms)

    if resolved_context:
        logger.info("Context: %s", type(resolved_context).__name__)
    if resolved_memory:
        logger.info("Memory: %s", type(resolved_memory).__name__)
    if resolved_planner:
        logger.info("Planner: %s", type(resolved_planner).__name__)
    if resolved_policy:
        logger.info("Policy: %s", type(resolved_policy).__name__)

    goal_engine = resolve_goal_engine(config)

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
    logger.info("Plugins loaded in %.1fms", plugins_ms)

    tools_start = time.perf_counter()
    config_tools = resolve_tools(config.tools, lazy=config.performance.parallel_tool_loading, config=config)
    goal_tools = resolve_goal_tools(goal_engine)
    all_tools: list[BaseTool | Callable | dict[str, Any]] = [*config_tools, *goal_tools]
    if tools:
        all_tools.extend(tools)
    tools_ms = (time.perf_counter() - tools_start) * 1000
    logger.info("Tools resolved in %.1fms", tools_ms)

    subagents_start = time.perf_counter()
    config_subagents = resolve_subagents(
        config, default_model=default_model_instance, lazy=config.performance.parallel_subagent_loading
    )
    all_subagents: list[SubAgent | CompiledSubAgent] = [*config_subagents]
    if subagents:
        all_subagents.extend(subagents)
    subagents_ms = (time.perf_counter() - subagents_start) * 1000
    logger.info("Subagents resolved in %.1fms", subagents_ms)

    resolved_backend = backend
    if resolved_backend is None:
        from soothe.core.filesystem import FrameworkFilesystem

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
        logger.info("System prompt optimization middleware enabled")

    # Add execution hints middleware for Layer 2 → Layer 1 integration (RFC-0023)
    default_middleware.append(ExecutionHintsMiddleware())
    logger.debug("Execution hints middleware enabled")

    if resolved_context:
        default_middleware.append(SubagentContextMiddleware(context=resolved_context))

    # Add parallel tools middleware for performance (always enabled with safe defaults)
    max_parallel_tools = config.execution.concurrency.max_parallel_tools if hasattr(config, "execution") else 3
    default_middleware.append(ParallelToolsMiddleware(max_parallel_tools=max_parallel_tools))
    logger.info("Parallel tools middleware enabled with max_parallel_tools=%d", max_parallel_tools)

    all_middleware: tuple[AgentMiddleware, ...] = (*default_middleware, *middleware)

    # Merge built-in skills with user-provided skills
    all_skills = get_built_in_skills_paths()
    if config.skills:
        all_skills.extend(config.skills)

    deep_agent_start = time.perf_counter()
    agent = create_deep_agent(
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
    logger.info("Deep agent created in %.1fms", deep_agent_ms)

    agent.soothe_context = resolved_context  # type: ignore[attr-defined]
    agent.soothe_memory = resolved_memory  # type: ignore[attr-defined]
    agent.soothe_planner = resolved_planner  # type: ignore[attr-defined]
    agent.soothe_policy = resolved_policy  # type: ignore[attr-defined]
    agent.soothe_goal_engine = goal_engine  # type: ignore[attr-defined]
    agent.soothe_config = config  # type: ignore[attr-defined]
    agent.soothe_subagents = all_subagents  # type: ignore[attr-defined]

    total_ms = (time.perf_counter() - create_start) * 1000
    logger.info("Soothe agent created in %.1fms", total_ms)

    return agent
