"""Tool, goal, and subagent resolution for create_soothe_agent.

Extracted from ``resolver.py`` to isolate tool/subagent wiring from
protocol and infrastructure resolution.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from soothe.config import SootheConfig
from soothe.foundation.workspace.tool_path_resolution import (
    filesystem_virtual_mode_from_soothe_config,
    max_file_size_mb_for_filesystem_backend,
    resolve_effective_tool_workspace,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from deepagents.middleware.subagents import CompiledSubAgent, SubAgent
    from langchain_core.language_models import BaseChatModel
    from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)


def _workspace_backend_factory(
    *,
    virtual_mode: bool,
    max_file_size_mb: int,
) -> Callable[[str], Any]:
    """Build a workspace-scoped backend factory for surgical file tools."""
    from soothe.foundation.workspace.normalized_backend import get_workspace_backend

    def factory(workspace: str) -> Any:
        return get_workspace_backend(
            Path(workspace).expanduser().resolve(),
            virtual_mode=virtual_mode,
            max_file_size_mb=max_file_size_mb,
        )

    return factory


def _build_soothe_file_middleware(config: SootheConfig | None) -> Any:
    """Create ``SootheFilesystemMiddleware`` bound to the effective workspace."""
    from soothe.middleware.filesystem import SootheFilesystemMiddleware

    resolved_cwd = str(resolve_effective_tool_workspace(config))
    virtual_mode = filesystem_virtual_mode_from_soothe_config(config) if config else False
    max_file_size_mb = max_file_size_mb_for_filesystem_backend(config) if config else 10
    backend = _workspace_backend_factory(
        virtual_mode=virtual_mode,
        max_file_size_mb=max_file_size_mb,
    )(resolved_cwd)
    return SootheFilesystemMiddleware(
        backend=backend,
        backup_enabled=True,
        workspace_root=resolved_cwd,
        workspace_backend_factory=_workspace_backend_factory(
            virtual_mode=virtual_mode,
            max_file_size_mb=max_file_size_mb,
        ),
        tool_token_limit_before_evict=20000,
    )


def _get_subagent_factories() -> dict[str, Callable[..., SubAgent | CompiledSubAgent]]:
    """Lazily load subagent factories on first access.

    This avoids importing heavy subagent modules at module load time.
    """
    from soothe.subagents.academic_research import create_academic_research_subagent
    from soothe.subagents.browser_use import create_browser_use_subagent
    from soothe.subagents.deep_research import create_deep_research_subagent
    from soothe.subagents.plan import create_plan_subagent

    return {
        "planner": create_plan_subagent,
        "deep_research": create_deep_research_subagent,
        "academic_research": create_academic_research_subagent,
        "browser_use": create_browser_use_subagent,
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


def _call_subagent_factory(factory: Any, kwargs: dict[str, Any]) -> Any:
    """Invoke a subagent factory and return its spec (dict or agent object).

    Plugin factories from ``@subagent`` are async; built-in factories are sync.
    When no event loop is running, coroutine results are driven with
    :func:`asyncio.run` (AgentBuilder runs in a synchronous context).
    When a loop is already running (e.g. async tests or nested async), the
    coroutine is completed on a worker thread with its own loop so we never
    call :func:`asyncio.run` from inside a running loop.
    """
    import asyncio
    import inspect
    from concurrent.futures import ThreadPoolExecutor

    result = factory(**kwargs)
    if not inspect.iscoroutine(result):
        return result
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(result)

    def _run_coro_on_fresh_loop(coro: Any) -> Any:
        return asyncio.run(coro)

    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(_run_coro_on_fresh_loop, result).result()


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
    # Note: "deep_research" is a subagent, not a tool group - handled in resolve_subagents()
    _tool_groups = [
        "execution",
        "file_ops",
        "datetime",
        "data",
        "wizsearch",
        "http_requests",
        "deepxiv",
    ]
    enabled_tools = []
    for name in _tool_groups:
        group_cfg = getattr(tools_config, name, None)
        if group_cfg and group_cfg.enabled:
            enabled_tools.append(name)

    # Host-execution tools (run_command, run_python, etc.) do not require a
    # sandbox — they run on the host via subprocess. The `execute`
    # tool (which needs a SandboxBackendProtocol) is filtered separately in
    # execute_tool_filter.py.

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

    from soothe.foundation.workspace.framework_filesystem import FrameworkFilesystem

    from ._tool_cache import cache_tools, get_cached_tools

    # Include workspace in cache key to prevent cross-workspace tool reuse
    current_ws = FrameworkFilesystem.get_current_workspace()
    ws_key = str(current_ws) if current_ws else None

    cached = get_cached_tools(name, workspace=ws_key)
    if cached is not None:
        logger.debug("Tool group '%s' loaded from cache (%d tools)", name, len(cached))
        return cached

    start = time.perf_counter()
    tools = _resolve_single_tool_group_uncached(name, config)
    elapsed_ms = (time.perf_counter() - start) * 1000

    if tools:
        cache_tools(name, tools, workspace=ws_key)

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
        from soothe.plugin.global_registry import get_plugin_registry, is_plugins_loaded

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

    # Toolkit dispatch using new toolkit classes
    if name == "datetime":
        from soothe.toolkits.datetime import DatetimeToolkit

        toolkit = DatetimeToolkit()
        return toolkit.get_tools()

    if name == "wizsearch":
        from soothe.toolkits.wizsearch import WizsearchToolkit

        web_search_config: dict = {}
        if config and hasattr(config, "tools") and hasattr(config.tools, "wizsearch"):
            ws = config.tools.wizsearch
            web_search_config = {
                "default_engines": ws.default_engines,
                "max_results_per_engine": ws.max_results_per_engine,
                "timeout": ws.timeout,
            }
        if config and hasattr(config, "debug"):
            web_search_config["debug"] = config.debug
        toolkit = WizsearchToolkit(config=web_search_config)
        return toolkit.get_tools()

    if name == "execution":
        from soothe.toolkits.execution import ExecutionToolkit, _execution_max_output_from_config

        resolved_cwd = str(resolve_effective_tool_workspace(config))
        toolkit = ExecutionToolkit(
            workspace_root=resolved_cwd,
            security_config=(getattr(config, "security", None) if config else None),
            max_output_length=_execution_max_output_from_config(config),
        )
        return toolkit.get_tools()

    if name == "http_requests":
        from soothe.toolkits.http_requests import HttpRequestsToolkit

        toolkit = HttpRequestsToolkit(config=config)
        return toolkit.get_tools()

    # Support individual tool names (map to consolidated group)
    if name in ("run_command", "run_background", "kill_process", "run_python"):
        # Host-execution tools do not require a sandbox backend.
        from soothe.toolkits.execution import ExecutionToolkit, _execution_max_output_from_config

        resolved_cwd = str(resolve_effective_tool_workspace(config))
        toolkit = ExecutionToolkit(
            workspace_root=resolved_cwd,
            security_config=(getattr(config, "security", None) if config else None),
            max_output_length=_execution_max_output_from_config(config),
        )
        all_tools = toolkit.get_tools()
        tool_map = {tool.name: tool for tool in all_tools}
        if name in tool_map:
            return [tool_map[name]]
        logger.warning("Tool '%s' not found in ExecutionToolkit", name)
        return []

    if name == "file_ops":
        middleware = _build_soothe_file_middleware(config)

        # Extract surgical tools only (not ls, read_file, etc. from FilesystemMiddleware)
        surgical_tool_names = [
            "delete_file",
            "file_info",
            "edit_file_lines",
            "insert_lines",
            "delete_lines",
            "apply_diff",
        ]
        tools = [t for t in middleware.tools if t.name in surgical_tool_names]
        return tools

    # Support individual tool names (map to consolidated group)
    if name in (
        "read_file",
        "write_file",
        "delete_file",
        "search_files",
        "list_files",
        "file_info",
        "edit_file_lines",
        "insert_lines",
        "delete_lines",
        "apply_diff",
    ):
        middleware = _build_soothe_file_middleware(config)

        # Extract surgical tools only
        surgical_tool_names = [
            "delete_file",
            "file_info",
            "edit_file_lines",
            "insert_lines",
            "delete_lines",
            "apply_diff",
        ]
        all_tools = [t for t in middleware.tools if t.name in surgical_tool_names]
        tool_map = {tool.name: tool for tool in all_tools}

        # For read_file/write_file/edit_file/search_files/list_files, these come from the middleware
        # so we need to get them from the middleware's full tools list
        if name in ("read_file", "write_file", "edit_file", "search_files", "list_files"):
            full_tool_map = {tool.name: tool for tool in middleware.tools}
            if name in full_tool_map:
                return [full_tool_map[name]]
            logger.warning("Tool '%s' not found in SootheFilesystemMiddleware", name)
            return []

        if name in tool_map:
            return [tool_map[name]]
        logger.warning("Tool '%s' not found in surgical tools", name)
        return []

    if name == "data":
        from soothe.toolkits.data import DataToolkit

        toolkit = DataToolkit(config=config)
        return toolkit.get_tools()

    if name == "deepxiv":
        from soothe.toolkits.deepxiv import DeepxivToolkit, resolve_deepxiv_token

        token: str | None = None
        timeout = 60
        max_retries = 3
        if config and hasattr(config, "tools"):
            dx = getattr(config.tools, "deepxiv", None)
            if dx:
                token = getattr(dx, "token", None)
                timeout = getattr(dx, "timeout", 60)
                max_retries = getattr(dx, "max_retries", 3)
        toolkit = DeepxivToolkit(
            token=resolve_deepxiv_token(token),
            timeout=timeout,
            max_retries=max_retries,
        )
        return toolkit.get_tools()

    # Support individual data tool names (map to consolidated group)
    if name in (
        "inspect_data",
        "summarize_data",
        "check_data_quality",
        "extract_text",
        "get_data_info",
        "ask_about_file",
    ):
        from soothe.toolkits.data import DataToolkit

        toolkit = DataToolkit(config=config)
        all_tools = toolkit.get_tools()
        tool_map = {tool.name: tool for tool in all_tools}
        if name in tool_map:
            return [tool_map[name]]
        logger.warning("Tool '%s' not found in DataToolkit", name)
        return []

    logger.warning("Unknown tool group '%s', skipping.", name)
    return []


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
        List of subagent specs for the runtime.
    """
    import time

    total_start = time.perf_counter()

    # Collect (name, factory, kwargs) tuples for enabled subagents
    pending: list[tuple[str, Callable, dict]] = []
    resolved_cwd = str(resolve_effective_tool_workspace(config))

    for name, sub_cfg in config.subagents.items():
        if not sub_cfg.enabled:
            continue

        factory = None
        resolved_via_plugin = False
        try:
            from soothe.plugin.global_registry import get_plugin_registry, is_plugins_loaded

            if is_plugins_loaded():
                registry = get_plugin_registry()
                reg_factory = registry.get_subagent_factory(name)
                if reg_factory is not None:
                    factory = reg_factory
                    resolved_via_plugin = True
                    logger.debug("Resolved subagent '%s' from plugin registry", name)
        except RuntimeError:
            logger.debug("Plugin registry not loaded, using fallback for '%s'", name)

        if factory is None:
            factory = SUBAGENT_FACTORIES.get(name)

        if factory is None:
            logger.warning("Unknown subagent '%s', skipping.", name)
            continue

        if name == "claude":
            model_override = None
        elif name in ("deep_research", "academic_research"):
            model_override = sub_cfg.model or config.create_chat_model("fast")
        elif name == "planner":
            # Built-in: always the router ``think`` role (ignore ``subagents.planner.model``).
            model_override = config.create_chat_model("think")
        elif name == "browser_use":
            model_override = None
        else:
            model_override = sub_cfg.model or default_model or config.resolve_model("default")

        if resolved_via_plugin:
            from soothe.plugin.context import create_plugin_context

            plugin_instance = factory.__self__
            pname = plugin_instance.manifest.name
            plugin_ctx = create_plugin_context(
                plugin_name=pname,
                config=dict(sub_cfg.config),
                soothe_config=config,
            )
            call_kwargs = dict(sub_cfg.config)
            call_kwargs["model"] = model_override
            call_kwargs["config"] = config
            call_kwargs["context"] = plugin_ctx
            pending.append((name, factory, call_kwargs))
            continue

        extra_kwargs: dict = dict(sub_cfg.config)
        if name in ("deep_research", "academic_research"):
            # Research YAML options live in ``config.subagents[name].config`` only.
            # Factories accept ``model``, ``SootheConfig``, and ``context``.
            extra_kwargs.clear()
            extra_kwargs["config"] = config
            extra_kwargs["context"] = {"work_dir": resolved_cwd}
        elif name == "planner":
            extra_kwargs.clear()
            extra_kwargs["config"] = config
            extra_kwargs["context"] = {"work_dir": resolved_cwd}
        elif name == "browser_use":
            from soothe.subagents.browser_use.config_model import BrowserUseSubagentConfig

            extra_kwargs.clear()
            cfg_dict = dict(sub_cfg.config)
            if cfg_dict:
                extra_kwargs["config"] = BrowserUseSubagentConfig(**cfg_dict)
            extra_kwargs["soothe_config"] = config
            pending.append((name, factory, extra_kwargs))
            continue

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
    """Register lazy subagent specs one-by-one (graphs compile on first task invoke)."""
    import time

    from soothe.runner.resolver._lazy_subagent import lazy_compiled_subagent_spec

    subagents: list[SubAgent | CompiledSubAgent] = []
    for name, factory, kwargs in pending:
        start = time.perf_counter()
        try:
            spec = lazy_compiled_subagent_spec(name, factory, kwargs)
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.info("Registered lazy subagent '%s' in %.1fms", name, elapsed_ms)
            subagents.append(spec)
        except Exception:
            logger.exception("Failed to register subagent '%s'", name)
    return subagents


def _resolve_subagents_parallel(
    pending: list[tuple[str, Callable, dict]],
) -> list[SubAgent | CompiledSubAgent]:
    """Register lazy subagent specs concurrently, preserving order."""
    return _resolve_subagents_sequential(pending)
