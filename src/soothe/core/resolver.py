"""Protocol, subagent, and tool resolution logic for create_soothe_agent.

Protocol resolution (context, memory, planner, policy) lives here.
Tool/subagent resolution is in ``_resolver_tools.py`` and infrastructure
(durability, checkpointer) in ``_resolver_infra.py``.  All public names
are re-exported for backward compatibility.
"""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from soothe.config import SOOTHE_HOME, SootheConfig

# Re-export tool/subagent resolution (backward compat for agent.py, cli/main.py)
from soothe.core._resolver_infra import resolve_checkpointer, resolve_durability
from soothe.core._resolver_tools import (
    SUBAGENT_FACTORIES,
    resolve_goal_engine,
    resolve_goal_tools,
    resolve_subagents,
    resolve_tools,
)

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from soothe.protocols.context import ContextProtocol
    from soothe.protocols.memory import MemoryProtocol
    from soothe.protocols.planner import PlannerProtocol
    from soothe.protocols.policy import PolicyProtocol

logger = logging.getLogger(__name__)

__all__ = [
    "SUBAGENT_FACTORIES",
    "resolve_checkpointer",
    "resolve_context",
    "resolve_durability",
    "resolve_goal_engine",
    "resolve_goal_tools",
    "resolve_memory",
    "resolve_planner",
    "resolve_policy",
    "resolve_subagents",
    "resolve_tools",
]


# ---------------------------------------------------------------------------
# Protocol resolution (context, memory, planner, policy)
# ---------------------------------------------------------------------------


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

    parts = config.protocols.context.backend.split("-")
    if len(parts) != 2:  # noqa: PLR2004
        logger.warning(
            "Invalid context backend '%s', expected format: {behavior}-{storage}",
            config.protocols.context.backend,
        )
        return None

    behavior, storage = parts

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

    from soothe.backends.context.keyword import KeywordContext
    from soothe.backends.persistence import create_persist_store

    persist_dir = config.protocols.context.persist_dir or str(Path(SOOTHE_HOME) / "context" / "data")

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

    parts = config.protocols.memory.backend.split("-")
    if len(parts) != 2:  # noqa: PLR2004
        logger.warning(
            "Invalid memory backend '%s', expected format: {behavior}-{storage}",
            config.protocols.memory.backend,
        )
        return None

    behavior, storage = parts

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

    from soothe.backends.memory.keyword import KeywordMemory
    from soothe.backends.persistence import create_persist_store

    persist_dir = config.protocols.memory.persist_dir or str(Path(SOOTHE_HOME) / "memory" / "data")

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
