"""Soothe agent factory -- wraps deepagents' `create_deep_agent`."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from deepagents import create_deep_agent
from langchain_core.language_models import BaseChatModel

from soothe.built_in_skills import get_built_in_skills_paths
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
from soothe.middleware.policy import SoothePolicyMiddleware
from soothe.middleware.subagent_context import SubagentContextMiddleware

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

    # Use lazy loading by default for better startup performance
    tools_start = time.perf_counter()
    config_tools = resolve_tools(config.tools, lazy=False)
    goal_tools = resolve_goal_tools(goal_engine)
    all_tools: list[BaseTool | Callable | dict[str, Any]] = [*config_tools, *goal_tools]
    if tools:
        all_tools.extend(tools)
    tools_ms = (time.perf_counter() - tools_start) * 1000
    logger.info("Tools resolved in %.1fms", tools_ms)

    subagents_start = time.perf_counter()
    config_subagents = resolve_subagents(config, default_model=default_model_instance, lazy=False)
    all_subagents: list[SubAgent | CompiledSubAgent] = [*config_subagents]
    if subagents:
        all_subagents.extend(subagents)
    subagents_ms = (time.perf_counter() - subagents_start) * 1000
    logger.info("Subagents resolved in %.1fms", subagents_ms)

    resolved_workspace = str(Path(config.workspace_dir).resolve()) if config.workspace_dir else str(Path.cwd())

    resolved_backend = backend
    if resolved_backend is None:
        from deepagents.backends.filesystem import FilesystemBackend

        resolved_backend = FilesystemBackend(
            root_dir=resolved_workspace,
            virtual_mode=True,
        )

    default_middleware: list[AgentMiddleware] = []
    if resolved_policy:
        default_middleware.append(
            SoothePolicyMiddleware(
                policy=resolved_policy,
                profile_name=config.policy_profile,
            )
        )
    if resolved_context:
        default_middleware.append(SubagentContextMiddleware(context=resolved_context))

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
