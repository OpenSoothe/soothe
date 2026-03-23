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
from soothe.utils import expand_path

from ._resolver_infra import resolve_checkpointer, resolve_durability
from ._resolver_tools import (
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

    # Only attempt vector backend if vector store role is configured
    if behavior == "vector":
        router_str = config.resolve_vector_store_role("context")
        if not router_str:
            logger.info(
                "Context backend is 'vector' but no vector store assigned for 'context' role; falling back to keyword"
            )
            behavior = "keyword"

    if behavior == "vector":
        try:
            from soothe.backends.context.vector import VectorContext

            vs = config.create_vector_store_for_role("context")
            embeddings = config.create_embedding_model()
            logger.info("Using vector context backend")
            return VectorContext(
                vector_store=vs,
                embeddings=embeddings,
                use_tiktoken=config.performance.thresholds.use_tiktoken,
            )
        except Exception:
            logger.warning("Vector context init failed, falling back to keyword", exc_info=True)

    # Keyword backend (default or fallback)
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
    return KeywordContext(
        persist_store=persist_store,
        use_tiktoken=config.performance.thresholds.use_tiktoken,
    )


def resolve_memory(config: SootheConfig) -> MemoryProtocol | None:
    """Instantiate the MemoryProtocol implementation using MemU.

    Args:
        config: Soothe configuration.

    Returns:
        A MemoryProtocol instance, or None if disabled.
    """
    if not config.protocols.memory.enabled:
        return None

    try:
        from soothe.backends.memory.memu_adapter import MemUMemory

        logger.info(
            "Using MemU memory backend (chat: %s, embed: %s)",
            config.resolve_model(config.protocols.memory.llm_chat_role),
            config.resolve_model(config.protocols.memory.llm_embed_role),
        )

        return MemUMemory(config)

    except ImportError:
        logger.exception("MemU memory backend requires dependencies")
        raise
    except Exception:
        logger.exception("Failed to initialize MemU memory backend")
        raise


def resolve_planner(
    config: SootheConfig,
    model: BaseChatModel | None,
) -> PlannerProtocol:
    """Instantiate the PlannerProtocol implementation from config.

    Always returns a planner -- at minimum SimplePlanner is used as fallback.

    Args:
        config: Soothe configuration.
        model: The resolved chat model.

    Returns:
        A PlannerProtocol instance.
    """
    planner_role = config.protocols.planner.planner_model or "think"
    planner_model = model
    if planner_model is None:
        try:
            planner_model = config.create_chat_model(planner_role)
        except Exception:
            try:
                planner_model = config.create_chat_model("default")
            except Exception:
                logger.warning("Failed to create model for planner")

    fast_model = None
    with contextlib.suppress(Exception):
        fast_model = config.create_chat_model("fast")

    resolved_cwd = str(expand_path(config.workspace_dir)) if config.workspace_dir else str(Path.cwd())

    from soothe.cognition.planning.simple import SimplePlanner

    # Use fast model for unified planning (structured output generation)
    simple_planner_model = fast_model or planner_model
    simple = SimplePlanner(model=simple_planner_model) if simple_planner_model else None

    if config.protocols.planner.routing == "always_direct":
        return simple or SimplePlanner(model=planner_model)

    claude_planner = None
    try:
        from soothe.cognition.planning.claude import ClaudePlanner

        claude_planner = ClaudePlanner(cwd=resolved_cwd, reflection_model=planner_model)
    except Exception:
        logger.info("Claude CLI not available for planning")

    if config.protocols.planner.routing == "always_claude":
        return claude_planner or simple  # type: ignore[return-value]

    from soothe.cognition.planning.router import AutoPlanner

    return AutoPlanner(
        claude=claude_planner,
        simple=simple,
        fast_model=fast_model,
        medium_token_threshold=30,
        complex_token_threshold=160,
        use_tiktoken=config.performance.thresholds.use_tiktoken,
    )


def resolve_policy(config: SootheConfig) -> PolicyProtocol | None:
    """Instantiate the PolicyProtocol implementation from config.

    Args:
        config: Soothe configuration.

    Returns:
        A PolicyProtocol instance.
    """
    from soothe.safety.config_driven import ConfigDrivenPolicy

    return ConfigDrivenPolicy(config=config)
