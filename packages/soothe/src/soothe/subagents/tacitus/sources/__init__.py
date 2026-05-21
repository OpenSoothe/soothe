"""Public-domain information sources for Tacitus."""

from .academic import AcademicSearchSource
from .url_crawl import UrlCrawlSource
from .web_search import WebSearchSource

__all__ = [
    "AcademicSearchSource",
    "UrlCrawlSource",
    "WebSearchSource",
]
