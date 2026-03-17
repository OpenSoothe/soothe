"""Protocol, subagent, and tool resolution logic for create_soothe_agent."""

from __future__ import annotations

import contextlib
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
    from langgraph.types import Checkpointer

    from soothe.core.goal_engine import GoalEngine
    from soothe.protocols.context import ContextProtocol
    from soothe.protocols.durability import DurabilityProtocol
    from soothe.protocols.memory import MemoryProtocol
    from soothe.protocols.planner import PlannerProtocol
    from soothe.protocols.policy import PolicyProtocol

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
                # Create lazy proxy that will load on first use
                # For simplicity, we load the first tool in the group
                proxy = LazyToolProxy(
                    tool_name=name,
                    loader=lambda n=name, c=config: _resolve_single_tool_group_uncached(n, c),
                    index=0,
                )
                tools.append(proxy)
                elapsed_ms = (time.perf_counter() - tool_start) * 1000
                logger.debug("Created lazy proxy for tool '%s' in %.1fms", name, elapsed_ms)
            else:
                # Eager loading with caching
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

    # Check cache first
    cached = get_cached_tools(name)
    if cached is not None:
        logger.debug("Tool group '%s' loaded from cache (%d tools)", name, len(cached))
        return cached

    # Load and cache
    start = time.perf_counter()
    tools = _resolve_single_tool_group_uncached(name, config)
    elapsed_ms = (time.perf_counter() - start) * 1000

    # Cache for future use
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

        # Pass wizsearch config if available
        wizsearch_config = {}
        if config and hasattr(config, "tools_settings") and hasattr(config.tools_settings, "wizsearch"):
            wizsearch_config = {
                "default_engines": config.tools_settings.wizsearch.default_engines,
                "max_results_per_engine": config.tools_settings.wizsearch.max_results_per_engine,
                "timeout": config.tools_settings.wizsearch.timeout,
            }
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

    # New tools from enhancement
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
        except Exception:
            logger.debug("Failed to load arxiv tool, skipping", exc_info=True)
            return []
    if name == "wikipedia":
        try:
            from langchain_community.tools import WikipediaQueryRun
            from langchain_community.utilities import WikipediaAPIWrapper

            return [WikipediaQueryRun(api_wrapper=WikipediaAPIWrapper())]
        except Exception:
            logger.debug("Failed to load wikipedia tool, skipping", exc_info=True)
            return []
    if name == "github":
        from langchain_community.utilities import GitHubAPIWrapper

        wrapper = GitHubAPIWrapper()
        return wrapper.get_tools()

    if name == "goals":
        # GoalEngine tools are resolved separately via resolve_goal_tools()
        return []

    logger.warning("Unknown tool group '%s', skipping.", name)
    return []


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

    # Subagents that should always be loaded eagerly (commonly used)
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
        if name in ("skillify", "weaver"):
            extra_kwargs["config"] = config
        # Pass browser-specific config
        if name == "browser":
            extra_kwargs["config"] = BrowserSubagentConfig(**sub_cfg.config)

        # Decide whether to load eagerly or lazily
        if lazy and name not in eager_subagents:
            # Create lazy spec that will initialize on first use
            spec = LazySubagentSpec(
                name=name,
                factory=factory,
                kwargs={"model": model_override, **extra_kwargs},
            )
            elapsed_ms = (time.perf_counter() - sub_start) * 1000
            logger.debug("Created lazy spec for subagent '%s' in %.1fms", name, elapsed_ms)
        else:
            # Eager loading (current behavior)
            try:
                spec = factory(model=model_override, **extra_kwargs)
                elapsed_ms = (time.perf_counter() - sub_start) * 1000
                logger.info("Loaded subagent '%s' in %.1fms", name, elapsed_ms)
            except Exception:
                logger.exception("Failed to load subagent '%s'", name)
                continue

        subagents.append(spec)

    # Load generated subagents (these are already compiled, so usually fast)
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


