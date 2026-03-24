"""Weaver plugin for generative agent framework.

This plugin provides a weaver subagent for generating specialized agents.
"""

from typing import Any

from soothe.subagents.weaver import create_weaver_subagent
from soothe_sdk import plugin, subagent


@plugin(
    name="weaver",
    version="1.0.0",
    description="Generative agent framework for creating specialized agents",
    trust_level="built-in",
)
class WeaverPlugin:
    """Weaver plugin.

    Provides weaver subagent for generating specialized agents on-demand.
    """

    async def on_load(self, context: Any) -> None:
        """Initialize weaver plugin.

        Args:
            context: Plugin context.
        """
        context.logger.info("Weaver plugin loaded")

    @subagent(
        name="weaver",
        description=(
            "Generative agent specialist. Creates specialized agents on-demand "
            "for specific tasks, with reuse-first matching for efficiency."
        ),
        model="openai:gpt-4o-mini",
    )
    async def create_weaver(
        self,
        model: Any,
        config: Any,
        context: Any,  # noqa: ARG002
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Create weaver subagent.

        Args:
            model: Resolved model (BaseChatModel or string).
            config: Soothe configuration.
            context: Plugin context.
            **kwargs: Additional weaver config.

        Returns:
            Subagent dict with name, description, and runnable.
        """
        # Create subagent using existing factory
        runnable = create_weaver_subagent(
            model=model,
            config=config,
            **kwargs,
        )

        return {
            "name": "weaver",
            "description": (
                "Generative agent specialist. Creates specialized agents on-demand "
                "for specific tasks, with reuse-first matching for efficiency."
            ),
            "runnable": runnable,
        }

    def get_subagents(self) -> list[Any]:
        """Get list of subagent factory functions.

        Returns:
            List containing the create_weaver method.
        """
        return [self.create_weaver]
