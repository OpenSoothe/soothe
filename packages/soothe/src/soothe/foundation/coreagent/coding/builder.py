"""Coding CoreAgent construction logic."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from soothe.config import SootheConfig
from soothe.foundation.coreagent.coding.core_agent import CodingCoreAgent
from soothe.middleware import build_soothe_middleware_stack
from soothe.protocols.core_agent import CoreAgentCapabilities
from soothe.runner.resolver import (
    resolve_memory,
    resolve_planner,
    resolve_policy,
    resolve_subagents,
    resolve_tools,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from langchain.agents.middleware import InterruptOnConfig
    from langchain.agents.middleware.types import AgentMiddleware
    from langchain_core.tools import BaseTool
    from langgraph.store.base import BaseStore
    from langgraph.types import Checkpointer
    from soothe_deepagents.backends.protocol import BackendFactory, BackendProtocol
    from soothe_deepagents.middleware.filesystem import FsToolName
    from soothe_deepagents.middleware.subagents import CompiledSubAgent, SubAgent

    from soothe.middleware.identity import IdentityRuntime
    from soothe.protocols.memory import MemoryProtocol
    from soothe.protocols.planner import PlannerProtocol
    from soothe.protocols.policy import PolicyProtocol

from langchain_core.language_models import BaseChatModel  # noqa: E402

_FILESYSTEM_TOOLS_NO_EXECUTE: list[FsToolName] = [
    "ls",
    "read_file",
    "write_file",
    "edit_file",
    "delete",
    "glob",
    "grep",
]
_PARENT_OWNED_STATE_KEYS = frozenset({"workspace"})

logger = logging.getLogger(__name__)


class AgentBuilder:
    """Builder for CodingCoreAgent instances."""

    def __init__(
        self,
        config: SootheConfig | None = None,
        mcp_registry: Any | None = None,
    ) -> None:
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
        core_agent_kind: str | None = None,
    ) -> CodingCoreAgent:
        from soothe_deepagents import create_deep_agent

        create_start = time.perf_counter()
        selected_kind = (core_agent_kind or self._resolve_core_agent_kind()).strip().lower()
        if selected_kind != "coding":
            msg = (
                f"Unsupported core agent kind: {selected_kind!r}. "
                "Only 'coding' is currently implemented."
            )
            raise ValueError(msg)

        resolved_model: str | BaseChatModel
        resolved_model = model if model is not None else self._config.create_chat_model("default")
        default_model_instance = (
            resolved_model if isinstance(resolved_model, BaseChatModel) else None
        )

        resolve_start = time.perf_counter()
        resolved_memory = memory_store or self._resolve_memory()
        resolved_planner = planner or self._resolve_planner(default_model_instance)
        resolved_policy = policy or self._resolve_policy()
        resolve_ms = (time.perf_counter() - resolve_start) * 1000
        logger.debug("[Init] Protocols resolved (%.1fms)", resolve_ms)

        self._load_plugins()

        tools_start = time.perf_counter()
        config_tools = resolve_tools(
            self._config.tools,
            lazy=True,
            config=self._config,
        )
        all_tools: list[BaseTool | Callable | dict[str, Any]] = list(config_tools)
        if tools:
            all_tools.extend(tools)

        registry = mcp_registry or self._mcp_registry
        if registry is not None:
            mcp_tools = registry.all_tools()
            if mcp_tools:
                all_tools.extend(mcp_tools)

            if registry.deferred_tools():
                from soothe.mcp.discovery_tools import create_search_mcp_tools_tool

                all_tools.append(create_search_mcp_tools_tool())

            from soothe.mcp.tools import create_mcp_resource_tools

            all_tools.extend(create_mcp_resource_tools(registry))

        if (
            self._config.progressive_tools.enabled
            and self._config.progressive_tools.search_tools_enabled
        ):
            from soothe.toolkits.progressive.search_tool import create_search_tools_tool

            all_tools.append(create_search_tools_tool())

        if self._config.progressive_skills.search_skills_enabled:
            from soothe.skills.discovery_tools import (
                create_invoke_skill_tool,
                create_search_skills_tool,
            )

            all_tools.append(create_search_skills_tool())
            all_tools.append(create_invoke_skill_tool())

        tools_ms = (time.perf_counter() - tools_start) * 1000
        logger.info("[Init] Tools resolved: %d tools (%.1fms)", len(all_tools), tools_ms)

        subagents_start = time.perf_counter()
        config_subagents = resolve_subagents(
            self._config,
            default_model=default_model_instance,
            lazy=True,
        )
        all_subagents: list[SubAgent | CompiledSubAgent] = list(config_subagents)
        if subagents:
            all_subagents.extend(subagents)
        subagents_ms = (time.perf_counter() - subagents_start) * 1000
        logger.info(
            "[Init] Subagents resolved: %d agents (%.1fms)", len(all_subagents), subagents_ms
        )

        resolved_backend = backend or self._initialize_backend(resolved_policy)

        default_middleware = build_soothe_middleware_stack(
            self._config,
            resolved_policy,
            mcp_registry=registry,
            identity_runtime=identity_runtime,
        )
        if all_tools:
            from soothe.middleware.mcp_activation import MCPActivationMiddleware
            from soothe.middleware.progressive_tools import ProgressiveToolMiddleware

            for mw in default_middleware:
                if isinstance(mw, ProgressiveToolMiddleware):
                    mw.set_tool_catalog(all_tools)
                elif isinstance(mw, MCPActivationMiddleware) and registry is not None:
                    mw.set_tool_catalog()
        all_middleware: tuple[AgentMiddleware, ...] = (*default_middleware, *middleware)

        from soothe.middleware.model_call_profiler import (
            install_model_call_profiler,
            is_profiler_enabled,
        )

        install_model_call_profiler(enabled=is_profiler_enabled(self._config))

        def _compile_deep_agent(cp: Checkpointer | None) -> Any:
            gp_enabled = self._config.agent.runtime.general_purpose_subagent
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
                enable_general_purpose_subagent=gp_enabled,
                filesystem_tools=_FILESYSTEM_TOOLS_NO_EXECUTE,
                parent_owned_state_keys=_PARENT_OWNED_STATE_KEYS,
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

        capabilities = CoreAgentCapabilities(
            tools=tuple(self._collect_tool_names(all_tools)),
            subagents=tuple(self._collect_subagent_names(all_subagents)),
            features=(
                "langgraph",
                "checkpointer",
                "execution_graph",
                "interrupt_resume",
                "streaming",
            ),
            metadata={
                "runtime_kind": "coding",
                "tool_count": len(all_tools),
                "subagent_count": len(all_subagents),
            },
        )

        agent = CodingCoreAgent(
            graph=graph,
            config=self._config,
            memory=resolved_memory,
            planner=resolved_planner,
            policy=resolved_policy,
            subagents=all_subagents,
            capabilities=capabilities,
            execute_graph=execute_graph,
            execute_graph_compiler=execute_graph_compiler,
        )

        total_ms = (time.perf_counter() - create_start) * 1000
        logger.info("[Init] CoreAgent ready (%.1fms total)", total_ms)
        return agent

    def _resolve_core_agent_kind(self) -> str:
        runtime_cfg = getattr(getattr(self._config, "agent", None), "runtime", None)
        raw = getattr(runtime_cfg, "core_agent_kind", None) if runtime_cfg else None
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
        return "coding"

    @staticmethod
    def _collect_tool_names(tools: Sequence[BaseTool | Callable | dict[str, Any]]) -> list[str]:
        names: list[str] = []
        for tool in tools:
            if isinstance(tool, dict):
                candidate = tool.get("name")
                if isinstance(candidate, str) and candidate:
                    names.append(candidate)
                continue
            name = getattr(tool, "name", None)
            if isinstance(name, str) and name:
                names.append(name)
                continue
            if callable(tool):
                names.append(getattr(tool, "__name__", "callable_tool"))
        return sorted(set(names))

    @staticmethod
    def _collect_subagent_names(subagents: Sequence[SubAgent | CompiledSubAgent]) -> list[str]:
        names: list[str] = []
        for subagent in subagents:
            name = getattr(subagent, "name", None)
            if isinstance(name, str) and name:
                names.append(name)
        return sorted(set(names))

    def _resolve_memory(self) -> MemoryProtocol | None:
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
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        from soothe.plugin.global_registry import load_plugins

        plugins_start = time.perf_counter()
        try:
            coro = load_plugins(self._config)
            try:
                asyncio.get_running_loop()

                def _run_async_on_fresh_loop() -> None:
                    asyncio.run(coro)

                with ThreadPoolExecutor(max_workers=1) as pool:
                    pool.submit(_run_async_on_fresh_loop).result()
            except RuntimeError:
                asyncio.run(coro)
        except RuntimeError:
            logger.debug("[Init] Plugin loading failed, will load on demand")
        plugins_ms = (time.perf_counter() - plugins_start) * 1000
        logger.info("[Init] Plugins loaded (%.1fms)", plugins_ms)

    def _initialize_backend(
        self,
        policy: PolicyProtocol | None,
    ) -> BackendProtocol | BackendFactory:
        from soothe.foundation.workspace import FrameworkFilesystem

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
    identity_runtime: IdentityRuntime | None = None,
    core_agent_kind: str | None = None,
) -> CodingCoreAgent:
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
        core_agent_kind=core_agent_kind,
    )
