"""Public URL content extraction via wizsearch crawl."""

from __future__ import annotations

import logging
import re
from typing import Any

from soothe.subagents.tacitus.polite_http import PoliteHTTPClient, RateLimitConfig
from soothe.subagents.tacitus.protocol import CapabilityId, GatherContext, SourceResult, SourceType

logger = logging.getLogger(__name__)

_CAPABILITY_DESCRIPTION = (
    "Read and extract the main text content from a specific public HTTP or HTTPS URL."
)

_URL_PATTERN = re.compile(r"https?://[^\s\])>\"']+")


class UrlCrawlSource:
    """Headless page crawl for explicit URLs (WizsearchCrawlTool) with polite rate limiting."""

    capability_id: CapabilityId = "url_crawl"
    capability_description: str = _CAPABILITY_DESCRIPTION

    def __init__(self, config: Any | None = None) -> None:
        self._config = config or {}
        self._crawl_tool: Any | None = None
        self._polite_client: PoliteHTTPClient | None = None

    def _ensure_tool(self) -> None:
        if self._crawl_tool is not None:
            return
        try:
            from soothe.toolkits.wizsearch import WizsearchCrawlTool

            self._crawl_tool = WizsearchCrawlTool(config={})
        except ImportError:
            logger.debug("WizsearchCrawlTool not available", exc_info=True)

    def _get_polite_client(self) -> PoliteHTTPClient:
        """Get or create polite HTTP client with config-based rate limiting."""
        if self._polite_client is None:
            # Extract polite config from source config
            polite_config = self._config.get("polite", {})

            # Build rate limit config with domain overrides
            rate_limit_config = RateLimitConfig()
            domain_overrides = polite_config.get("domain_overrides", {})
            for domain, settings in domain_overrides.items():
                from soothe.subagents.tacitus.polite_http import RateLimit

                rate_limit_config.limits[domain] = RateLimit(
                    rps=settings.get("rps", 1.0),
                    burst=settings.get("burst", 3),
                    concurrent=settings.get("concurrent", 5),
                )

            self._polite_client = PoliteHTTPClient(
                rate_limiter=None,  # Will create default with our config
                max_retries=polite_config.get("retry_max", 3),
                base_delay=polite_config.get("retry_base_delay", 1.0),
                enable_circuit_breaker=polite_config.get("enable_circuit_breaker", True),
                circuit_breaker_threshold=polite_config.get("circuit_breaker_threshold", 5),
                circuit_breaker_reset_sec=polite_config.get("circuit_breaker_reset_sec", 60.0),
            )
            # Apply the rate limit config
            self._polite_client.rate_limiter = PoliteHTTPClient().rate_limiter
            self._polite_client.rate_limiter.config = rate_limit_config

        return self._polite_client

    @property
    def name(self) -> str:
        return "url_crawl"

    @property
    def source_type(self) -> SourceType:
        return "url"

    async def query(self, query: str, context: GatherContext) -> list[SourceResult]:
        _ = context
        self._ensure_tool()
        if not self._crawl_tool:
            return []

        urls = _URL_PATTERN.findall(query)
        if not urls:
            return []

        # Get polite client for rate limiting
        polite_client = self._get_polite_client()

        results: list[SourceResult] = []
        for url in urls[:2]:
            try:
                # Use polite client to wrap the crawl with rate limiting
                raw = await polite_client.request(
                    method="GET",
                    url=url,
                    request_func=self._crawl_with_timeout,
                )
                if raw and isinstance(raw, str) and not raw.startswith("Error"):
                    results.append(
                        SourceResult(
                            content=raw[:5000],
                            source_ref=url,
                            source_name="url_crawl",
                            metadata={"url": url},
                        )
                    )
            except Exception:
                logger.debug("URL crawl failed for: %s", url, exc_info=True)
        return results

    async def _crawl_with_timeout(self, method: str, url: str, **kwargs) -> str:
        """Wrap crawl tool call for polite client compatibility."""
        # method and kwargs are ignored - they're part of the polite client interface
        _ = method
        _ = kwargs
        if self._crawl_tool is None:
            raise RuntimeError("Crawl tool not initialized")
        return await self._crawl_tool._arun(url=url)
