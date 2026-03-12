"""Soothe agent factory -- wraps deepagents' `create_deep_agent`."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends.protocol import BackendFactory, BackendProtocol
from deepagents.middleware.subagents import CompiledSubAgent, SubAgent
from langchain.agents.middleware import InterruptOnConfig
from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.graph.state import CompiledStateGraph
from langgraph.store.base import BaseStore
from langgraph.types import Checkpointer

from soothe.config import SootheConfig
from soothe.protocols.context import ContextProtocol
from soothe.protocols.memory import MemoryProtocol
from soothe.protocols.planner import PlannerProtocol
from soothe.protocols.policy import PolicyProtocol
from soothe.subagents.browser import create_browser_subagent
from soothe.subagents.claude import create_claude_subagent
from soothe.subagents.planner import create_planner_subagent
from soothe.subagents.research import create_research_subagent
from soothe.subagents.scout import create_scout_subagent

logger = logging.getLogger(__name__)

_SUBAGENT_FACTORIES: dict[str, Callable[..., SubAgent | CompiledSubAgent]] = {
    "planner": create_planner_subagent,
    "scout": create_scout_subagent,
    "research": create_research_subagent,
    "browser": create_browser_subagent,
    "claude": create_claude_subagent,
}


def _resolve_tools(tool_names: list[str]) -> list[BaseTool]:
    """Resolve tool group names to instantiated langchain BaseTool lists.

    Args:
        tool_names: Enabled tool group names from config.

    Returns:
        Flat list of `BaseTool` instances.
    """
    tools: list[BaseTool] = []
    for name in tool_names:
        if name == "jina":
            from soothe.tools.jina import create_jina_tools

            tools.extend(create_jina_tools())
        elif name == "serper":
            from soothe.tools.serper import create_serper_tools

            tools.extend(create_serper_tools())
        elif name == "image":
            from soothe.tools.image import create_image_tools

            tools.extend(create_image_tools())
        elif name == "audio":
            from soothe.tools.audio import create_audio_tools

            tools.extend(create_audio_tools())
        elif name == "video":
            from soothe.tools.video import create_video_tools

            tools.extend(create_video_tools())
        elif name == "tabular":
            from soothe.tools.tabular import create_tabular_tools

            tools.extend(create_tabular_tools())
        else:
            logger.warning("Unknown tool group '%s', skipping.", name)
    return tools


def _resolve_subagents(
    config: SootheConfig,
    default_model: BaseChatModel | None = None,
) -> list[SubAgent | CompiledSubAgent]:
    """Build subagent specs from config.

    Args:
        config: Soothe configuration.
        default_model: Pre-configured model instance to use as default.

    Returns:
        List of subagent specs for deepagents.
    """
    subagents: list[SubAgent | CompiledSubAgent] = []
    for name, sub_cfg in config.subagents.items():
        if not sub_cfg.enabled:
            continue
        factory = _SUBAGENT_FACTORIES.get(name)
        if factory is None:
            logger.warning("Unknown subagent '%s', skipping.", name)
            continue
        model_override = sub_cfg.model or default_model or config.resolve_model("default")
        spec = factory(model=model_override, **sub_cfg.config)
        subagents.append(spec)
    return subagents


def _resolve_context(config: SootheConfig) -> ContextProtocol | None:
    """Instantiate the ContextProtocol implementation from config.

    Args:
        config: Soothe configuration.

    Returns:
        A ContextProtocol instance, or None if disabled.
    """
    if config.context_backend == "none":
        return None

    if config.context_backend == "vector":
        from soothe.context.vector_context import VectorContext
        from soothe.vector_store import create_vector_store

        if config.vector_store_provider == "none":
            logger.warning("vector context requires vector_store_provider; falling back to keyword")
        else:
            vs = create_vector_store(
                config.vector_store_provider,
                f"{config.vector_store_collection}_context",
                config.vector_store_config,
            )
            embeddings = config.create_embedding_model()
            return VectorContext(vector_store=vs, embeddings=embeddings)

    from soothe.context.keyword import KeywordContext

    return KeywordContext(
        persist_dir=config.context_persist_dir,
        persist_backend=config.context_persist_backend,
    )


def _resolve_memory(config: SootheConfig) -> MemoryProtocol | None:
    """Instantiate the MemoryProtocol implementation from config.

    Args:
        config: Soothe configuration.

    Returns:
        A MemoryProtocol instance, or None if disabled.
    """
    if config.memory_backend == "none":
        return None

    if config.memory_backend == "vector":
        from soothe.memory_store.vector_memory import VectorMemory
        from soothe.vector_store import create_vector_store

        if config.vector_store_provider == "none":
            logger.warning("vector memory requires vector_store_provider; falling back to store")
        else:
            vs = create_vector_store(
                config.vector_store_provider,
                f"{config.vector_store_collection}_memory",
                config.vector_store_config,
            )
            embeddings = config.create_embedding_model()
            return VectorMemory(vector_store=vs, embeddings=embeddings)

    from soothe.memory_store.store_backed import StoreBackedMemory

    return StoreBackedMemory(
        persist_path=config.memory_persist_path,
        persist_backend=config.memory_persist_backend,
    )


def _resolve_planner(
    config: SootheConfig,
    model: BaseChatModel | None,
) -> PlannerProtocol | None:
    """Instantiate the PlannerProtocol implementation from config.

    Args:
        config: Soothe configuration.
        model: The resolved chat model.

    Returns:
        A PlannerProtocol instance, or None if disabled.
    """
    if config.planner_routing == "none":
        return None

    planner_model = model
    if planner_model is None:
        try:
            planner_model = config.create_chat_model("think")
        except Exception:  # noqa: BLE001
            logger.warning("Failed to create think model for planner")
            return None

    if config.planner_routing in ("always_direct", "auto"):
        from soothe.planning.direct import DirectPlanner

        return DirectPlanner(model=planner_model)

    logger.warning("Planner routing '%s' not yet implemented, using direct", config.planner_routing)
    from soothe.planning.direct import DirectPlanner

    return DirectPlanner(model=planner_model)


def _resolve_policy(config: SootheConfig) -> PolicyProtocol | None:
    """Instantiate the PolicyProtocol implementation from config.

    Args:
        config: Soothe configuration.

    Returns:
        A PolicyProtocol instance.
    """
    from soothe.policy.config_driven import ConfigDrivenPolicy

    return ConfigDrivenPolicy()


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
    """Create a Soothe agent.

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
    if config is None:
        config = SootheConfig()

    config.propagate_env()

    resolved_model: str | BaseChatModel
    if model is not None:
        resolved_model = model
    else:
        resolved_model = config.create_chat_model("default")

    default_model_instance = resolved_model if isinstance(resolved_model, BaseChatModel) else None
    resolved_context = context or _resolve_context(config)
    resolved_memory = memory_store or _resolve_memory(config)
    resolved_planner = planner or _resolve_planner(config, default_model_instance)
    resolved_policy = policy or _resolve_policy(config)

    if resolved_context:
        logger.info("Context: %s", type(resolved_context).__name__)
    if resolved_memory:
        logger.info("Memory: %s", type(resolved_memory).__name__)
    if resolved_planner:
        logger.info("Planner: %s", type(resolved_planner).__name__)
    if resolved_policy:
        logger.info("Policy: %s", type(resolved_policy).__name__)

    config_tools = _resolve_tools(config.tools)
    all_tools: list[BaseTool | Callable | dict[str, Any]] = [*config_tools]
    if tools:
        all_tools.extend(tools)

    config_subagents = _resolve_subagents(config, default_model=default_model_instance)
    all_subagents: list[SubAgent | CompiledSubAgent] = [*config_subagents]
    if subagents:
        all_subagents.extend(subagents)

    resolved_backend = backend
    if resolved_backend is None and config.workspace_dir:
        from deepagents.backends.filesystem import FilesystemBackend

        resolved_backend = FilesystemBackend(
            root_dir=config.workspace_dir,
            virtual_mode=True,
        )

    agent = create_deep_agent(
        model=resolved_model,
        tools=all_tools or None,
        system_prompt=config.system_prompt,
        middleware=middleware,
        subagents=all_subagents or None,
        skills=config.skills or None,
        memory=config.memory or None,
        checkpointer=checkpointer,
        store=store,
        backend=resolved_backend,
        interrupt_on=interrupt_on,
        debug=config.debug,
    )

    agent.soothe_context = resolved_context  # type: ignore[attr-defined]
    agent.soothe_memory = resolved_memory  # type: ignore[attr-defined]
    agent.soothe_planner = resolved_planner  # type: ignore[attr-defined]
    agent.soothe_policy = resolved_policy  # type: ignore[attr-defined]
    agent.soothe_config = config  # type: ignore[attr-defined]

    return agent
