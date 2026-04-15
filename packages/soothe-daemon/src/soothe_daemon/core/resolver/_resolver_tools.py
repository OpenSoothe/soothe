"""Tool, goal, and subagent resolution for create_soothe_agent.

Extracted from ``resolver.py`` to isolate tool/subagent wiring from
protocol and infrastructure resolution.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from soothe.config import BrowserSubagentConfig, SootheConfig
from soothe.utils import expand_path

if TYPE_CHECKING:
    from collections.abc import Callable

    from deepagents.middleware.subagents import CompiledSubAgent, SubAgent
    from langchain_core.language_models import BaseChatModel
    from langchain_core.tools import BaseTool
    from soothe.cognition import GoalEngine

logger = logging.getLogger(__name__)


def _get_subagent_factories() -> dict[str, Callable[..., SubAgent | CompiledSubAgent]]:
    """Lazily load subagent factories on first access.

    This avoids importing heavy subagent modules (browser)
    at module load time, which was causing 24+ second startup delays.
    """
    from soothe_daemon.subagents.browser import create_browser_subagent
    from soothe_daemon.subagents.claude import create_claude_subagent
    from soothe_daemon.subagents.research import create_research_subagent

    return {
        "browser": create_browser_subagent,
        "claude": create_claude_subagent,
        "research": create_research_subagent,
    }


# Lazy accessor for SUBAGENT_FACTORIES
class _SubagentFactoriesAccessor:
    """Lazy accessor for subagent factories."""

    _factories: dict[str, Callable[..., SubAgent | CompiledSubAgent]] | None = None

    def __getitem__(self, key: str) -> Callable[..., SubAgent | CompiledSubAgent]:
        if self._factories is None:
            self._factories = _get_subagent_factories()
        return self._factories[key]

    def get(self, key: str, default: Any = None) -> Any:
        if self._factories is None:
            self._factories = _get_subagent_factories()
        return self._factories.get(key, default)

    def keys(self) -> Any:  # type: ignore[override]
        if self._factories is None:
            self._factories = _get_subagent_factories()
        return self._factories.keys()

    def items(self) -> Any:  # type: ignore[override]
        if self._factories is None:
            self._factories = _get_subagent_factories()
        return self._factories.items()

    def __len__(self) -> int:
        if self._factories is None:
            self._factories = _get_subagent_factories()
        return len(self._factories)


SUBAGENT_FACTORIES = _SubagentFactoriesAccessor()


# ---------------------------------------------------------------------------
# Tool resolution
# ---------------------------------------------------------------------------


def resolve_tools(
    tools_config: Any,
    *,
    lazy: bool = False,
    config: SootheConfig | None = None,
) -> list[BaseTool]:
    """Resolve tool groups from ToolsConfig to instantiated langchain BaseTool lists.

    Args:
        tools_config: ToolsConfig instance with enabled tool groups.
        lazy: If True, load tool groups in parallel using a thread pool
            for faster startup.  Historically this created lazy proxies,
            but those are incompatible with langgraph ToolNode's eager
            metadata probing.
        config: Optional Soothe config for tool configuration.

    Returns:
        Flat list of fully-initialised `BaseTool` instances.
    """
    import time

    # Get list of enabled tool group names
    # Note: "research" is a subagent, not a tool group - handled in resolve_subagents()
    enabled_tools = [
        name
        for name in [
            "execution",
            "file_ops",
            "code_edit",
            "datetime",
            "data",
            "web_search",
            "image",
            "audio",
            "video",
            "github",
        ]
        if getattr(tools_config, name, None) and getattr(tools_config, name).enabled
    ]

    total_start = time.perf_counter()

    parallel = lazy and len(enabled_tools) > 1
    tools = (
        _resolve_tools_parallel(enabled_tools, config)
        if parallel
        else _resolve_tools_sequential(enabled_tools, config)
    )

    total_elapsed_ms = (time.perf_counter() - total_start) * 1000
    logger.info(
        "Resolved %d tool groups (%d tools) in %.1fms (parallel=%s)",
        len(enabled_tools),
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
            tools.extend(resolved)
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
        futures = {
            name: pool.submit(_resolve_single_tool_group, name, config) for name in tool_names
        }
        for name in tool_names:
            try:
                results[name] = futures[name].result()
            except Exception:
                logger.warning("Failed to load tool group '%s'", name, exc_info=True)

    tools: list[BaseTool] = []
    for name in tool_names:
        tools.extend(results.get(name, []))
    return tools


def _resolve_single_tool_group(name: str, config: SootheConfig | None = None) -> list[BaseTool]:
    """Resolve a single tool group name to a list of BaseTool instances with caching and profiling.

    This method checks the cache first, and if not found, delegates to the uncached version.
    """
    import time

    from soothe_daemon.core.lazy_tools import cache_tools, get_cached_tools

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


def _resolve_single_tool_group_uncached(
    name: str, config: SootheConfig | None = None
) -> list[BaseTool]:
    """Resolve a single tool group name to a list of BaseTool instances.

    Args:
        name: Tool group name.
        config: Optional Soothe config for tool configuration.
    """
    # Try plugin registry first
    try:
        from soothe_daemon.plugin.global_registry import get_plugin_registry, is_plugins_loaded

        if is_plugins_loaded():
            registry = get_plugin_registry()
            plugin_tools = registry.get_tools_for_group(name)
            if plugin_tools:
                logger.debug(
                    "Resolved tool group '%s' from plugins (%d tools)", name, len(plugin_tools)
                )
                return plugin_tools
    except RuntimeError:
        logger.debug(
            "Plugin registry not loaded, falling back to hardcoded dispatch for '%s'", name
        )

    # Fallback to hardcoded dispatch (to be removed after migration)
    if name == "datetime":
        from soothe_daemon.tools.datetime import create_datetime_tools

        return list(create_datetime_tools())
    if name == "image":
        from soothe_daemon.tools.image import create_image_tools

        return list(create_image_tools())
    if name == "audio":
        from soothe_daemon.tools.audio import create_audio_tools

        return list(create_audio_tools(config=config))
    if name == "video":
        from soothe_daemon.tools.video import create_video_tools

        return list(create_video_tools())
    if name == "github":
        try:
            from langchain_community.utilities import GitHubAPIWrapper

            wrapper = GitHubAPIWrapper()
            return wrapper.get_tools()
        except Exception:
            logger.debug("github tool not available (pip install pygithub)", exc_info=True)
            return []

    if name == "web_search":
        from soothe_daemon.tools.web_search import create_websearch_tools

        web_search_config: dict = {}
        if config and hasattr(config, "tools") and hasattr(config.tools, "web_search"):
            ws = config.tools.web_search
            web_search_config = {
                "default_engines": ws.default_engines,
                "max_results_per_engine": ws.max_results_per_engine,
                "timeout": ws.timeout,
            }
        if config and hasattr(config, "debug"):
            web_search_config["debug"] = config.debug
        return list(create_websearch_tools(web_search_config))

    # --- Consolidated execution tools (RFC-0016 refactoring) ---
    if name == "execution":
        from soothe_daemon.tools.execution import create_execution_tools

        resolved_cwd = (
            str(expand_path(config.workspace_dir))
            if config and config.workspace_dir
            else str(Path.cwd())
        )
        return list(create_execution_tools(workspace_root=resolved_cwd))

    # Support individual tool names (map to consolidated group)
    if name in ("run_command", "run_background", "kill_process", "run_python"):
        from soothe_daemon.tools.execution import (
            KillProcessTool,
            RunBackgroundTool,
            RunCommandTool,
            RunPythonTool,
        )

        resolved_cwd = (
            str(expand_path(config.workspace_dir))
            if config and config.workspace_dir
            else str(Path.cwd())
        )
        if name == "run_command":
            return [RunCommandTool(workspace_root=resolved_cwd)]
        if name == "run_python":
            return [RunPythonTool(workdir=resolved_cwd)]
        if name == "run_background":
            return [RunBackgroundTool()]
        if name == "kill_process":
            return [KillProcessTool()]

    # --- Consolidated file operation tools (RFC-0016 refactoring) ---
    if name == "file_ops":
        from soothe_daemon.tools.file_ops import create_file_ops_tools

        resolved_cwd = (
            str(expand_path(config.workspace_dir))
            if config and config.workspace_dir
            else str(Path.cwd())
        )
        allow_outside = (
            config.security.allow_paths_outside_workspace
            if config and hasattr(config, "security")
            else False
        )
        return list(
            create_file_ops_tools(work_dir=resolved_cwd, allow_outside_workdir=allow_outside)
        )

    # Support individual tool names (map to consolidated group)
    if name in (
        "read_file",
        "write_file",
        "delete_file",
        "search_files",
        "list_files",
        "file_info",
    ):
        from soothe_daemon.tools.file_ops import (
            DeleteFileTool,
            FileInfoTool,
            ListFilesTool,
            ReadFileTool,
            SearchFilesTool,
            WriteFileTool,
        )

        resolved_cwd = (
            str(expand_path(config.workspace_dir))
            if config and config.workspace_dir
            else str(Path.cwd())
        )
        allow_outside = (
            config.security.allow_paths_outside_workspace
            if config and hasattr(config, "security")
            else False
        )
        if name == "read_file":
            return [ReadFileTool(work_dir=resolved_cwd, allow_outside_workdir=allow_outside)]
        if name == "write_file":
            return [WriteFileTool(work_dir=resolved_cwd, allow_outside_workdir=allow_outside)]
        if name == "delete_file":
            return [DeleteFileTool(work_dir=resolved_cwd, allow_outside_workdir=allow_outside)]
        if name == "search_files":
            return [SearchFilesTool(work_dir=resolved_cwd)]
        if name == "list_files":
            return [ListFilesTool(work_dir=resolved_cwd)]
        if name == "file_info":
            return [FileInfoTool(work_dir=resolved_cwd, allow_outside_workdir=allow_outside)]

    # --- Surgical editing tools (RFC-0016 Phase 2) ---
    if name == "code_edit":
        from soothe_daemon.tools.code_edit import create_code_edit_tools

        resolved_cwd = (
            str(expand_path(config.workspace_dir))
            if config and config.workspace_dir
            else str(Path.cwd())
        )
        allow_outside = (
            config.security.allow_paths_outside_workspace
            if config and hasattr(config, "security")
            else False
        )
        return list(
            create_code_edit_tools(work_dir=resolved_cwd, allow_outside_workdir=allow_outside)
        )

    # Support individual tool names (map to consolidated group)
    if name in ("edit_file_lines", "insert_lines", "delete_lines", "apply_diff"):
        from soothe_daemon.tools.code_edit import (
            ApplyDiffTool,
            DeleteLinesTool,
            EditFileLinesTool,
            InsertLinesTool,
        )

        resolved_cwd = (
            str(expand_path(config.workspace_dir))
            if config and config.workspace_dir
            else str(Path.cwd())
        )
        allow_outside = (
            config.security.allow_paths_outside_workspace
            if config and hasattr(config, "security")
            else False
        )
        if name == "edit_file_lines":
            return [EditFileLinesTool(work_dir=resolved_cwd, allow_outside_workdir=allow_outside)]
        if name == "insert_lines":
            return [InsertLinesTool(work_dir=resolved_cwd, allow_outside_workdir=allow_outside)]
        if name == "delete_lines":
            return [DeleteLinesTool(work_dir=resolved_cwd, allow_outside_workdir=allow_outside)]
        if name == "apply_diff":
            return [ApplyDiffTool(work_dir=resolved_cwd, allow_outside_workdir=allow_outside)]

    # --- Data inspection tools (RFC-0016 single-purpose) ---
    if name == "data":
        from soothe_daemon.tools.data import create_data_tools

        return list(create_data_tools(config=config))

    # Support individual data tool names (map to consolidated group)
    if name in (
        "inspect_data",
        "summarize_data",
        "check_data_quality",
        "extract_text",
        "get_data_info",
        "ask_about_file",
    ):
        from soothe_daemon.tools.data import (
            AskAboutFileTool,
            CheckDataQualityTool,
            ExtractTextTool,
            GetDataInfoTool,
            InspectDataTool,
            SummarizeDataTool,
        )

        if name == "inspect_data":
            return [InspectDataTool(config=config)]
        if name == "summarize_data":
            return [SummarizeDataTool(config=config)]
        if name == "check_data_quality":
            return [CheckDataQualityTool()]
        if name == "extract_text":
            return [ExtractTextTool()]
        if name == "get_data_info":
            return [GetDataInfoTool()]
        if name == "ask_about_file":
            return [AskAboutFileTool(config=config)]

    # --- Goal management tools (RFC-0016 single-purpose) ---
    if name == "goals":
        return []  # Goals are handled separately via resolve_goal_tools

    # Support individual goal tool names (map to consolidated group)
    if name in ("create_goal", "list_goals", "complete_goal", "fail_goal"):
        # These require goal_engine, return empty for now
        # They will be handled via resolve_goal_tools
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
    from soothe.cognition import GoalEngine

    return GoalEngine(max_retries=config.autonomous.max_retries)


def resolve_goal_tools(goal_engine: GoalEngine) -> list[BaseTool]:
    """Create goal management tools bound to a GoalEngine.

    Args:
        goal_engine: The engine to bind.

    Returns:
        List of goal management BaseTool instances.
    """
    from soothe_daemon.tools.goals import create_goals_tools

    return create_goals_tools(goal_engine)


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
    resolved_cwd = (
        str(expand_path(config.workspace_dir)) if config.workspace_dir else str(Path.cwd())
    )

    for name, sub_cfg in config.subagents.items():
        if not sub_cfg.enabled:
            continue

        # Try plugin registry first
        factory = None
        try:
            from soothe_daemon.plugin.global_registry import get_plugin_registry, is_plugins_loaded

            if is_plugins_loaded():
                registry = get_plugin_registry()
                factory = registry.get_subagent_factory(name)
                if factory:
                    logger.debug("Resolved subagent '%s' from plugin registry", name)
        except RuntimeError:
            logger.debug("Plugin registry not loaded, using fallback for '%s'", name)

        # Fallback to SUBAGENT_FACTORIES
        if factory is None:
            factory = SUBAGENT_FACTORIES.get(name)

        if factory is None:
            logger.warning("Unknown subagent '%s', skipping.", name)
            continue

        model_override = (
            None
            if name == "claude"
            else sub_cfg.model or default_model or config.resolve_model("default")
        )

        extra_kwargs: dict = dict(sub_cfg.config)
        if name in cwd_subagents and "cwd" not in extra_kwargs:
            extra_kwargs["cwd"] = resolved_cwd
        if name == "browser":
            extra_kwargs["config"] = BrowserSubagentConfig(**sub_cfg.config)
        if name == "research":
            extra_kwargs["config"] = config
            if "context" not in extra_kwargs:
                extra_kwargs["context"] = {"work_dir": resolved_cwd}

        pending.append((name, factory, {"model": model_override, **extra_kwargs}))

    parallel = lazy and len(pending) > 1
    subagents = (
        _resolve_subagents_parallel(pending) if parallel else _resolve_subagents_sequential(pending)
    )

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