def resolve_context(config: SootheConfig) -> ContextProtocol | None:
    """Instantiate the ContextProtocol implementation from config.

    Falls back to keyword backend when vector initialisation fails.

    Args:
        config: Soothe configuration.

    Returns:
        A ContextProtocol instance, or None if disabled.
    """
    if config.protocols.context.backend == "none":
        return None

    # Parse combined backend: {behavior}-{storage}
    parts = config.protocols.context.backend.split("-")
    if len(parts) != 2:
        logger.warning(
            "Invalid context backend '%s', expected format: {behavior}-{storage}",
            config.protocols.context.backend,
        )
        return None

    behavior, storage = parts

    # Handle vector behavior
    if behavior == "vector" and config.vector_store_provider != "none":
        try:
            from soothe.backends.context.vector import VectorContext
            from soothe.backends.vector_store import create_vector_store

            vs = create_vector_store(
                config.vector_store_provider,
                f"{config.vector_store_collection}_context",
                config.resolve_vector_store_config(),
            )
            embeddings = config.create_embedding_model()
            logger.info("Using vector context backend")
            return VectorContext(vector_store=vs, embeddings=embeddings)
        except Exception:
            logger.warning("Vector context init failed, falling back to keyword", exc_info=True)
    elif behavior == "vector":
        logger.warning("vector context requires vector_store_provider; falling back to keyword")

    # Keyword behavior with storage backend
    from pathlib import Path

    from soothe.backends.context.keyword import KeywordContext
    from soothe.backends.persistence import create_persist_store

    persist_dir = config.protocols.context.persist_dir or str(Path(SOOTHE_HOME) / "context" / "data")

    # Create persist store based on storage backend
    try:
        persist_store = create_persist_store(
            persist_dir=persist_dir,
            backend=storage,
            dsn=config.resolve_persistence_postgres_dsn() if storage == "postgresql" else None,
            namespace="context",
        )
    except Exception as e:
        logger.warning("Failed to create context persist store, falling back to json: %s", e)
        persist_store = create_persist_store(
            persist_dir=persist_dir,
            backend="json",
        )

    logger.info("Using keyword context backend with %s storage", storage)
    return KeywordContext(persist_store=persist_store)


def resolve_memory(config: SootheConfig) -> MemoryProtocol | None:
    """Instantiate the MemoryProtocol implementation from config.

    Falls back to keyword backend when vector initialisation fails.

    Args:
        config: Soothe configuration.

    Returns:
        A MemoryProtocol instance, or None if disabled.
    """
    if config.protocols.memory.backend == "none":
        return None

    # Parse combined backend: {behavior}-{storage}
    parts = config.protocols.memory.backend.split("-")
    if len(parts) != 2:
        logger.warning(
            "Invalid memory backend '%s', expected format: {behavior}-{storage}",
            config.protocols.memory.backend,
        )
        return None

    behavior, storage = parts

    # Handle vector behavior
    if behavior == "vector" and config.vector_store_provider != "none":
        try:
            from soothe.backends.memory.vector import VectorMemory
            from soothe.backends.vector_store import create_vector_store

            vs = create_vector_store(
                config.vector_store_provider,
                f"{config.vector_store_collection}_memory",
                config.resolve_vector_store_config(),
            )
            embeddings = config.create_embedding_model()
            logger.info("Using vector memory backend")
            return VectorMemory(vector_store=vs, embeddings=embeddings)
        except Exception:
            logger.warning("Vector memory init failed, falling back to keyword", exc_info=True)
    elif behavior == "vector":
        logger.warning("vector memory requires vector_store_provider; falling back to keyword")

    # Keyword behavior with storage backend
    from pathlib import Path

    from soothe.backends.memory.keyword import KeywordMemory
    from soothe.backends.persistence import create_persist_store

    persist_dir = config.protocols.memory.persist_dir or str(Path(SOOTHE_HOME) / "memory" / "data")

    # Create persist store based on storage backend
    try:
        persist_store = create_persist_store(
            persist_dir=persist_dir,
            backend=storage,
            dsn=config.resolve_persistence_postgres_dsn() if storage == "postgresql" else None,
            namespace="memory",
        )
    except Exception as e:
        logger.warning("Failed to create memory persist store, falling back to json: %s", e)
        persist_store = create_persist_store(
            persist_dir=persist_dir,
            backend="json",
        )

    logger.info("Using keyword memory backend with %s storage", storage)
    return KeywordMemory(persist_store=persist_store)


