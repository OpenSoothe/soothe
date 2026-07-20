"""Explorer subagent implementation (RFC-613).

Factory function for creating the explorer subagent.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from soothe_nano.config import SootheConfig, SubagentConfig

from .engine import build_explore_engine
from .recovery import ExploreRunnableRecoveryWrapper
from .schemas import ExploreSubagentConfig

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)


def create_explorer_subagent(
    model: BaseChatModel,
    config: SootheConfig,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Create explorer subagent.

    Args:
        model: LLM for search planning and result assessment.
        config: Soothe configuration.
        context: Context with work_dir and thoroughness settings.
            Note: work_dir is static from resolver (daemon workspace). Thread workspace
            is injected at runtime via state.workspace (IG-328).

    Returns:
        CompiledSubAgent dict with name, description, runnable.
    """
    # Resolver-provided workspace (fallback when state lacks workspace)
    resolver_work_dir = context.get("work_dir", "")
    subagent_config = config.subagents.get("explorer", SubagentConfig())
    explore_config = ExploreSubagentConfig(**subagent_config.config)

    # Use resolver workspace as initial default
    # Thread workspace will override at runtime via state.workspace (IG-328)
    initial_workspace = resolver_work_dir

    # Use fast model for synthesis (optimization: 3x faster structured output)
    try:
        synthesis_model = config.create_chat_model("fast")
        logger.debug("Using fast model for explorer synthesis")
    except Exception:
        synthesis_model = model
        logger.warning("Fast model not configured, using primary model for synthesis")

    graph = build_explore_engine(
        model,
        explore_config,
        initial_workspace,
        allow_paths_outside_workspace=config.security.allow_paths_outside_workspace,
        synthesis_model=synthesis_model,
        soothe_config=config,
    )
    runnable = ExploreRunnableRecoveryWrapper(
        graph,
        thoroughness=explore_config.thoroughness,
        max_matches=explore_config.max_matches_returned,
    )

    return {
        "name": "explorer",
        "description": (
            "Deep readonly code explorer. Uses iterative LLM-orchestrated "
            "search with configurable thoroughness (quick/medium/thorough). "
            "Use when goal mentions 'find', 'locate', 'search for', or requires "
            "navigating filesystem toward a specific target."
        ),
        "runnable": runnable,
    }
