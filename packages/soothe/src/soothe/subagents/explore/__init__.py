"""Explore subagent package (RFC-613).

Provides targeted filesystem search using LLM-orchestrated iterative tool selection.
"""

from typing import Any

from soothe_sdk.plugin import plugin, subagent

from .implementation import create_explore_subagent
from .schemas import ExploreResult, ExploreState, ExploreSubagentConfig, MatchEntry

__all__ = [
    # Schemas
    "ExploreResult",
    "ExploreSubagentConfig",
    "ExploreState",
    "MatchEntry",
    # Plugin
    "ExplorePlugin",
    # Factory
    "create_explore_subagent",
]


@plugin(
    name="explore",
    version="1.0.0",
    description="Targeted filesystem search agent",
    trust_level="built-in",
)
class ExplorePlugin:
    """Explore subagent plugin."""

    def __init__(self) -> None:
        """Initialize the plugin."""
        self._subagent: Any = None

    async def on_load(self, context: Any) -> None:
        """Initialize explore subagent.

        Args:
            context: Plugin context with config and logger.
        """
        context.logger.info("Loaded explore subagent v1.0.0")

    @subagent(
        name="explore",
        description=(
            "Targeted filesystem search agent. Uses iterative LLM-orchestrated "
            "search with configurable thoroughness. "
            "Use for: finding modules, locating patterns, navigating codebase. "
            "DO NOT use for: simple file reads (read_file), file edits. "
            "Inputs: `target` (required), `thoroughness` (optional: 'quick', 'medium', 'thorough'). "
            "Returns matches with paths, descriptions, and optional content snippets."
        ),
        model="openai:gpt-4o-mini",
        triggers=["find", "locate", "search for", "where is", "look for"],
    )
    async def create_subagent(
        self,
        model: Any,
        config: Any,
        context: Any,
    ) -> Any:
        """Create explore subagent.

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
        return create_explore_subagent(model, config, context_dict)
