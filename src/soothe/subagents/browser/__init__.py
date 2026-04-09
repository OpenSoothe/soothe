"""Browser automation subagent package.

This package provides browser automation capabilities using browser-use.
"""

from typing import Any

from soothe_sdk import plugin, subagent

from .implementation import (
    _build_browser_graph,  # noqa: F401 - needed for tests
    create_browser_subagent as _create_browser_subagent,
)

__all__ = ["BrowserPlugin", "create_browser_subagent"]


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
        system_context="""<BROWSER_CONTEXT>
<navigation_rules>
Always verify URLs before navigation to prevent security issues.
Check for HTTPS when handling sensitive data (logins, payments).
Handle JavaScript-heavy pages with patience - wait for dynamic content.
Detect and handle CAPTCHAs, authentication prompts, and interactive elements.
</navigation_rules>
<output_interpretation>
Browser results include page states, DOM snapshots, and screenshots.
URLs in results show navigation history and current page location.
Status indicators show success/failure of navigation actions.
Screenshots capture visual state for verification.
</output_interpretation>
<best_practices>
Use specific selectors (CSS, XPath) for reliable element interaction.
Implement retry logic for transient failures.
Capture screenshots at key navigation points for debugging.
</best_practices>
</BROWSER_CONTEXT>""",
        triggers=["WORKSPACE", "BROWSER_CONTEXT"],
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

        # Create subagent using internal factory
        runnable = _create_browser_subagent(
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


def create_browser_subagent(
    model: Any = None,
    *,
    headless: bool = True,
    max_steps: int = 100,
    use_vision: bool = True,
    config: Any = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Create a Browser subagent (CompiledSubAgent with browser-use workflow).

    Args:
        model: Model name string or langchain BaseChatModel for the browser-use
            LLM. If a BaseChatModel instance is passed, the model name is
            extracted automatically.
        headless: Run browser in headless mode.
        max_steps: Maximum browser agent steps.
        use_vision: Enable vision/screenshot support.
        config: Browser subagent configuration object with runtime directories,
            cleanup settings, and feature flags.
        **kwargs: Additional config -- `base_url` and `api_key` are forwarded
            to the browser-use LLM.

    Returns:
        `CompiledSubAgent` dict compatible with deepagents.
    """
    return _create_browser_subagent(
        model=model,
        headless=headless,
        max_steps=max_steps,
        use_vision=use_vision,
        config=config,
        **kwargs,
    )
