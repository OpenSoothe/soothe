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
        model_override = sub_cfg.model or default_model or config.resolve_model_string()
        spec = factory(model=model_override, **sub_cfg.config)
        subagents.append(spec)
    return subagents


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
) -> CompiledStateGraph:
    """Create a Soothe agent.

    Thin wrapper around `create_deep_agent()` that wires up Soothe-specific
    subagents, tools, MCP servers, and skills from `SootheConfig`.

    Args:
        config: Soothe configuration. If `None`, uses defaults.
        model: Override the model from config. Passed to `create_deep_agent`.
        tools: Additional tools beyond what config specifies.
        subagents: Additional subagents beyond what config specifies.
        middleware: Additional middleware appended after the standard stack.
        checkpointer: LangGraph checkpointer for persistence.
        store: LangGraph store for persistent storage.
        backend: deepagents backend for file/execution operations.
        interrupt_on: Tool interrupt configuration for human-in-the-loop.

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
        resolved_model = config.create_chat_model()

    config_tools = _resolve_tools(config.tools)
    all_tools: list[BaseTool | Callable | dict[str, Any]] = [*config_tools]
    if tools:
        all_tools.extend(tools)

    default_model_instance = resolved_model if isinstance(resolved_model, BaseChatModel) else None
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

    return create_deep_agent(
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
