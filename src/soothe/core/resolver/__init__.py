"""Protocol, subagent, and tool resolution logic for create_soothe_agent.

Protocol resolution (memory, planner, policy) lives here.
Tool/subagent resolution is in ``_resolver_tools.py`` and infrastructure
(durability, checkpointer) in ``_resolver_infra.py``.  All public names
are re-exported for backward compatibility.
"""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from soothe.config import SootheConfig
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

    from soothe.protocols.memory import MemoryProtocol
    from soothe.protocols.planner import PlannerProtocol
    from soothe.protocols.policy import PolicyProtocol

logger = logging.getLogger(__name__)

__all__ = [
    "SUBAGENT_FACTORIES",
    "resolve_checkpointer",
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
    simple = SimplePlanner(model=simple_planner_model, config=config) if simple_planner_model else None

    if config.protocols.planner.routing == "always_direct":
        return simple or SimplePlanner(model=planner_model, config=config)

    # Check if we're running inside Claude Code (nested session not allowed)
    import os

    inside_claude_code = os.environ.get("CLAUDECODE") is not None

    claude_planner = None
    # Check if claude subagent is enabled in config before creating ClaudePlanner
    claude_enabled = config.subagents.get("claude", None)
    if claude_enabled is not None and not claude_enabled.enabled:
        logger.info("Claude subagent disabled in config, skipping ClaudePlanner")
    elif not inside_claude_code:
        try:
            from soothe.cognition.planning.claude import ClaudePlanner

            claude_planner = ClaudePlanner(cwd=resolved_cwd, reflection_model=planner_model, config=config)
        except Exception:
            logger.info("Claude CLI not available for planning")
    else:
        logger.info("Running inside Claude Code, skipping ClaudePlanner (nested session not allowed)")

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
    from soothe.core.config_driven import ConfigDrivenPolicy

    return ConfigDrivenPolicy(config=config)
