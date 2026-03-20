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
from soothe.subagents.skillify import create_skillify_subagent
from soothe.subagents.weaver import create_weaver_subagent
from soothe.utils import expand_path
from soothe.utils.tool_logging import wrap_main_agent_tool_with_logging

if TYPE_CHECKING:
    from collections.abc import Callable

    from deepagents.middleware.subagents import CompiledSubAgent, SubAgent
    from langchain_core.language_models import BaseChatModel
    from langchain_core.tools import BaseTool

    from soothe.core.goal_engine import GoalEngine

logger = logging.getLogger(__name__)

SUBAGENT_FACTORIES: dict[str, Callable[..., SubAgent | CompiledSubAgent]] = {
    "browser": create_browser_subagent,
    "claude": create_claude_subagent,
    "skillify": create_skillify_subagent,
    "weaver": create_weaver_subagent,
}


# ---------------------------------------------------------------------------
# Tool resolution
# ---------------------------------------------------------------------------


def resolve_tools(
    tool_names: list[str],
    *,
    lazy: bool = False,
    config: SootheConfig | None = None,
) -> list[BaseTool]:
    """Resolve tool group names to instantiated langchain BaseTool lists.

    Args:
        tool_names: Enabled tool group names from config.
        lazy: If True, load tool groups in parallel using a thread pool
            for faster startup.  Historically this created lazy proxies,
            but those are incompatible with langgraph ToolNode's eager
            metadata probing.
        config: Optional Soothe config for tool configuration.

    Returns:
        Flat list of fully-initialised `BaseTool` instances.
    """
    import time

    total_start = time.perf_counter()

    parallel = lazy and len(tool_names) > 1
    tools = _resolve_tools_parallel(tool_names, config) if parallel else _resolve_tools_sequential(tool_names, config)

    total_elapsed_ms = (time.perf_counter() - total_start) * 1000
    logger.info(
        "Resolved %d tool groups (%d tools) in %.1fms (parallel=%s)",
        len(tool_names),
        len(tools),
        total_elapsed_ms,
        parallel,
    )

    return tools


def _resolve_tools_sequential(
    tool_names: list[str],
    config: SootheConfig | None = None,
) -> list[BaseTool]:
    """Load tool groups one-by-one, skipping failures."""
    tools: list[BaseTool] = []
    for name in tool_names:
        try:
            resolved = _resolve_single_tool_group(name, config)
            wrapped = [wrap_main_agent_tool_with_logging(tool, logger, tool_group=name) for tool in resolved]
            tools.extend(wrapped)
        except Exception:
            logger.warning("Failed to load tool group '%s'", name, exc_info=True)
    return tools


