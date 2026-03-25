"""Web search tool events."""

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


__all__ = [
    "WebsearchCrawlCompletedEvent",
    "WebsearchCrawlFailedEvent",
    "WebsearchCrawlStartedEvent",
    "WebsearchSearchCompletedEvent",
    "WebsearchSearchFailedEvent",
    "WebsearchSearchStartedEvent",
]
