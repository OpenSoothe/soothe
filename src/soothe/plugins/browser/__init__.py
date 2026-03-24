"""Browser automation subagent plugin.

This plugin provides a browser automation subagent using browser-use.
"""

from typing import Any

from soothe.subagents.browser import create_browser_subagent
from soothe_sdk import plugin, subagent


@plugin(
    name="browser",
    version="1.0.0",
    description="Browser automation using browser-use",
    dependencies=["browser-use~=0.1.0"],
    trust_level="built-in",
)
class BrowserPlugin:
    """Browser automation plugin.

    Provides browser subagent for web navigation and interaction.
    """

    async def on_load(self, context: Any) -> None:
        """Verify browser-use is available.

        Args:
            context: Plugin context.

        Raises:
            PluginError: If browser-use library is not installed.
        """
        try:
            import browser_use  # noqa: F401
        except ImportError as e:
            from soothe.plugin.exceptions import PluginError

            raise PluginError(
                "browser-use library not installed. Install with: pip install soothe[browser]",
                plugin_name="browser",
            ) from e

        context.logger.info("Browser plugin loaded")

    @subagent(
        name="browser",
        description=(
            "Browser automation specialist for web tasks. Can navigate pages, click "
            "elements, fill forms, extract content, and take screenshots. Use for "
            "web scraping, form automation, and browser-based testing."
        ),
        model="openai:gpt-4o-mini",
    )
    async def create_browser(
        self,
        model: Any,
        config: Any,
        context: Any,  # noqa: ARG002
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Create browser automation subagent.

        Args:
            model: Resolved model (BaseChatModel or string).
            config: Soothe configuration.
            context: Plugin context.
            **kwargs: Additional browser config (headless, max_steps, etc.).

        Returns:
            Subagent dict with name, description, and runnable.
        """
        from soothe.config import BrowserSubagentConfig

        # Get browser config from subagent config
        browser_config = None
        if hasattr(config, "subagents") and "browser" in config.subagents:
            subagent_config = config.subagents["browser"]
            if subagent_config.enabled and subagent_config.config:
                browser_config = BrowserSubagentConfig(**subagent_config.config)

        # Extract common parameters
        headless = kwargs.get("headless", True)
        max_steps = kwargs.get("max_steps", 100)
        use_vision = kwargs.get("use_vision", True)

        # Create subagent using existing factory
        runnable = create_browser_subagent(
            model=model,
            headless=headless,
            max_steps=max_steps,
            use_vision=use_vision,
            config=browser_config,
        )

        return {
            "name": "browser",
            "description": (
                "Browser automation specialist for web tasks. Can navigate pages, click "
                "elements, fill forms, extract content, and take screenshots. Use for "
                "web scraping, form automation, and browser-based testing."
            ),
            "runnable": runnable,
        }

    def get_subagents(self) -> list[Any]:
        """Get list of subagent factory functions.

        Returns:
            List containing the create_browser method.
        """
        return [self.create_browser]
