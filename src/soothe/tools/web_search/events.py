"""Web search tool events.

This module defines events for the websearch tool.
Events are self-registered at module load time.
"""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict

from soothe.core.base_events import ToolEvent


class WebsearchSearchStartedEvent(ToolEvent):
    """Websearch search started event."""

    type: Literal["soothe.tool.websearch.search_started"] = "soothe.tool.websearch.search_started"
    tool: str = "search_web"
    query: str = ""

    model_config = ConfigDict(extra="allow")


class WebsearchSearchCompletedEvent(ToolEvent):
    """Websearch search completed event."""

    type: Literal["soothe.tool.websearch.search_completed"] = "soothe.tool.websearch.search_completed"
    tool: str = "search_web"
    result_count: int = 0
    query: str = ""

    model_config = ConfigDict(extra="allow")


class WebsearchSearchFailedEvent(ToolEvent):
    """Websearch search failed event."""

    type: Literal["soothe.tool.websearch.search_failed"] = "soothe.tool.websearch.search_failed"
    tool: str = "search_web"
    error: str = ""
    query: str = ""

    model_config = ConfigDict(extra="allow")


class WebsearchCrawlStartedEvent(ToolEvent):
    """Websearch crawl started event."""

    type: Literal["soothe.tool.websearch.crawl_started"] = "soothe.tool.websearch.crawl_started"
    tool: str = "crawl_web"
    url: str = ""

    model_config = ConfigDict(extra="allow")


class WebsearchCrawlCompletedEvent(ToolEvent):
    """Websearch crawl completed event."""

    type: Literal["soothe.tool.websearch.crawl_completed"] = "soothe.tool.websearch.crawl_completed"
    tool: str = "crawl_web"
    content_length: int = 0
    url: str = ""

    model_config = ConfigDict(extra="allow")


class WebsearchCrawlFailedEvent(ToolEvent):
    """Websearch crawl failed event."""

    type: Literal["soothe.tool.websearch.crawl_failed"] = "soothe.tool.websearch.crawl_failed"
    tool: str = "crawl_web"
    error: str = ""
    url: str = ""

    model_config = ConfigDict(extra="allow")


# Register all websearch events with the global registry
from soothe.core.event_catalog import register_event  # noqa: E402

register_event(WebsearchSearchStartedEvent, summary_template="Searching: {query}")
register_event(WebsearchSearchCompletedEvent, summary_template="Found {result_count} results")
register_event(WebsearchSearchFailedEvent, summary_template="Search failed: {error}")
register_event(WebsearchCrawlStartedEvent, summary_template="Crawling: {url}")
register_event(
    WebsearchCrawlCompletedEvent,
    summary_template="Crawl complete: {content_length} bytes",
)
register_event(WebsearchCrawlFailedEvent, summary_template="Crawl failed: {error}")

# Event type constants for convenient imports
TOOL_WEBSEARCH_SEARCH_STARTED = "soothe.tool.websearch.search_started"
TOOL_WEBSEARCH_SEARCH_COMPLETED = "soothe.tool.websearch.search_completed"
TOOL_WEBSEARCH_SEARCH_FAILED = "soothe.tool.websearch.search_failed"
TOOL_WEBSEARCH_CRAWL_STARTED = "soothe.tool.websearch.crawl_started"
TOOL_WEBSEARCH_CRAWL_COMPLETED = "soothe.tool.websearch.crawl_completed"
TOOL_WEBSEARCH_CRAWL_FAILED = "soothe.tool.websearch.crawl_failed"

__all__ = [
    "TOOL_WEBSEARCH_CRAWL_COMPLETED",
    "TOOL_WEBSEARCH_CRAWL_FAILED",
    "TOOL_WEBSEARCH_CRAWL_STARTED",
    "TOOL_WEBSEARCH_SEARCH_COMPLETED",
    "TOOL_WEBSEARCH_SEARCH_FAILED",
    "TOOL_WEBSEARCH_SEARCH_STARTED",
    "WebsearchCrawlCompletedEvent",
    "WebsearchCrawlFailedEvent",
    "WebsearchCrawlStartedEvent",
    "WebsearchSearchCompletedEvent",
    "WebsearchSearchFailedEvent",
    "WebsearchSearchStartedEvent",
]
