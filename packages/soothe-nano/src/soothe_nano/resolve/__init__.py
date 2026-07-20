"""Protocol, subagent, and tool resolution logic for create_nano_agent.

Protocol resolution (memory, planner, policy) lives here.
Tool/subagent resolution is in ``_resolver_tools.py`` and infrastructure
(durability, checkpointer) in ``_resolver_infra.py``.  All public names
are re-exported here for convenience.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from soothe_nano.config import SootheConfig

from ._resolver_infra import resolve_checkpointer, resolve_durability
from ._resolver_tools import (
    SUBAGENT_FACTORIES,
    resolve_subagents,
    resolve_tools,
)

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel
    from soothe_sdk.protocols.memory import MemoryProtocol
    from soothe_sdk.protocols.planner import PlannerProtocol
    from soothe_sdk.protocols.policy import PolicyProtocol

logger = logging.getLogger(__name__)

__all__ = [
    "SUBAGENT_FACTORIES",
    "resolve_checkpointer",
    "resolve_durability",
    "resolve_memory",
    "resolve_planner",
    "resolve_policy",
    "resolve_subagents",
    "resolve_tools",
]


# ---------------------------------------------------------------------------
# Protocol resolution (memory, planner, policy)
# ---------------------------------------------------------------------------


def _create_loop_phase_model(
    config: SootheConfig,
    role: str,
    *,
    fallback: BaseChatModel | None,
    phase: str,
) -> BaseChatModel | None:
    """Resolve a loop-phase chat model from router role."""
    try:
        return config.create_chat_model(role)
    except Exception:
        logger.warning(
            "Failed to create %s model for role=%s; falling back to planner model",
            phase,
            role,
            exc_info=True,
        )
        return fallback


def resolve_memory(config: SootheConfig) -> MemoryProtocol | None:
    """Instantiate the MemoryProtocol implementation using MemU.

    Args:
        config: Soothe configuration.

    Returns:
        A MemoryProtocol instance, or None if disabled.
    """
    if not config.agent.protocols.memory.enabled:
        return None

    try:
        from soothe_nano.backends.memory.memu_adapter import MemUMemory

        logger.info(
            "Using MemU memory backend (chat: %s, embed: %s)",
            config.resolve_model(config.agent.protocols.memory.llm_chat_role),
            config.resolve_model(config.agent.protocols.memory.llm_embed_role),
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
) -> PlannerProtocol | None:
    """Resolve planner protocol for Coding CoreAgent.

    ``LLMPlanner`` lives in full ``soothe``. Inject via ``AgentBuilder.build(planner=...)``.
    """
    del config, model
    return None


def resolve_policy(config: SootheConfig) -> PolicyProtocol | None:
    """Instantiate the PolicyProtocol implementation from config.

    Args:
        config: Soothe configuration.

    Returns:
        A PolicyProtocol instance.
    """
    from soothe_nano.security import ConfigDrivenPolicy

    return ConfigDrivenPolicy(config=config)
