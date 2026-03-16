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
        except Exception:
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
    if name == "wizsearch":
        from soothe.tools.wizsearch import create_wizsearch_tools

        return list(create_wizsearch_tools())
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

    return GoalEngine(max_retries=config.autonomous_max_retries)


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
) -> list[SubAgent | CompiledSubAgent]:
    """Build subagent specs from config.

    Args:
        config: Soothe configuration.
        default_model: Pre-configured model instance to use as default.

    Returns:
        List of subagent specs for deepagents.
    """
    cwd_subagents = {"planner", "scout", "claude"}
    string_model_subagents = {"claude"}
    resolved_cwd = str(Path(config.workspace_dir).resolve()) if config.workspace_dir else str(Path.cwd())

    subagents: list[SubAgent | CompiledSubAgent] = []
    for name, sub_cfg in config.subagents.items():
        if not sub_cfg.enabled:
            continue
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
    if config.context_backend == "none":
        return None

    if config.context_backend == "vector" and config.vector_store_provider != "none":
        try:
            from soothe.backends.context.vector import VectorContext
            from soothe.backends.vector_store import create_vector_store

            vs = create_vector_store(
                config.vector_store_provider,
                f"{config.vector_store_collection}_context",
                config.vector_store_config,
            )
            embeddings = config.create_embedding_model()
            return VectorContext(vector_store=vs, embeddings=embeddings)
        except Exception:
            logger.warning("Vector context init failed, falling back to keyword", exc_info=True)
    elif config.context_backend == "vector":
        logger.warning("vector context requires vector_store_provider; falling back to keyword")

    from pathlib import Path

    from soothe.backends.context.keyword import KeywordContext

    persist_dir = config.context_persist_dir or str(Path(SOOTHE_HOME) / "context")
    return KeywordContext(
        persist_dir=persist_dir,
        persist_backend=config.context_persist_backend,
    )


def resolve_memory(config: SootheConfig) -> MemoryProtocol | None:
    """Instantiate the MemoryProtocol implementation from config.

    Falls back to keyword backend when vector initialisation fails.

    Args:
        config: Soothe configuration.

    Returns:
        A MemoryProtocol instance, or None if disabled.
    """
    if config.memory_backend == "none":
        return None

    if config.memory_backend == "vector" and config.vector_store_provider != "none":
        try:
            from soothe.backends.memory.vector import VectorMemory
            from soothe.backends.vector_store import create_vector_store

            vs = create_vector_store(
                config.vector_store_provider,
                f"{config.vector_store_collection}_memory",
                config.vector_store_config,
            )
            embeddings = config.create_embedding_model()
            return VectorMemory(vector_store=vs, embeddings=embeddings)
        except Exception:
            logger.warning("Vector memory init failed, falling back to keyword", exc_info=True)
    elif config.memory_backend == "vector":
        logger.warning("vector memory requires vector_store_provider; falling back to keyword")

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

    if config.planner_routing == "always_direct":
        return direct or DirectPlanner(model=planner_model)

    subagent_planner = None
    try:
        from soothe.backends.planning.subagent import SubagentPlanner

        subagent_planner = SubagentPlanner(model=planner_model, cwd=resolved_cwd)
    except Exception:
        logger.debug("SubagentPlanner init failed", exc_info=True)

    if config.planner_routing == "always_planner":
        return subagent_planner or direct  # type: ignore[return-value]

    claude_planner = None
    try:
        from soothe.backends.planning.claude import ClaudePlanner

        claude_planner = ClaudePlanner(cwd=resolved_cwd)
    except Exception:
        logger.info("Claude CLI not available for planning")

    if config.planner_routing == "always_claude":
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
    """Instantiate the DurabilityProtocol implementation from config."""
    if config.durability_backend == "langgraph":
        from pathlib import Path

        from soothe.backends.durability.langgraph import LangGraphDurability

        metadata_path = config.durability_metadata_path or str(Path(SOOTHE_HOME) / "durability" / "threads.json")
        return LangGraphDurability(metadata_path=metadata_path)

    from soothe.backends.durability.in_memory import InMemoryDurability

    return InMemoryDurability()


def resolve_checkpointer(config: SootheConfig) -> Checkpointer:
    """Resolve a LangGraph checkpointer from config.

    Falls back to ``MemorySaver`` when an optional backend dependency is
    unavailable or misconfigured.
    """
    from langgraph.checkpoint.memory import MemorySaver

    backend = config.checkpointer_backend
    if backend == "memory":
        return MemorySaver()

    if backend == "sqlite":
        return _resolve_sqlite_checkpointer(config) or MemorySaver()

    if backend == "postgres":
        return _resolve_postgres_checkpointer(config) or MemorySaver()

    logger.warning("Unknown checkpointer backend '%s'; using memory saver", backend)
    return MemorySaver()


def _resolve_sqlite_checkpointer(config: SootheConfig) -> Checkpointer | None:
    """Try to initialize a SQLite-based checkpointer."""
    from pathlib import Path

    sqlite_path = config.checkpointer_sqlite_path or str(Path(SOOTHE_HOME) / "checkpoints.sqlite")
    Path(sqlite_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)

    candidates = [
        ("langgraph.checkpoint.sqlite.aio", "AsyncSqliteSaver"),
        ("langgraph.checkpoint.sqlite", "SqliteSaver"),
    ]
    for module_name, class_name in candidates:
        try:
            module = __import__(module_name, fromlist=[class_name])
            saver_cls = getattr(module, class_name)
            if hasattr(saver_cls, "from_conn_string"):
                return saver_cls.from_conn_string(sqlite_path)
            return saver_cls(sqlite_path)
        except Exception:
            logger.debug("Failed to load %s.%s", module_name, class_name, exc_info=True)
            continue

    logger.warning(
        "SQLite checkpointer requested but sqlite checkpoint package is unavailable; "
        "install langgraph sqlite checkpoint support. Falling back to memory."
    )
    return None


def _resolve_postgres_checkpointer(config: SootheConfig) -> Checkpointer | None:
    """Try to initialize a Postgres-based checkpointer."""
    dsn = config.checkpointer_postgres_dsn
    if not dsn:
        logger.warning("Postgres checkpointer requested but checkpointer_postgres_dsn is not set; using memory.")
        return None

    candidates = [
        ("langgraph.checkpoint.postgres.aio", "AsyncPostgresSaver"),
        ("langgraph.checkpoint.postgres", "PostgresSaver"),
    ]
    for module_name, class_name in candidates:
        try:
            module = __import__(module_name, fromlist=[class_name])
            saver_cls = getattr(module, class_name)
            if hasattr(saver_cls, "from_conn_string"):
                return saver_cls.from_conn_string(dsn)
            return saver_cls(dsn)
        except Exception:
            logger.debug("Failed to load %s.%s", module_name, class_name, exc_info=True)
            continue

    logger.warning(
        "Postgres checkpointer requested but postgres checkpoint package is unavailable; "
        "install langgraph postgres checkpoint support. Falling back to memory."
    )
    return None