def resolve_planner(
    config: SootheConfig,
    model: BaseChatModel | None,
) -> PlannerProtocol:
    """Instantiate the PlannerProtocol implementation from config.

    Always returns a planner -- at minimum DirectPlanner is used as fallback.

    Args:
        config: Soothe configuration.
        model: The resolved chat model.

    Returns:
        A PlannerProtocol instance.
    """
    planner_model = model
    if planner_model is None:
        try:
            planner_model = config.create_chat_model("think")
        except Exception:
            try:
                planner_model = config.create_chat_model("default")
            except Exception:
                logger.warning("Failed to create model for planner")

    resolved_cwd = str(Path(config.workspace_dir).resolve()) if config.workspace_dir else str(Path.cwd())

    from soothe.backends.planning.direct import DirectPlanner

    direct = DirectPlanner(model=planner_model) if planner_model else None

    if config.protocols.planner.routing == "always_direct":
        return direct or DirectPlanner(model=planner_model)

    subagent_planner = None
    try:
        from soothe.backends.planning.subagent import SubagentPlanner

        subagent_planner = SubagentPlanner(model=planner_model, cwd=resolved_cwd)
    except Exception:
        logger.debug("SubagentPlanner init failed", exc_info=True)

    if config.protocols.planner.routing == "always_planner":
        return subagent_planner or direct  # type: ignore[return-value]

    claude_planner = None
    try:
        from soothe.backends.planning.claude import ClaudePlanner

        claude_planner = ClaudePlanner(cwd=resolved_cwd)
    except Exception:
        logger.info("Claude CLI not available for planning")

    if config.protocols.planner.routing == "always_claude":
        return claude_planner or subagent_planner or direct  # type: ignore[return-value]

    from soothe.backends.planning.router import AutoPlanner

    fast_model = None
    with contextlib.suppress(Exception):
        fast_model = config.create_chat_model("fast")

    return AutoPlanner(
        claude=claude_planner,
        subagent=subagent_planner,
        direct=direct,
        fast_model=fast_model,
    )


def resolve_policy(_config: SootheConfig) -> PolicyProtocol | None:
    """Instantiate the PolicyProtocol implementation from config.

    Args:
        _config: Soothe configuration (unused - ConfigDrivenPolicy reads from env).

    Returns:
        A PolicyProtocol instance.
    """
    from soothe.backends.policy.config_driven import ConfigDrivenPolicy

    return ConfigDrivenPolicy()