def _resolve_tools_parallel(
    tool_names: list[str],
    config: SootheConfig | None = None,
) -> list[BaseTool]:
    """Load tool groups concurrently via ThreadPoolExecutor.

    Overlaps I/O-bound module imports and network initialisation across
    tool groups while preserving the original ordering in the result.
    Failed groups are logged and skipped.
    """
    from concurrent.futures import ThreadPoolExecutor

    max_workers = min(len(tool_names), 4)
    results: dict[str, list[BaseTool]] = {}

    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="tool-load") as pool:
        futures = {name: pool.submit(_resolve_single_tool_group, name, config) for name in tool_names}
        for name in tool_names:
            try:
                results[name] = futures[name].result()
            except Exception:
                logger.warning("Failed to load tool group '%s'", name, exc_info=True)

    tools: list[BaseTool] = []
    for name in tool_names:
        tools.extend(wrap_main_agent_tool_with_logging(t, logger, tool_group=name) for t in results.get(name, []))
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
    if name == "github":
        try:
            from langchain_community.utilities import GitHubAPIWrapper

            wrapper = GitHubAPIWrapper()
            return wrapper.get_tools()
        except Exception:
            logger.debug("github tool not available (pip install pygithub)", exc_info=True)
            return []

    if name == "research":
        from soothe.tools.research import create_research_tools

        resolved_cwd = str(expand_path(config.workspace_dir)) if config and config.workspace_dir else str(Path.cwd())
        return list(create_research_tools(config=config, work_dir=resolved_cwd))

    if name == "websearch":
        from soothe.tools.websearch import create_websearch_tools

        wizsearch_config: dict = {}
        if config and hasattr(config, "tools_settings") and hasattr(config.tools_settings, "wizsearch"):
            wizsearch_config = {
                "default_engines": config.tools_settings.wizsearch.default_engines,
                "max_results_per_engine": config.tools_settings.wizsearch.max_results_per_engine,
                "timeout": config.tools_settings.wizsearch.timeout,
            }
        if config and hasattr(config, "debug"):
            wizsearch_config["debug"] = config.debug
        return list(create_websearch_tools(wizsearch_config))

    if name == "workspace":
        from soothe.tools.workspace import create_workspace_tools

        resolved_cwd = str(expand_path(config.workspace_dir)) if config and config.workspace_dir else str(Path.cwd())
        allow_outside = (
            config.security.allow_paths_outside_workspace if config and hasattr(config, "security") else False
        )
        return list(create_workspace_tools(work_dir=resolved_cwd, allow_outside_workdir=allow_outside))

    if name == "execute":
        from soothe.tools.execute import create_execute_tools

        resolved_cwd = str(expand_path(config.workspace_dir)) if config and config.workspace_dir else str(Path.cwd())
        return list(create_execute_tools(workspace_root=resolved_cwd))

    if name == "data":
        from soothe.tools.data import create_data_tools

        return list(create_data_tools())

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
    """Build subagent specs from config.

    Args:
        config: Soothe configuration.
        default_model: Pre-configured model instance to use as default.
        lazy: If True, create subagent specs in parallel using a thread
            pool for faster startup.

    Returns:
        List of subagent specs for deepagents.
    """
    import time

    total_start = time.perf_counter()

    # Collect (name, factory, kwargs) tuples for enabled subagents
    pending: list[tuple[str, Callable, dict]] = []
    cwd_subagents = {"claude"}
    resolved_cwd = str(expand_path(config.workspace_dir)) if config.workspace_dir else str(Path.cwd())

    for name, sub_cfg in config.subagents.items():
        if not sub_cfg.enabled:
            continue
        factory = SUBAGENT_FACTORIES.get(name)
        if factory is None:
            logger.warning("Unknown subagent '%s', skipping.", name)
            continue

        model_override = None if name == "claude" else sub_cfg.model or default_model or config.resolve_model("default")

        extra_kwargs: dict = dict(sub_cfg.config)
        if name in cwd_subagents and "cwd" not in extra_kwargs:
            extra_kwargs["cwd"] = resolved_cwd
        if name in ("skillify", "weaver"):
            extra_kwargs["config"] = config
        if name == "browser":
            extra_kwargs["config"] = BrowserSubagentConfig(**sub_cfg.config)

        pending.append((name, factory, {"model": model_override, **extra_kwargs}))

    parallel = lazy and len(pending) > 1
    subagents = _resolve_subagents_parallel(pending) if parallel else _resolve_subagents_sequential(pending)

    generated = _resolve_generated_subagents(config)
    if generated:
        logger.info("Loaded %d generated agent(s) from registry", len(generated))
        subagents.extend(generated)

    total_elapsed_ms = (time.perf_counter() - total_start) * 1000
    logger.info(
        "Resolved %d subagents in %.1fms (parallel=%s)",
        len(subagents),
        total_elapsed_ms,
        parallel,
    )

    return subagents


def _resolve_subagents_sequential(
    pending: list[tuple[str, Callable, dict]],
) -> list[SubAgent | CompiledSubAgent]:
    """Build subagent specs one-by-one, skipping failures."""
    import time

    subagents: list[SubAgent | CompiledSubAgent] = []
    for name, factory, kwargs in pending:
        start = time.perf_counter()
        try:
            spec = factory(**kwargs)
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.info("Loaded subagent '%s' in %.1fms", name, elapsed_ms)
            subagents.append(spec)
        except Exception:
            logger.exception("Failed to load subagent '%s'", name)
    return subagents


def _resolve_subagents_parallel(
    pending: list[tuple[str, Callable, dict]],
) -> list[SubAgent | CompiledSubAgent]:
    """Build subagent specs concurrently, preserving order."""
    import time
    from concurrent.futures import ThreadPoolExecutor

    max_workers = min(len(pending), 4)

    def _build(entry: tuple[str, Callable, dict]) -> SubAgent | CompiledSubAgent:
        name, factory, kwargs = entry
        start = time.perf_counter()
        spec = factory(**kwargs)
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info("Loaded subagent '%s' in %.1fms", name, elapsed_ms)
        return spec

    subagents: list[SubAgent | CompiledSubAgent] = []
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="subagent-load") as pool:
        futures = [(entry[0], pool.submit(_build, entry)) for entry in pending]
        for name, future in futures:
            try:
                subagents.append(future.result())
            except Exception:
                logger.exception("Failed to load subagent '%s'", name)
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
