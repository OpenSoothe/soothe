"""Tool, goal, and subagent resolution for create_nano_agent.

Extracted from ``resolver.py`` to isolate tool/subagent wiring from
protocol and infrastructure resolution.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from soothe_nano.config import SootheConfig, SubagentConfig
from soothe_nano.config.models import ModelRole
from soothe_nano.toolkits.file_ops_catalog import (
    SURGICAL_FILE_OP_TOOL_NAME_SET,
    build_filesystem_tools,
    build_surgical_file_ops_tools,
)
from soothe_nano.workspace.workspace_paths import (
    filesystem_virtual_mode_from_soothe_config,
    max_file_size_mb_for_filesystem_backend,
    resolve_effective_tool_workspace,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from langchain_core.language_models import BaseChatModel
    from langchain_core.tools import BaseTool
    from soothe_deepagents.middleware.subagents import CompiledSubAgent, SubAgent

logger = logging.getLogger(__name__)


def _workspace_backend_factory(
    *,
    virtual_mode: bool,
    max_file_size_mb: int,
) -> Callable[[str], Any]:
    """Build a workspace-scoped backend factory for surgical file tools."""
    from soothe_nano.workspace.workspace_filesystem import get_workspace_backend

    def factory(workspace: str) -> Any:
        return get_workspace_backend(
            Path(workspace).expanduser().resolve(),
            virtual_mode=virtual_mode,
            max_file_size_mb=max_file_size_mb,
        )

    return factory


def _build_soothe_file_tools(
    config: SootheConfig | None,
    *,
    surgical_only: bool = False,
) -> list[BaseTool]:
    """Create filesystem tools bound to the effective workspace."""
    resolved_cwd = str(resolve_effective_tool_workspace(config))
    virtual_mode = filesystem_virtual_mode_from_soothe_config(config) if config else False
    max_file_size_mb = max_file_size_mb_for_filesystem_backend(config) if config else 10
    backend = _workspace_backend_factory(
        virtual_mode=virtual_mode,
        max_file_size_mb=max_file_size_mb,
    )(resolved_cwd)
    if surgical_only:
        return build_surgical_file_ops_tools(
            backend=backend,
            backup_enabled=True,
            workspace_root=resolved_cwd,
            workspace_backend_factory=_workspace_backend_factory(
                virtual_mode=virtual_mode,
                max_file_size_mb=max_file_size_mb,
            ),
            tool_token_limit_before_evict=20000,
        )
    return build_filesystem_tools(
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
    from soothe_nano.subagents.academic_research import create_academic_research_subagent
    from soothe_nano.subagents.browser_use import create_browser_use_subagent
    from soothe_nano.subagents.deep_research import create_deep_research_subagent
    from soothe_nano.subagents.explore import create_explorer_subagent
    from soothe_nano.subagents.plan import create_plan_subagent

    return {
        "planner": create_plan_subagent,
        "explorer": create_explorer_subagent,
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


def _resolve_subagent_chat_model(
    config: SootheConfig,
    sub_cfg: SubagentConfig,
    *,
    default_role: ModelRole,
) -> BaseChatModel:
    """Resolve a subagent chat model from an explicit spec or router role.

    When ``sub_cfg.model`` is set (``provider:model``), it takes precedence over
    ``sub_cfg.model_role`` and ``default_role``.
    """
    if sub_cfg.model:
        return config.create_chat_model_for_spec(sub_cfg.model)
    role = sub_cfg.model_role or default_role
    return config.create_chat_model(role)


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
    # Host-execution tools run on the host via subprocess (see toolkits.execution).

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

    from soothe_nano.workspace.workspace_filesystem import FrameworkFilesystem

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
        from soothe_nano.plugin.global_registry import get_plugin_registry, is_plugins_loaded

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
        from soothe_nano.toolkits.datetime import DatetimeToolkit

        toolkit = DatetimeToolkit()
        return toolkit.get_tools()

    if name == "wizsearch":
        from soothe_nano.toolkits.wizsearch import WizsearchToolkit

        web_search_config: dict = {}
        if config and hasattr(config, "tools") and hasattr(config.tools, "wizsearch"):
            ws = config.tools.wizsearch
            web_search_config = {
                "default_engines": ws.default_engines,
                "max_results_per_engine": ws.max_results_per_engine,
                "timeout": ws.timeout,
                "proxy": ws.proxy,
            }
        if config and hasattr(config, "debug"):
            web_search_config["debug"] = config.debug
        toolkit = WizsearchToolkit(config=web_search_config)
        return toolkit.get_tools()

    if name == "execution":
        from soothe_nano.toolkits.execution import build_execution_toolkit

        resolved_cwd = str(resolve_effective_tool_workspace(config))
        return build_execution_toolkit(
            config=config,
            workspace_root=resolved_cwd,
        ).get_tools()

    if name == "http_requests":
        from soothe_nano.toolkits.http_requests import HttpRequestsToolkit

        toolkit = HttpRequestsToolkit(config=config)
        return toolkit.get_tools()

    # Support individual tool names (map to consolidated group)
    if name in (
        "run_command",
        "run_background",
        "tail_background_log",
        "kill_process",
        "run_python",
    ):
        # Host-execution tools do not require a sandbox backend.
        from soothe_nano.toolkits.execution import build_execution_toolkit

        resolved_cwd = str(resolve_effective_tool_workspace(config))
        all_tools = build_execution_toolkit(
            config=config,
            workspace_root=resolved_cwd,
        ).get_tools()
        tool_map = {tool.name: tool for tool in all_tools}
        if name in tool_map:
            return [tool_map[name]]
        logger.warning("Tool '%s' not found in ExecutionToolkit", name)
        return []

    if name == "file_ops":
        return _build_soothe_file_tools(config, surgical_only=True)

    # Support individual tool names (map to consolidated group)
    if name in (
        "read_file",
        "write_file",
        "delete",
        "search_files",
        "list_files",
        "file_info",
        "edit_lines",
        "insert_lines",
        "delete_lines",
        "apply_diff",
    ):
        if name in SURGICAL_FILE_OP_TOOL_NAME_SET:
            surgical_tools = _build_soothe_file_tools(config, surgical_only=True)
            surgical_tool_map = {tool.name: tool for tool in surgical_tools}
            if name in surgical_tool_map:
                return [surgical_tool_map[name]]
            logger.warning("Tool '%s' not found in surgical file_ops catalog", name)
            return []

        full_tool_map = {tool.name: tool for tool in _build_soothe_file_tools(config)}
        if name in full_tool_map:
            return [full_tool_map[name]]
        logger.warning("Tool '%s' not found in filesystem tools", name)
        return []

    if name == "data":
        from soothe_nano.toolkits.data import DataToolkit

        toolkit = DataToolkit(config=config)
        return toolkit.get_tools()

    if name == "deepxiv":
        from soothe_nano.toolkits.deepxiv import DeepxivToolkit, resolve_deepxiv_token

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
        from soothe_nano.toolkits.data import DataToolkit

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
            from soothe_nano.plugin.global_registry import get_plugin_registry, is_plugins_loaded

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

        if name in ("deep_research", "academic_research"):
            model_override = _resolve_subagent_chat_model(config, sub_cfg, default_role="fast")
        elif name == "explorer":
            model_override = _resolve_subagent_chat_model(config, sub_cfg, default_role="fast")
        elif name == "planner":
            model_override = _resolve_subagent_chat_model(config, sub_cfg, default_role="think")
        elif name == "browser_use":
            model_override = None
        else:
            model_override = sub_cfg.model or default_model or config.resolve_model("default")

        if resolved_via_plugin:
            from soothe_nano.plugin.context import create_plugin_context

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
        elif name == "explorer":
            # Explorer YAML options live in ``config.subagents[name].config`` only.
            # Factory accepts ``model``, ``SootheConfig``, and ``context``.
            extra_kwargs.clear()
            extra_kwargs["config"] = config
            extra_kwargs["context"] = {"work_dir": resolved_cwd}
        elif name == "planner":
            extra_kwargs.clear()
            extra_kwargs["config"] = config
            extra_kwargs["context"] = {"work_dir": resolved_cwd}
        elif name == "browser_use":
            from soothe_nano.subagents.browser_use.config_model import BrowserUseSubagentConfig

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

    from soothe_nano.resolve._lazy_subagent import lazy_compiled_subagent_spec

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
