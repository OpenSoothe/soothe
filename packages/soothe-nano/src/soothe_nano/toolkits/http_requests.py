"""HTTP client tools via LangChain Community RequestsToolkit (IG-339).

Wraps ``langchain_community.agent_toolkits.openapi.toolkit.RequestsToolkit`` with
Soothe configuration and safe defaults (disabled unless explicitly enabled).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langchain_core.tools import BaseTool
from soothe_sdk.plugin import plugin

if TYPE_CHECKING:
    from soothe_nano.config import SootheConfig

logger = logging.getLogger(__name__)


class HttpRequestsToolkit:
    """Build LangChain ``RequestsToolkit`` tools from Soothe config."""

    def __init__(self, *, config: SootheConfig | None = None) -> None:
        """Initialize with optional full Soothe config.

        Args:
            config: Loaded ``SootheConfig``; when None, returns no tools.
        """
        self._config = config

    def get_tools(self) -> list[BaseTool]:
        """Return HTTP verb tools, or an empty list when disabled or not opted in.

        Returns:
            Up to five LangChain request tools, or ``[]``.
        """
        if self._config is None:
            logger.debug("HttpRequestsToolkit: no Soothe config; skipping http_requests tools")
            return []

        hr = self._config.tools.http_requests
        if not hr.enabled:
            logger.debug("HttpRequestsToolkit: tools.http_requests.enabled is false")
            return []
        if not hr.allow_dangerous_requests:
            logger.warning(
                "HttpRequestsToolkit: tools.http_requests.allow_dangerous_requests is false; "
                "no HTTP tools will be registered. Set both enabled and "
                "allow_dangerous_requests to true to opt in (see IG-339)."
            )
            return []

        try:
            from langchain_community.agent_toolkits.openapi.toolkit import RequestsToolkit
            from langchain_community.utilities.requests import TextRequestsWrapper
        except ImportError as exc:
            logger.warning(
                "HttpRequestsToolkit: failed to import LangChain request toolkit (%s).",
                exc,
            )
            return []

        headers = hr.headers if hr.headers else None
        wrapper = TextRequestsWrapper(headers=headers, verify=hr.verify_ssl)
        toolkit = RequestsToolkit(
            requests_wrapper=wrapper,
            allow_dangerous_requests=True,
        )
        tools = toolkit.get_tools()
        logger.info("HttpRequestsToolkit: registered %d HTTP request tools", len(tools))
        return list(tools)


@plugin(
    name="http_requests",
    version="1.0.0",
    description="LangChain HTTP Requests toolkit (GET/POST/PATCH/PUT/DELETE)",
    trust_level="built-in",
)
class HttpRequestsPlugin:
    """Plugin providing LangChain Community HTTP request tools."""

    def __init__(self) -> None:
        """Initialize the plugin."""
        self._tools: list[BaseTool] = []

    async def on_load(self, context) -> None:
        """Load tools from ``soothe_config``."""
        soothe_config = getattr(context, "soothe_config", None)
        toolkit = HttpRequestsToolkit(config=soothe_config)
        self._tools = toolkit.get_tools()
        context.logger.info("Loaded %d http_requests tools", len(self._tools))

    def get_tools(self) -> list[BaseTool]:
        """Return tools loaded during ``on_load``."""
        return self._tools
