"""CoreAgent construction logic (internal).

Encapsulates protocol resolution, middleware stack, and backend initialization.
This module separates construction concerns from the CoreAgent interface.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from soothe.config import SootheConfig
from soothe.foundation.core.agent._execute_filter import (
    without_execute_tool_when_sandbox_disabled,
)
from soothe.foundation.core.agent._patch_summarization import (
    apply_summarization_patches,
)
from soothe.foundation.core.agent._patch_task_tool import (
    apply_task_tool_patch,
    general_purpose_subagent_build_context,
)
from soothe.middleware import build_soothe_middleware_stack
from soothe.runner.resolver import (
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

    from soothe.middleware.identity import IdentityRuntime
    from soothe.protocols.memory import MemoryProtocol
    from soothe.protocols.planner import PlannerProtocol
    from soothe.protocols.policy import PolicyProtocol

# Runtime imports placed after TYPE_CHECKING block to avoid circular imports
# (CoreAgent pulls in the loop engine + protocols chain).
from langchain_core.language_models import BaseChatModel  # noqa: E402

from soothe.foundation.core.agent._core import CoreAgent  # noqa: E402

# Apply all patches at module import time (after all imports complete)
apply_summarization_patches()
apply_task_tool_patch()

logger = logging.getLogger(__name__)


class AgentBuilder:
    """Builder for CoreAgent instances.

    Encapsulates all construction concerns in a single class:
    - Protocol resolution (memory, planner, policy)
    - Middleware stack construction
    - Backend initialization
    - Plugin loading
    - Tools/subagents resolution
    - MCP registry integration (RFC-412)

    This separates the complex construction logic from the simple CoreAgent
    interface, making both easier to understand and maintain.

    Example:
        builder = AgentBuilder(config)
        agent = builder.build(checkpointer=my_checkpointer)
    """

    def __init__(
        self,
        config: SootheConfig | None = None,
        mcp_registry: Any | None = None,
    ) -> None:
        """Initialize builder with configuration.

        Args:
            config: Soothe configuration. If None, uses defaults.
            mcp_registry: MCPRegistry instance for MCP tool integration (RFC-412).
        """
        self._config = config or SootheConfig()
        self._config.propagate_env()
        self._mcp_registry = mcp_registry

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
        mcp_registry: Any | None = None,
        identity_runtime: IdentityRuntime | None = None,
    ) -> CoreAgent:
        """Build CoreAgent with all components.

        Layer 1 Responsibilities:
            - Execute tools/subagents via LangGraph Model → Tools → Model loop
            - Apply middlewares (context, memory, policy, planner, hints)
            - Manage thread state (sequential vs parallel execution)
            - Consider execution hints from Layer 2 (advisory suggestions)

        Built-in Capabilities:
            - Tools: execution, websearch, research, etc.
            - Subagents: browser_use, explore, plan, tacitus
            - MCP servers: loaded via configuration
            - Middlewares: policy, system prompt optimization, hints, context, memory

        Args:
            model: Override the model from config. Passed to ``create_deep_agent``.
            tools: Additional tools beyond what config specifies.
            subagents: Additional subagents beyond what config specifies.
            middleware: Additional middleware appended after the standard stack.
            checkpointer: LangGraph checkpointer for persistence.
            store: LangGraph store for persistent storage.
            backend: Backend for file/execution operations.
            interrupt_on: Optional tool interrupt configuration.
            memory_store: Override MemoryProtocol implementation. None uses config.
            planner: Override PlannerProtocol implementation. None uses config.
            policy: Override PolicyProtocol implementation. None uses config.
            mcp_registry: Override MCPRegistry. None uses builder's instance (RFC-412).
            identity_runtime: Optional identity bundle (RFC-307). When enabled,
                IdentityMiddleware is prepended to the stack.

        Returns:
            CoreAgent instance wrapping CompiledStateGraph with typed properties.
        """
        # Route based on core_agent_backend config
        core_agent_backend = self._config.agent.core_agent_backend
        logger.info("[Init] core_agent_backend=%s", core_agent_backend)
        if core_agent_backend == "claude":
            return self._build_claude_agent(
                memory_store=memory_store,
                planner=planner,
                policy=policy,
            )

        # Default: LangGraph-based CoreAgent
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
            lazy=True,  # Always load tools in parallel (default behavior)
            config=self._config,
        )
        all_tools: list[BaseTool | Callable | dict[str, Any]] = list(config_tools)
        if tools:
            all_tools.extend(tools)

        # RFC-412: Append MCP always-loaded tools (defer=False servers)
        registry = mcp_registry or self._mcp_registry
        if registry is not None:
            mcp_tools = registry.always_loaded_tools()
            if mcp_tools:
                all_tools.extend(mcp_tools)
                logger.debug("[Init] MCP tools: %d always-loaded", len(mcp_tools))

            # Synthetic MCP resource tools (list + read)
            from soothe.mcp.tools import create_mcp_resource_tools

            all_tools.extend(create_mcp_resource_tools(registry))
            logger.debug("[Init] MCP resource tools added")

        # Filter out execute tool when sandbox is disabled (IG-sandbox)
        before = len(all_tools)
        all_tools = without_execute_tool_when_sandbox_disabled(
            all_tools, security_sandbox_enabled=self._config.security.sandbox
        )
        if len(all_tools) < before:
            logger.debug("Sandbox disabled: execute tool filtered out")

        if (
            self._config.progressive_tools.enabled
            and self._config.progressive_tools.search_tools_enabled
        ):
            from soothe.toolkits.progressive.search_tool import create_search_tools_tool

            all_tools.append(create_search_tools_tool())
            logger.debug("[Init] Progressive search_tools added")

        if self._config.progressive_skills.search_skills_enabled:
            from soothe.skills.discovery_tools import (
                create_invoke_skill_tool,
                create_search_skills_tool,
            )

            all_tools.append(create_search_skills_tool())
            all_tools.append(create_invoke_skill_tool())
            logger.debug("[Init] Progressive search_skills + invoke_skill added")

        tools_ms = (time.perf_counter() - tools_start) * 1000
        logger.info("[Init] Tools resolved: %d tools (%.1fms)", len(all_tools), tools_ms)

        # Resolve subagents
        subagents_start = time.perf_counter()
        config_subagents = resolve_subagents(
            self._config,
            default_model=default_model_instance,
            lazy=True,  # Always load subagents in parallel (default behavior)
        )
        all_subagents: list[SubAgent | CompiledSubAgent] = list(config_subagents)
        if subagents:
            all_subagents.extend(subagents)
        subagents_ms = (time.perf_counter() - subagents_start) * 1000
        logger.info(
            "[Init] Subagents resolved: %d agents (%.1fms)", len(all_subagents), subagents_ms
        )

        registry = mcp_registry or self._mcp_registry

        # Initialize backend
        resolved_backend = backend or self._initialize_backend(resolved_policy)

        # Build middleware stack (RFC-412: pass mcp_registry; RFC-307: pass identity)
        default_middleware = build_soothe_middleware_stack(
            self._config,
            resolved_policy,
            mcp_registry=registry,
            identity_runtime=identity_runtime,
        )
        if all_tools:
            from soothe.middleware.progressive_tools import ProgressiveToolMiddleware

            for mw in default_middleware:
                if isinstance(mw, ProgressiveToolMiddleware):
                    mw.set_tool_catalog(all_tools)
                    break
        all_middleware: tuple[AgentMiddleware, ...] = (*default_middleware, *middleware)

        # RFC-105: Skill emission is owned by SystemPromptMiddleware via
        # ProgressiveSkillRegistry. Deepagents' SkillsMiddleware must not also emit.
        # Pass skills=None so the middleware is never installed.

        # Create deep_agent graph
        from soothe.middleware.model_call_profiler import (
            install_model_call_profiler,
            is_profiler_enabled,
        )

        install_model_call_profiler(enabled=is_profiler_enabled(self._config))

        def _compile_deep_agent(cp: Checkpointer | None) -> Any:
            gp_enabled = self._config.agent.runtime.general_purpose_subagent
            with general_purpose_subagent_build_context(gp_enabled):
                return create_deep_agent(
                    model=resolved_model,
                    tools=all_tools or None,
                    system_prompt=self._config.resolve_system_prompt(),
                    middleware=all_middleware,
                    subagents=all_subagents or None,
                    skills=None,
                    memory=self._config.memory or None,
                    checkpointer=cp,
                    store=store,
                    backend=resolved_backend,
                    interrupt_on=interrupt_on,
                    debug=self._config.debug,
                )

        deep_agent_start = time.perf_counter()
        graph = _compile_deep_agent(checkpointer)
        deep_agent_ms = (time.perf_counter() - deep_agent_start) * 1000
        logger.info("[Init] Deep agent graph created (%.1fms)", deep_agent_ms)

        execute_graph = None
        execute_graph_compiler = None
        from soothe.foundation.sloop.engine.executor import ephemeral_execute_stream_enabled

        if ephemeral_execute_stream_enabled():

            def execute_graph_compiler() -> Any:
                return _compile_deep_agent(None)

        # Wrap graph in CoreAgent with typed protocol properties
        agent = CoreAgent(
            graph=graph,
            config=self._config,
            memory=resolved_memory,
            planner=resolved_planner,
            policy=resolved_policy,
            subagents=all_subagents,
            execute_graph=execute_graph,
            execute_graph_compiler=execute_graph_compiler,
        )

        total_ms = (time.perf_counter() - create_start) * 1000
        logger.info("[Init] CoreAgent ready (%.1fms total)", total_ms)

        return agent

    def _resolve_memory(self) -> MemoryProtocol | None:
        """Resolve MemoryProtocol with parallel resolution support (always enabled)."""
        # Always resolve in parallel (default behavior)
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

    def _resolve_planner(self, default_model: BaseChatModel | None) -> PlannerProtocol | None:
        """Resolve PlannerProtocol with parallel resolution support (always enabled)."""
        # Always resolve in parallel (default behavior)
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

    def _resolve_policy(self) -> PolicyProtocol | None:
        """Resolve PolicyProtocol with parallel resolution support (always enabled)."""
        # Always resolve in parallel (default behavior)
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

    def _load_plugins(self) -> None:
        """Load plugins from global registry.

        Uses thread pool when already in async context (e.g., daemon thread runner)
        to avoid skipping plugin loading entirely.
        """
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        from soothe.plugin.global_registry import load_plugins

        plugins_start = time.perf_counter()
        try:
            coro = load_plugins(self._config)
            try:
                asyncio.get_running_loop()

                # Already in async context: run on a worker thread with fresh loop
                def _run_async_on_fresh_loop() -> None:
                    asyncio.run(coro)

                with ThreadPoolExecutor(max_workers=1) as pool:
                    pool.submit(_run_async_on_fresh_loop).result()
            except RuntimeError:
                # No running loop, safe to use asyncio.run()
                asyncio.run(coro)
        except RuntimeError:
            logger.debug("[Init] Plugin loading failed, will load on demand")
        plugins_ms = (time.perf_counter() - plugins_start) * 1000
        logger.info("[Init] Plugins loaded (%.1fms)", plugins_ms)

    def _initialize_backend(
        self,
        policy: PolicyProtocol | None,
    ) -> BackendProtocol | BackendFactory:
        """Initialize FrameworkFilesystem backend."""
        from soothe.foundation.workspace import FrameworkFilesystem

        return FrameworkFilesystem.initialize(
            config=self._config,
            policy=policy,
        )

    def _build_claude_agent(
        self,
        memory_store: MemoryProtocol | None = None,
        planner: PlannerProtocol | None = None,
        policy: PolicyProtocol | None = None,
    ) -> CoreAgent:
        """Build ClaudeCoreAgent using claude-agent-sdk.

        This is an alternative to the LangGraph-based CoreAgent that uses
        claude-agent-sdk (Claude Code CLI) for execution.

        Args:
            memory_store: Override MemoryProtocol implementation.
            planner: Override PlannerProtocol implementation.
            policy: Override PolicyProtocol implementation.

        Returns:
            ClaudeCoreAgent instance (typed as CoreAgent for compatibility).
        """
        from pathlib import Path

        from soothe.foundation.core.agent._claude_agent import ClaudeCoreAgent

        create_start = time.perf_counter()

        # Resolve protocols
        resolved_memory = memory_store or self._resolve_memory()
        resolved_planner = planner or self._resolve_planner(None)
        resolved_policy = policy or self._resolve_policy()

        if resolved_memory:
            logger.info("[Init] Memory: %s", type(resolved_memory).__name__)
        if resolved_planner:
            logger.info("[Init] Planner: %s", type(resolved_planner).__name__)
        if resolved_policy:
            logger.info("[Init] Policy: %s", type(resolved_policy).__name__)

        # Build ClaudeCoreAgent
        agent = ClaudeCoreAgent(
            config=self._config,
            model=self._config.agent.claude_model,
            system_prompt=self._config.resolve_system_prompt(),
            permission_mode=self._config.agent.claude_permission_mode,
            max_turns=self._config.agent.claude_max_turns,
            cwd=str(Path.cwd()),
            memory=resolved_memory,
            planner=resolved_planner,
            policy=resolved_policy,
        )

        total_ms = (time.perf_counter() - create_start) * 1000
        logger.info("[Init] ClaudeCoreAgent ready (%.1fms total)", total_ms)

        return agent


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
    identity_runtime: IdentityRuntime | None = None,
) -> CoreAgent:
    """Factory that creates Soothe's Layer 1 CoreAgent runtime.

    This is a thin wrapper delegating to AgentBuilder.
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
        backend: Backend for file/execution operations.
        interrupt_on: Optional tool interrupt configuration.
        memory_store: Override MemoryProtocol implementation.
        planner: Override PlannerProtocol implementation.
        policy: Override PolicyProtocol implementation.
        identity_runtime: Optional identity bundle (RFC-307).

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
        identity_runtime=identity_runtime,
    )
