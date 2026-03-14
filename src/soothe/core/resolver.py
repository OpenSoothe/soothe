"""Protocol, subagent, and tool resolution logic for create_soothe_agent."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from deepagents.middleware.subagents import CompiledSubAgent, SubAgent
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from soothe.config import SOOTHE_HOME, SootheConfig
from soothe.protocols.context import ContextProtocol
from soothe.protocols.memory import MemoryProtocol
from soothe.protocols.planner import PlannerProtocol
from soothe.protocols.policy import PolicyProtocol
from soothe.subagents.browser import create_browser_subagent
from soothe.subagents.claude import create_claude_subagent
from soothe.subagents.planner import create_planner_subagent
from soothe.subagents.research import create_research_subagent
from soothe.subagents.scout import create_scout_subagent
from soothe.subagents.skillify import create_skillify_subagent
from soothe.subagents.weaver import create_weaver_subagent

logger = logging.getLogger(__name__)

SUBAGENT_FACTORIES: dict[str, Callable[..., SubAgent | CompiledSubAgent]] = {
    "planner": create_planner_subagent,
    "scout": create_scout_subagent,
    "research": create_research_subagent,
    "browser": create_browser_subagent,
    "claude": create_claude_subagent,
    "skillify": create_skillify_subagent,
    "weaver": create_weaver_subagent,
}


def resolve_tools(tool_names: list[str]) -> list[BaseTool]:
    """Resolve tool group names to instantiated langchain BaseTool lists.

    Args:
        tool_names: Enabled tool group names from config.

    Returns:
        Flat list of `BaseTool` instances.
    """
    tools: list[BaseTool] = []
    for name in tool_names:
        try:
            resolved = _resolve_single_tool_group(name)
            tools.extend(resolved)
        except Exception:  # noqa: BLE001
            logger.warning("Failed to load tool group '%s'", name, exc_info=True)
    return tools


def _resolve_single_tool_group(name: str) -> list[BaseTool]:
    """Resolve a single tool group name to a list of BaseTool instances."""
    if name == "jina":
        from soothe.tools.jina import create_jina_tools

        return list(create_jina_tools())
    if name == "serper":
        from soothe.tools.serper import create_serper_tools

        return list(create_serper_tools())
    if name == "image":
        from soothe.tools.image import create_image_tools

        return list(create_image_tools())
    if name == "audio":
        from soothe.tools.audio import create_audio_tools

        return list(create_audio_tools())
    if name == "video":
        from soothe.tools.video import create_video_tools

        return list(create_video_tools())
    if name == "tabular":
        from soothe.tools.tabular import create_tabular_tools

        return list(create_tabular_tools())

    if name == "tavily":
        from langchain_tavily import TavilySearchResults

        return [TavilySearchResults()]
    if name == "duckduckgo":
        from langchain_community.tools import DuckDuckGoSearchRun

        return [DuckDuckGoSearchRun()]
    if name == "arxiv":
        from langchain_community.tools import ArxivQueryRun

        return [ArxivQueryRun()]
    if name == "wikipedia":
        from langchain_community.tools import WikipediaQueryRun
        from langchain_community.utilities import WikipediaAPIWrapper

        return [WikipediaQueryRun(api_wrapper=WikipediaAPIWrapper())]
    if name == "github":
        from langchain_community.utilities import GitHubAPIWrapper

        wrapper = GitHubAPIWrapper()
        return wrapper.get_tools()
    if name == "python_repl":
        from langchain_community.tools import PythonREPLTool

        return [PythonREPLTool()]

    logger.warning("Unknown tool group '%s', skipping.", name)
    return []


def resolve_subagents(
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
        factory = SUBAGENT_FACTORIES.get(name)
        if factory is None:
            logger.warning("Unknown subagent '%s', skipping.", name)
            continue
        model_override = sub_cfg.model or default_model or config.resolve_model("default")
        extra_kwargs = dict(sub_cfg.config)
        if name in ("skillify", "weaver"):
            extra_kwargs["config"] = config
        spec = factory(model=model_override, **extra_kwargs)
        subagents.append(spec)

    generated = _resolve_generated_subagents(config)
    if generated:
        logger.info("Loaded %d generated agent(s) from registry", len(generated))
        subagents.extend(generated)

    return subagents


def _resolve_generated_subagents(config: SootheConfig) -> list[SubAgent]:
    """Load generated agents from Weaver's registry at startup."""
    from pathlib import Path

    generated_dir = config.weaver.generated_agents_dir or str(Path(SOOTHE_HOME) / "generated_agents")
    base = Path(generated_dir).expanduser().resolve()
    if not base.is_dir():
        return []

    try:
        from soothe.subagents.weaver.registry import GeneratedAgentRegistry

        registry = GeneratedAgentRegistry(base_dir=base)
    except Exception:  # noqa: BLE001
        logger.debug("Failed to initialise generated agent registry", exc_info=True)
        return []

    subagents: list[SubAgent] = []
    for manifest in registry.list_agents():
        agent = registry.load_as_subagent(manifest.name)
        if agent:
            subagents.append(agent)
    return subagents


def resolve_context(config: SootheConfig) -> ContextProtocol | None:
    """Instantiate the ContextProtocol implementation from config.

    Args:
        config: Soothe configuration.

    Returns:
        A ContextProtocol instance, or None if disabled.
    """
    if config.context_backend == "none":
        return None

    if config.context_backend == "vector":
        from soothe.backends.context.vector import VectorContext
        from soothe.backends.vector_store import create_vector_store

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

    from pathlib import Path

    from soothe.backends.context.keyword import KeywordContext

    persist_dir = config.context_persist_dir or str(Path(SOOTHE_HOME) / "context")
    return KeywordContext(
        persist_dir=persist_dir,
        persist_backend=config.context_persist_backend,
    )


def resolve_memory(config: SootheConfig) -> MemoryProtocol | None:
    """Instantiate the MemoryProtocol implementation from config.

    Args:
        config: Soothe configuration.

    Returns:
        A MemoryProtocol instance, or None if disabled.
    """
    if config.memory_backend == "none":
        return None

    if config.memory_backend == "vector":
        from soothe.backends.memory.vector import VectorMemory
        from soothe.backends.vector_store import create_vector_store

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

    from pathlib import Path

    from soothe.backends.memory.store import StoreBackedMemory

    persist_path = config.memory_persist_path or str(Path(SOOTHE_HOME) / "memory")
    return StoreBackedMemory(
        persist_path=persist_path,
        persist_backend=config.memory_persist_backend,
    )


def resolve_planner(
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
        from soothe.backends.planning.direct import DirectPlanner

        return DirectPlanner(model=planner_model)

    logger.warning("Planner routing '%s' not yet implemented, using direct", config.planner_routing)
    from soothe.backends.planning.direct import DirectPlanner

    return DirectPlanner(model=planner_model)


def resolve_policy(config: SootheConfig) -> PolicyProtocol | None:
    """Instantiate the PolicyProtocol implementation from config.

    Args:
        config: Soothe configuration.

    Returns:
        A PolicyProtocol instance.
    """
    from soothe.backends.policy.config_driven import ConfigDrivenPolicy

    return ConfigDrivenPolicy()
