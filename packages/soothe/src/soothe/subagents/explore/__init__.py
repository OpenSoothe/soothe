"""Explorer subagent package (RFC-613).

Provides targeted filesystem search using LLM-orchestrated iterative tool selection.
"""

from typing import Any

from soothe_sdk.plugin import plugin, subagent

from . import events as _events  # noqa: F401 — register soothe.subagent.explorer.* wire types
from .implementation import create_explorer_subagent
from .schemas import ExploreAgentState, ExploreResult, ExploreSubagentConfig, MatchEntry

__all__ = [
    # Schemas
    "ExploreAgentState",
    "ExploreResult",
    "ExploreSubagentConfig",
    "MatchEntry",
    # Plugin
    "ExplorerPlugin",
    # Factory
    "create_explorer_subagent",
]


@plugin(
    name="explorer",
    version="1.0.0",
    description="Deep readonly code explorer",
    trust_level="built-in",
)
class ExplorerPlugin:
    """Explorer subagent plugin."""

    def __init__(self) -> None:
        """Initialize the plugin."""
        self._subagent: Any = None

    async def on_load(self, context: Any) -> None:
        """Initialize explorer subagent.

        Args:
            context: Plugin context with config and logger.
        """
        context.logger.info("Loaded explorer subagent v1.0.0")

    @subagent(
        name="explorer",
        description=(
            "Deep readonly code explorer. Uses iterative LLM-orchestrated "
            "repository reconnaissance with configurable thoroughness. "
            "Use for: finding modules, locating patterns, navigating codebase. "
            "DO NOT use for: simple file reads (read_file), file edits. "
            "Inputs: `target` (required), `thoroughness` (optional: 'quick', 'medium', 'thorough'). "
            "Returns matches with paths, descriptions, and optional content snippets."
        ),
        triggers=["find", "locate", "search for", "where is", "look for"],
    )
    async def create_subagent(
        self,
        model: Any,
        config: Any,
        context: Any,
    ) -> Any:
        """Create explorer subagent.

        Args:
            model: LLM for search operations.
            config: Soothe configuration.
            context: Plugin context with work_dir and thoroughness.

        Returns:
            Compiled LangGraph subagent.
        """
        context_dict = {
            "work_dir": getattr(context, "work_dir", ""),
            "thoroughness": getattr(context, "thoroughness", "medium"),
        }
        return create_explorer_subagent(model, config, context_dict)