def resolve_durability(config: SootheConfig) -> DurabilityProtocol:
    """Instantiate the DurabilityProtocol implementation from config.

    Supports: json, rocksdb, postgresql backends.
    Falls back to json durability when other backends fail.
    """
    from pathlib import Path

    # Try PostgreSQL backend
    if config.protocols.durability.backend == "postgresql":
        try:
            from soothe.backends.durability.postgresql import PostgreSQLDurability
            from soothe.backends.persistence import create_persist_store

            persist_store = create_persist_store(
                backend="postgresql",
                dsn=config.resolve_persistence_postgres_dsn(),
                namespace="durability",
            )
            logger.info("Using PostgreSQL durability backend")
            return PostgreSQLDurability(persist_store=persist_store)
        except Exception as e:
            logger.warning(
                "PostgreSQL durability requested but failed: %s. "
                "Falling back to json durability. "
                "Install with: pip install 'soothe[postgres]'",
                e,
            )
            # Fall through to json backend

    # Try RocksDB backend
    if config.protocols.durability.backend == "rocksdb":
        try:
            from soothe.backends.durability.rocksdb import RocksDBDurability
            from soothe.backends.persistence import create_persist_store

            persist_dir = config.protocols.durability.persist_dir or str(Path(SOOTHE_HOME) / "durability" / "data")
            persist_store = create_persist_store(persist_dir, backend="rocksdb")
            if persist_store is None:
                raise ValueError(f"Failed to create RocksDB store at {persist_dir}")

            logger.info("Using RocksDB durability backend at %s", persist_dir)
            return RocksDBDurability(persist_store)
        except (ImportError, RuntimeError, ValueError) as e:
            logger.warning(
                "RocksDB durability requested but dependencies unavailable: %s. "
                "Falling back to json durability. "
                "Install with: pip install soothe[rocksdb]",
                e,
            )
            # Fall through to json backend

    # JSON backend (default fallback)
    if config.protocols.durability.backend in ("json", "postgresql", "rocksdb"):
        from soothe.backends.durability.json import JsonDurability

        persist_dir = config.protocols.durability.persist_dir or str(Path(SOOTHE_HOME) / "durability")
        logger.info("Using json durability backend at %s", persist_dir)
        return JsonDurability(persist_dir=persist_dir)

    # Unknown backend - default to json
    logger.warning(
        "Unknown durability backend '%s'; using json durability",
        config.protocols.durability.backend,
    )
    from soothe.backends.durability.json import JsonDurability

    persist_dir = str(Path(SOOTHE_HOME) / "durability")
    return JsonDurability(persist_dir=persist_dir)


def resolve_checkpointer(config: SootheConfig) -> tuple[Checkpointer, Any] | Checkpointer:
    """Resolve a LangGraph checkpointer from config.

    Uses persistence.soothe_postgres_dsn for connection.
    Falls back to MemorySaver when PostgreSQL is unavailable.

    Returns:
        A tuple of (checkpointer, connection_resource) for PostgreSQL, or just the checkpointer for MemorySaver.
        The connection_resource must be closed during cleanup (e.g., via runner.cleanup()).
    """
    from langgraph.checkpoint.memory import MemorySaver

    backend = config.protocols.durability.checkpointer
    if backend == "postgresql":
        dsn = config.resolve_persistence_postgres_dsn()
        result = _resolve_postgres_checkpointer(dsn)
        if result:
            return result  # (checkpointer, pool)

    logger.warning("Unknown checkpointer backend '%s'; using memory saver", backend)
    return MemorySaver()


def _resolve_postgres_checkpointer(dsn: str) -> tuple[Checkpointer, Any] | None:
    """Initialize PostgreSQL checkpointer with provided DSN.

    Returns:
        A tuple of (AsyncPostgresSaver, AsyncConnectionPool) if successful, None otherwise.
        The pool must be closed during cleanup.
    """
    if not dsn:
        logger.warning("PostgreSQL checkpointer requires DSN configuration")
        return None

    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from psycopg_pool import AsyncConnectionPool
        from psycopg.rows import dict_row
    except ImportError:
        logger.warning(
            "PostgreSQL checkpointer requires 'langgraph[postgres]' and 'psycopg-pool'. "
            "Install with: pip install 'langgraph[postgres]' 'psycopg-pool'"
        )
        return None

    # Create an async connection pool (better for long-running daemon)
    try:
        pool = AsyncConnectionPool(
            dsn,
            max_size=10,
            kwargs={
                "autocommit": True,
                "prepare_threshold": 0,
                "row_factory": dict_row,
            },
            open=False,  # Don't open connections yet
        )
        checkpointer = AsyncPostgresSaver(pool)

        logger.info("Using AsyncPostgresSaver with connection pool, DSN: %s", _mask_dsn(dsn))
        return (checkpointer, pool)
    except Exception as exc:
        logger.warning("Failed to initialize AsyncPostgresSaver: %s", exc)
        return None


def _mask_dsn(dsn: str) -> str:
    """Mask password in DSN for logging."""
    import re

    return re.sub(r"://([^:]+):([^@]+)@", r"://\1:****@", dsn)
