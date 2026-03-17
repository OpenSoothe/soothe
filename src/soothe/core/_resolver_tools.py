"""Tool, goal, and subagent resolution for create_soothe_agent.

Extracted from ``resolver.py`` to isolate tool/subagent wiring from
protocol and infrastructure resolution.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from soothe.config import SOOTHE_HOME, BrowserSubagentConfig, SootheConfig
from soothe.subagents.browser import create_browser_subagent
from soothe.subagents.claude import create_claude_subagent
from soothe.subagents.planner import create_planner_subagent
from soothe.subagents.research import create_research_subagent
from soothe.subagents.scout import create_scout_subagent
from soothe.subagents.skillify import create_skillify_subagent
from soothe.subagents.weaver import create_weaver_subagent

if TYPE_CHECKING:
    from collections.abc import Callable

    from deepagents.middleware.subagents import CompiledSubAgent, SubAgent
    from langchain_core.language_models import BaseChatModel
    from langchain_core.tools import BaseTool

    from soothe.core.goal_engine import GoalEngine

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


# ---------------------------------------------------------------------------
# Tool resolution
# ---------------------------------------------------------------------------


def resolve_tools(tool_names: list[str], *, lazy: bool = False, config: SootheConfig | None = None) -> list[BaseTool]:
    """Resolve tool group names to instantiated langchain BaseTool lists.

    Args:
        tool_names: Enabled tool group names from config.
        lazy: If True, defer tool loading until first use (improves startup time).
        config: Optional Soothe config for tool configuration.

    Returns:
        Flat list of `BaseTool` instances (or lazy proxies).
    """
    import time

    from soothe.core.lazy_tools import LazyToolProxy

    tools: list[BaseTool] = []
    total_start = time.perf_counter()

    for name in tool_names:
        tool_start = time.perf_counter()
        try:
            if lazy:
                proxy = LazyToolProxy(
                    tool_name=name,
                    loader=lambda n=name, c=config: _resolve_single_tool_group_uncached(n, c),
                    index=0,
                )
                tools.append(proxy)
                elapsed_ms = (time.perf_counter() - tool_start) * 1000
                logger.debug("Created lazy proxy for tool '%s' in %.1fms", name, elapsed_ms)
            else:
                resolved = _resolve_single_tool_group(name, config)
                tools.extend(resolved)
        except Exception:
            logger.warning("Failed to load tool group '%s'", name, exc_info=True)

    total_elapsed_ms = (time.perf_counter() - total_start) * 1000
    logger.info(
        "Loaded %d tool groups (%d tools) in %.1fms (lazy=%s)",
        len(tool_names),
        len(tools),
        total_elapsed_ms,
        lazy,
    )

    return tools


def _resolve_single_tool_group(name: str, config: SootheConfig | None = None) -> list[BaseTool]:
    """Resolve a single tool group name to a list of BaseTool instances with caching and profiling.

    This method checks the cache first, and if not found, delegates to the uncached version.
    """
    import time

    from soothe.core.lazy_tools import cache_tools, get_cached_tools

    cached = get_cached_tools(name)
    if cached is not None:
        logger.debug("Tool group '%s' loaded from cache (%d tools)", name, len(cached))
        return cached

    start = time.perf_counter()
    tools = _resolve_single_tool_group_uncached(name, config)
    elapsed_ms = (time.perf_counter() - start) * 1000

    if tools:
        cache_tools(name, tools)

    logger.debug("Tool group '%s' loaded in %.1fms (%d tools)", name, elapsed_ms, len(tools))
    return tools


def _resolve_single_tool_group_uncached(name: str, config: SootheConfig | None = None) -> list[BaseTool]:
    """Resolve a single tool group name to a list of BaseTool instances.

    Args:
        name: Tool group name.
        config: Optional Soothe config for tool configuration.
    """
    if name == "jina":
        from soothe.tools.jina import create_jina_tools

        return list(create_jina_tools())
    if name == "serper":
        from soothe.tools.serper import create_serper_tools

        return list(create_serper_tools())
    if name == "wizsearch":
        from soothe.tools.wizsearch import create_wizsearch_tools

        wizsearch_config = {}
        if config and hasattr(config, "tools_settings") and hasattr(config.tools_settings, "wizsearch"):
            wizsearch_config = {
                "default_engines": config.tools_settings.wizsearch.default_engines,
                "max_results_per_engine": config.tools_settings.wizsearch.max_results_per_engine,
                "timeout": config.tools_settings.wizsearch.timeout,
            }
        if config and hasattr(config, "debug"):
            wizsearch_config["debug"] = config.debug
        return list(create_wizsearch_tools(wizsearch_config))
    if name == "datetime":
        from soothe.tools.datetime import create_datetime_tools

        return list(create_datetime_tools())
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

    if name == "bash":
        from soothe.tools.bash import create_bash_tools

        return list(create_bash_tools())

    if name == "file_edit":
        from soothe.tools.file_edit import create_file_edit_tools

        return list(create_file_edit_tools())

    if name == "document":
        from soothe.tools.document import create_document_tools

        return list(create_document_tools())

    if name == "python_executor":
        from soothe.tools.python_executor import create_python_executor_tools

        return list(create_python_executor_tools())

    if name == "arxiv":
        try:
            from langchain_community.tools import ArxivQueryRun

            return [ArxivQueryRun()]
        except ImportError:
            logger.debug("arxiv tool not available (install with: pip install arxiv)")
            return []
    if name == "wikipedia":
        try:
            from langchain_community.tools import WikipediaQueryRun
            from langchain_community.utilities import WikipediaAPIWrapper

            return [WikipediaQueryRun(api_wrapper=WikipediaAPIWrapper())]
        except ImportError:
            logger.debug("wikipedia tool not available (install with: pip install wikipedia)")
            return []
    if name == "github":
        from langchain_community.utilities import GitHubAPIWrapper

        wrapper = GitHubAPIWrapper()
        return wrapper.get_tools()

    if name == "goals":
        return []

    logger.warning("Unknown tool group '%s', skipping.", name)
    return []


# ---------------------------------------------------------------------------
# Goal engine resolution
# ---------------------------------------------------------------------------


def resolve_goal_engine(config: SootheConfig) -> GoalEngine:
    """Create a GoalEngine instance from config.

    Args:
        config: Soothe configuration.

    Returns:
        A configured GoalEngine.
    """
    from soothe.core.goal_engine import GoalEngine

    return GoalEngine(max_retries=config.autonomous.max_retries)


def resolve_goal_tools(goal_engine: GoalEngine) -> list[BaseTool]:
    """Create goal management tools bound to a GoalEngine.

    Args:
        goal_engine: The engine to bind.

    Returns:
        List of goal management BaseTool instances.
    """
    from soothe.tools.goals import create_goal_tools

    return create_goal_tools(goal_engine)


# ---------------------------------------------------------------------------
# Subagent resolution
# ---------------------------------------------------------------------------


def resolve_subagents(
    config: SootheConfig,
    default_model: BaseChatModel | None = None,
    *,
    lazy: bool = False,
) -> list[SubAgent | CompiledSubAgent]:
    """Build subagent specs from config with optional lazy loading.

    Args:
        config: Soothe configuration.
        default_model: Pre-configured model instance to use as default.
        lazy: If True, defer subagent initialization until first use.

    Returns:
        List of subagent specs for deepagents.
    """
    import time

    from soothe.core.lazy_tools import LazySubagentSpec

    eager_subagents = {"planner"}

    cwd_subagents = {"planner", "scout", "claude"}
    string_model_subagents = {"claude"}
    resolved_cwd = str(Path(config.workspace_dir).resolve()) if config.workspace_dir else str(Path.cwd())

    subagents: list[SubAgent | CompiledSubAgent] = []
    total_start = time.perf_counter()

    for name, sub_cfg in config.subagents.items():
        if not sub_cfg.enabled:
            continue

        sub_start = time.perf_counter()
        factory = SUBAGENT_FACTORIES.get(name)
        if factory is None:
            logger.warning("Unknown subagent '%s', skipping.", name)
            continue

        if name in string_model_subagents:
            model_override = sub_cfg.model or config.resolve_model("default")
        else:
            model_override = sub_cfg.model or default_model or config.resolve_model("default")

        extra_kwargs = dict(sub_cfg.config)
        if name in cwd_subagents and "cwd" not in extra_kwargs:
            extra_kwargs["cwd"] = resolved_cwd
        if name in ("skillify", "weaver", "research"):
            extra_kwargs["config"] = config
        if name == "browser":
            extra_kwargs["config"] = BrowserSubagentConfig(**sub_cfg.config)

        if lazy and name not in eager_subagents:
            spec = LazySubagentSpec(
                name=name,
                factory=factory,
                kwargs={"model": model_override, **extra_kwargs},
            )
            elapsed_ms = (time.perf_counter() - sub_start) * 1000
            logger.debug("Created lazy spec for subagent '%s' in %.1fms", name, elapsed_ms)
        else:
            try:
                spec = factory(model=model_override, **extra_kwargs)
                elapsed_ms = (time.perf_counter() - sub_start) * 1000
                logger.info("Loaded subagent '%s' in %.1fms", name, elapsed_ms)
            except Exception:
                logger.exception("Failed to load subagent '%s'", name)
                continue

        subagents.append(spec)

    generated = _resolve_generated_subagents(config)
    if generated:
        logger.info("Loaded %d generated agent(s) from registry", len(generated))
        subagents.extend(generated)

    total_elapsed_ms = (time.perf_counter() - total_start) * 1000
    logger.info(
        "Loaded %d subagents in %.1fms (lazy=%s)",
        len(subagents),
        total_elapsed_ms,
        lazy,
    )

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
    except Exception:
        logger.debug("Failed to initialise generated agent registry", exc_info=True)
        return []

    subagents: list[SubAgent] = []
    for manifest in registry.list_agents():
        agent = registry.load_as_subagent(manifest.name)
        if agent:
            subagents.append(agent)
    return subagents
