"""Skillify plugin for skill warehouse retrieval.

This plugin provides a skillify subagent for retrieving and applying skills.
"""

from typing import Any

from soothe.subagents.skillify import create_skillify_subagent
from soothe_sdk import plugin, subagent


@plugin(
    name="skillify",
    version="1.0.0",
    description="Skill warehouse retrieval and application",
    trust_level="built-in",
)
class SkillifyPlugin:
    """Skillify plugin.

    Provides skillify subagent for discovering and applying skills from skill warehouses.
    """

    async def on_load(self, context: Any) -> None:
        """Initialize skillify plugin.

        Args:
            context: Plugin context.
        """
        context.logger.info("Skillify plugin loaded")

    @subagent(
        name="skillify",
        description=(
            "Skill retrieval specialist. Searches skill warehouses to find "
            "and apply relevant skills and capabilities from the community."
        ),
        model="openai:gpt-4o-mini",
    )
    async def create_skillify(
        self,
        model: Any,
        config: Any,
        context: Any,  # noqa: ARG002
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Create skillify subagent.

        Args:
            model: Resolved model (BaseChatModel or string).
            config: Soothe configuration.
            context: Plugin context.
            **kwargs: Additional skillify config.

        Returns:
            Subagent dict with name, description, and runnable.
        """
        # Create subagent using existing factory
        runnable = create_skillify_subagent(
            _model=model,
            config=config,
            **kwargs,
        )

        return {
            "name": "skillify",
            "description": (
                "Skill retrieval specialist. Searches skill warehouses to find "
                "and apply relevant skills and capabilities from the community."
            ),
            "runnable": runnable,
        }

    def get_subagents(self) -> list[Any]:
        """Get list of subagent factory functions.

        Returns:
            List containing the create_skillify method.
        """
        return [self.create_skillify]
