"""CoreAgent construction logic (internal).

Encapsulates protocol resolution, middleware stack, and backend initialization.
This module separates construction concerns from the CoreAgent interface.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from soothe.config import SootheConfig
from soothe.skills import get_built_in_skills_paths

# Import and apply deepagents patches
from soothe_daemon.core.agent._patch import *  # noqa: F403
from soothe_daemon.core.middleware import build_soothe_middleware_stack
from soothe_daemon.core.resolver import (
    resolve_memory,
    resolve_planner,
    resolve_policy,
    resolve_subagents,
    resolve_tools,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from deepagents.backends.protocol import BackendFactory, BackendProtocol
    from deepagents.middleware.subagents import CompiledSubAgent, SubAgent
    from langchain.agents.middleware import InterruptOnConfig
    from langchain.agents.middleware.types import AgentMiddleware
    from langchain_core.tools import BaseTool
    from langgraph.store.base import BaseStore
    from langgraph.types import Checkpointer

    from soothe_daemon.protocols.memory import MemoryProtocol
    from soothe_daemon.protocols.planner import PlannerProtocol
    from soothe_daemon.protocols.policy import PolicyProtocol

# Runtime imports (used in isinstance checks)
from langchain_core.language_models import BaseChatModel

from soothe_daemon.core.agent._core import CoreAgent

logger = logging.getLogger(__name__)


class AgentBuilder:
    """Builder for CoreAgent instances.

    Encapsulates all construction concerns in a single class:
    - Protocol resolution (memory, planner, policy)
    - Middleware stack construction
    - Backend initialization
    - Plugin loading
    - Tools/subagents resolution

    This separates the complex construction logic from the simple CoreAgent
    interface, making both easier to understand and maintain.

    Example:
        builder = AgentBuilder(config)
        agent = builder.build(checkpointer=my_checkpointer)
    """

    def __init__(self, config: SootheConfig | None = None) -> None:
        """Initialize builder with configuration.

        Args:
            config: Soothe configuration. If None, uses defaults.
        """
        self._config = config or SootheConfig()
        self._config.propagate_env()

    def build(
        self,
        *,
        model: str | BaseChatModel | None = None,
        tools: Sequence[BaseTool | Callable | dict[str, Any]] | None = None,
        subagents: list[SubAgent | CompiledSubAgent] | None = None,
        middleware: Sequence[AgentMiddleware] = (),
        checkpointer: Checkpointer | None = None,
        store: BaseStore | None = None,
        backend: BackendProtocol | BackendFactory | None = None,
        interrupt_on: dict[str, bool | InterruptOnConfig] | None = None,
        memory_store: MemoryProtocol | None = None,
        planner: PlannerProtocol | None = None,
        policy: PolicyProtocol | None = None,
    ) -> CoreAgent:
        """Build CoreAgent with all components.

        Layer 1 Responsibilities:
            - Execute tools/subagents via LangGraph Model → Tools → Model loop
            - Apply middlewares (context, memory, policy, planner, hints)
            - Manage thread state (sequential vs parallel execution)
            - Consider execution hints from Layer 2 (advisory suggestions)

        Built-in Capabilities:
            - Tools: execution, websearch, research, etc.
            - Subagents: Browser, Claude, Research
            - MCP servers: loaded via configuration
            - Middlewares: policy, system prompt optimization, hints, context, memory

        Args:
            model: Override the model from config. Passed to ``create_deep_agent``.
            tools: Additional tools beyond what config specifies.
            subagents: Additional subagents beyond what config specifies.
            middleware: Additional middleware appended after the standard stack.
            checkpointer: LangGraph checkpointer for persistence.
            store: LangGraph store for persistent storage.
            backend: deepagents backend for file/execution operations.
            interrupt_on: Tool interrupt configuration for human-in-the-loop.
            memory_store: Override MemoryProtocol implementation. None uses config.
            planner: Override PlannerProtocol implementation. None uses config.
            policy: Override PolicyProtocol implementation. None uses config.

        Returns:
            CoreAgent instance wrapping CompiledStateGraph with typed properties.
        """
        from deepagents import create_deep_agent

        create_start = time.perf_counter()

        # Resolve model
        resolved_model: str | BaseChatModel
        resolved_model = model if model is not None else self._config.create_chat_model("default")
        default_model_instance = (
            resolved_model if isinstance(resolved_model, BaseChatModel) else None
        )

        # Resolve protocols
        resolve_start = time.perf_counter()
        resolved_memory = memory_store or self._resolve_memory()
        resolved_planner = planner or self._resolve_planner(default_model_instance)
        resolved_policy = policy or self._resolve_policy()
        resolve_ms = (time.perf_counter() - resolve_start) * 1000
        logger.debug("[Init] Protocols resolved (%.1fms)", resolve_ms)

        if resolved_memory:
            logger.info("[Init] Memory: %s", type(resolved_memory).__name__)
        if resolved_planner:
            logger.info("[Init] Planner: %s", type(resolved_planner).__name__)
        if resolved_policy:
            logger.info("[Init] Policy: %s", type(resolved_policy).__name__)

        # Load plugins
        self._load_plugins()

        # Resolve tools (NO goal_tools - Layer 3 responsibility)
        tools_start = time.perf_counter()
        config_tools = resolve_tools(
            self._config.tools,
            lazy=self._config.performance.parallel_tool_loading,
            config=self._config,
        )
        all_tools: list[BaseTool | Callable | dict[str, Any]] = list(config_tools)
        if tools:
            all_tools.extend(tools)
        tools_ms = (time.perf_counter() - tools_start) * 1000
        logger.info("[Init] Tools resolved: %d tools (%.1fms)", len(all_tools), tools_ms)

        # Resolve subagents
        subagents_start = time.perf_counter()
        config_subagents = resolve_subagents(
            self._config,
            default_model=default_model_instance,
            lazy=self._config.performance.parallel_subagent_loading,
        )
        all_subagents: list[SubAgent | CompiledSubAgent] = list(config_subagents)
        if subagents:
            all_subagents.extend(subagents)
        subagents_ms = (time.perf_counter() - subagents_start) * 1000
        logger.info(
            "[Init] Subagents resolved: %d agents (%.1fms)", len(all_subagents), subagents_ms
        )

        # Initialize backend
        resolved_backend = backend or self._initialize_backend(resolved_policy)

        # Build middleware stack
        default_middleware = build_soothe_middleware_stack(
            self._config,
            resolved_policy,
        )
        all_middleware: tuple[AgentMiddleware, ...] = (*default_middleware, *middleware)

        # Merge built-in skills with user-provided skills
        all_skills = get_built_in_skills_paths()
        if self._config.skills:
            all_skills.extend(self._config.skills)

        # Create deep_agent graph
        deep_agent_start = time.perf_counter()
        graph = create_deep_agent(
            model=resolved_model,
            tools=all_tools or None,
            system_prompt=self._config.resolve_system_prompt(),
            middleware=all_middleware,
            subagents=all_subagents or None,
            skills=all_skills or None,
            memory=self._config.memory or None,
            checkpointer=checkpointer,
            store=store,
            backend=resolved_backend,
            interrupt_on=interrupt_on,
            debug=self._config.debug,
        )
        deep_agent_ms = (time.perf_counter() - deep_agent_start) * 1000
        logger.info("[Init] Deep agent graph created (%.1fms)", deep_agent_ms)

        # Wrap graph in CoreAgent with typed protocol properties
        agent = CoreAgent(
            graph=graph,
            config=self._config,
            memory=resolved_memory,
            planner=resolved_planner,
            policy=resolved_policy,
            subagents=all_subagents,
        )

        total_ms = (time.perf_counter() - create_start) * 1000
        logger.info("[Init] ✓ CoreAgent ready (%.1fms total)", total_ms)

        return agent

    def _resolve_memory(self) -> MemoryProtocol | None:
        """Resolve MemoryProtocol with parallel resolution support."""
        if self._config.performance.parallel_protocol_resolution:
            try:
                import asyncio

                try:
                    asyncio.get_running_loop()
                    return resolve_memory(self._config)
                except RuntimeError:
                    result = asyncio.run(asyncio.to_thread(resolve_memory, self._config))
                    return result if not isinstance(result, Exception) else None
            except RuntimeError:
                return resolve_memory(self._config)
        return resolve_memory(self._config)

    def _resolve_planner(self, default_model: BaseChatModel | None) -> PlannerProtocol | None:
        """Resolve PlannerProtocol with parallel resolution support."""
        if self._config.performance.parallel_protocol_resolution:
            try:
                import asyncio

                try:
                    asyncio.get_running_loop()
                    return resolve_planner(self._config, default_model)
                except RuntimeError:
                    result = asyncio.run(
                        asyncio.to_thread(resolve_planner, self._config, default_model)
                    )
                    return result if not isinstance(result, Exception) else None
            except RuntimeError:
                return resolve_planner(self._config, default_model)
        return resolve_planner(self._config, default_model)

    def _resolve_policy(self) -> PolicyProtocol | None:
        """Resolve PolicyProtocol with parallel resolution support."""
        if self._config.performance.parallel_protocol_resolution:
            try:
                import asyncio

                try:
                    asyncio.get_running_loop()
                    return resolve_policy(self._config)
                except RuntimeError:
                    result = asyncio.run(asyncio.to_thread(resolve_policy, self._config))
                    return result if not isinstance(result, Exception) else None
            except RuntimeError:
                return resolve_policy(self._config)
        return resolve_policy(self._config)

    def _load_plugins(self) -> None:
        """Load plugins from global registry."""
        import asyncio

        from soothe_daemon.plugin.global_registry import load_plugins

        plugins_start = time.perf_counter()
        try:
            try:
                asyncio.get_running_loop()
                # Already in async context, skip for now
                logger.debug("[Init] Skipping plugin loading in async context")
            except RuntimeError:
                # No running loop, safe to use asyncio.run()
                asyncio.run(load_plugins(self._config))
        except RuntimeError:
            logger.debug("[Init] Plugin loading failed, will load on demand")
        plugins_ms = (time.perf_counter() - plugins_start) * 1000
        logger.info("[Init] Plugins loaded (%.1fms)", plugins_ms)

    def _initialize_backend(
        self,
        policy: PolicyProtocol | None,
    ) -> BackendProtocol | BackendFactory:
        """Initialize FrameworkFilesystem backend."""
        from soothe.core import FrameworkFilesystem

        return FrameworkFilesystem.initialize(
            config=self._config,
            policy=policy,
        )


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
    memory_store: MemoryProtocol | None = None,
    planner: PlannerProtocol | None = None,
    policy: PolicyProtocol | None = None,
) -> CoreAgent:
    """Factory that creates Soothe's Layer 1 CoreAgent runtime.

    This is a thin wrapper delegating to AgentBuilder for backward compatibility.
    See AgentBuilder.build() for full parameter documentation.

    Note: Goal management (GoalEngine, goal_tools) is NOT included.
    That is Layer 3 responsibility - resolve separately in SootheRunner.

    Args:
        config: Soothe configuration. If ``None``, uses defaults.
        model: Override the model from config.
        tools: Additional tools beyond config.
        subagents: Additional subagents beyond config.
        middleware: Additional middleware after standard stack.
        checkpointer: LangGraph checkpointer for persistence.
        store: LangGraph store for persistent storage.
        backend: deepagents backend for file/execution operations.
        interrupt_on: Tool interrupt configuration for HITL.
        memory_store: Override MemoryProtocol implementation.
        planner: Override PlannerProtocol implementation.
        policy: Override PolicyProtocol implementation.

    Returns:
        CoreAgent instance wrapping CompiledStateGraph with typed properties.
    """
    return AgentBuilder(config).build(
        model=model,
        tools=tools,
        subagents=subagents,
        middleware=middleware,
        checkpointer=checkpointer,
        store=store,
        backend=backend,
        interrupt_on=interrupt_on,
        memory_store=memory_store,
        planner=planner,
        policy=policy,
    )
