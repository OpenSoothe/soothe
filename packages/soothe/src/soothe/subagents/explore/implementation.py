"""Explore subagent implementation (RFC-613).

Factory function for creating the explore subagent.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from soothe.config import SootheConfig, SubagentConfig

from .engine import build_explore_engine
from .schemas import ExploreSubagentConfig

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)


def create_explore_subagent(
    model: BaseChatModel,
    config: SootheConfig,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Create explore subagent.

    Args:
        model: LLM for search planning and result assessment.
        config: Soothe configuration.
        context: Context with work_dir and thoroughness settings.

    Returns:
        CompiledSubAgent dict with name, description, runnable.
    """
    work_dir = context.get("work_dir", "")
    subagent_config = config.subagents.get("explore", SubagentConfig())
    explore_config = ExploreSubagentConfig(**subagent_config.config)
    workspace = work_dir  # Search boundary is workspace

    runnable = build_explore_engine(model, explore_config, workspace)

    return {
        "name": "explore",
        "description": (
            "Targeted filesystem search agent. Uses iterative LLM-orchestrated "
            "search with configurable thoroughness (quick/medium/thorough). "
            "Use when goal mentions 'find', 'locate', 'search for', or requires "
            "navigating filesystem toward a specific target."
        ),
        "runnable": runnable,
    }
