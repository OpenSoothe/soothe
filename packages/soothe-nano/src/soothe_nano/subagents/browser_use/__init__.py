"""Browser automation subagent package.

This package provides browser automation capabilities using browser-use library.
"""

from __future__ import annotations

from typing import Any

from soothe_sdk.plugin import plugin, subagent

from . import events as _events  # noqa: F401 — register soothe.subagent.browser_use.* wire types
from .implementation import (
    _build_browser_use_graph,  # noqa: F401 - needed for tests
    create_browser_use_subagent,
)

__all__ = ["BrowserUsePlugin", "create_browser_use_subagent"]


@plugin(
    name="browser_use",
    version="1.0.0",
    description="Browser automation using browser-use library",
    trust_level="built-in",
)
class BrowserUsePlugin:
    """Browser automation plugin.

    Provides browser_use subagent for web navigation and interaction.
    """

    async def on_load(self, context: Any) -> None:
        """Verify browser-use is available."""
        try:
            import browser_use  # noqa: F401
        except ImportError as e:
            from soothe_sdk.core.exceptions import PluginError

            raise PluginError(
                "browser-use library not installed. Install with: pip install -U soothe",
                plugin_name="browser_use",
            ) from e

        context.logger.info("BrowserUse plugin loaded")

    @subagent(
        name="browser_use",
        description=(
            "Browser automation specialist for web tasks. Can navigate pages, click "
            "elements, fill forms, extract content, and take screenshots. Use for "
            "web scraping, form automation, and browser-based testing."
        ),
        system_context="""<BROWSER_CONTEXT>
<NAVIGATION_RULES>
Always verify URLs before navigation to prevent security issues.
Check for HTTPS when handling sensitive data (logins, payments).
Handle JavaScript-heavy pages with patience - wait for dynamic content.
Detect and handle CAPTCHAs, authentication prompts, and interactive elements.
</NAVIGATION_RULES>
<OUTPUT_INTERPRETATION>
Browser results include page states, DOM snapshots, and screenshots.
URLs in results show navigation history and current page location.
Status indicators show success/failure of navigation actions.
Screenshots capture visual state for verification.
</OUTPUT_INTERPRETATION>
<BEST_PRACTICES>
Use specific selectors (CSS, XPath) for reliable element interaction.
Implement retry logic for transient failures.
Capture screenshots at key navigation points for debugging.
</BEST_PRACTICES>
</BROWSER_CONTEXT>""",
        triggers=["WORKSPACE", "BROWSER_CONTEXT"],
    )
    async def create_browser_use(
        self,
        model: Any = None,  # noqa: ARG002
        config: Any = None,
        context: Any = None,  # noqa: ARG002
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Create browser_use automation subagent.

        Args:
            model: Unused; kept for ``@subagent`` factory wrapper compatibility.
            config: Soothe configuration (router + ``subagents.browser_use.model_role``).
            context: Plugin context.
            **kwargs: Additional browser config (headless, max_steps, etc.).

        Returns:
            Subagent dict with name, description, and runnable.
        """
        from soothe_nano.subagents.browser_use.config_model import BrowserUseSubagentConfig

        browser_config = None
        if hasattr(config, "subagents") and "browser_use" in config.subagents:
            subagent_config = config.subagents["browser_use"]
            if subagent_config.enabled and subagent_config.config:
                browser_config = BrowserUseSubagentConfig(**subagent_config.config)

        headless = kwargs.get("headless", True)
        browser_cfg = kwargs.get("config")
        if not isinstance(browser_cfg, BrowserUseSubagentConfig):
            browser_cfg = (
                browser_config
                if isinstance(browser_config, BrowserUseSubagentConfig)
                else BrowserUseSubagentConfig()
            )
        max_steps = kwargs.get("max_steps", browser_cfg.max_steps)
        use_vision = kwargs.get("use_vision", True)

        return create_browser_use_subagent(
            headless=headless,
            max_steps=max_steps,
            use_vision=use_vision,
            config=browser_config,
            soothe_config=config,
        )

    def get_subagents(self) -> list[Any]:
        """Get list of subagent factory functions."""
        return [self.create_browser_use]
