"""Protocol, subagent, and tool resolution logic for create_soothe_agent.

Protocol resolution (memory, planner, policy) lives here.
Tool/subagent resolution is in ``_resolver_tools.py`` and infrastructure
(durability, checkpointer) in ``_resolver_infra.py``.  All public names
are re-exported here for convenience.
"""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING

from soothe.config import SootheConfig

from ._resolver_infra import resolve_checkpointer, resolve_durability
from ._resolver_tools import (
    SUBAGENT_FACTORIES,
    resolve_goal_engine,
    resolve_subagents,
    resolve_tools,
)

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from soothe.protocols.memory import MemoryProtocol
    from soothe.protocols.planner import PlannerProtocol
    from soothe.protocols.policy import PolicyProtocol

logger = logging.getLogger(__name__)

__all__ = [
    "SUBAGENT_FACTORIES",
    "resolve_checkpointer",
    "resolve_durability",
    "resolve_goal_engine",
    "resolve_memory",
    "resolve_planner",
    "resolve_policy",
    "resolve_subagents",
    "resolve_tools",
]


# ---------------------------------------------------------------------------
# Protocol resolution (memory, planner, policy)
# ---------------------------------------------------------------------------


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
    """Instantiate LLMPlanner as the sole planner implementation.

    Args:
        config: Soothe configuration.
        model: The resolved chat model.

    Returns:
        LLMPlanner instance.
    """
    planner_role = config.protocols.planner.model or "think"
    planner_model = model
    if planner_model is None:
        try:
            planner_model = config.create_chat_model(planner_role)
        except Exception:
            try:
                planner_model = config.create_chat_model("default")
            except Exception:
                logger.warning("Failed to create model for planner")

    # Use fast model for planning (structured output generation)
    fast_model = None
    with contextlib.suppress(Exception):
        fast_model = config.create_chat_model("fast")

    planner_model = fast_model or planner_model

    from soothe.cognition.agent_loop.core.planner import LLMPlanner

    return LLMPlanner(model=planner_model, config=config)


def resolve_policy(config: SootheConfig) -> PolicyProtocol | None:
    """Instantiate the PolicyProtocol implementation from config.

    Args:
        config: Soothe configuration.

    Returns:
        A PolicyProtocol instance.
    """
    from soothe.core.persistence import ConfigDrivenPolicy

    return ConfigDrivenPolicy(config=config)
