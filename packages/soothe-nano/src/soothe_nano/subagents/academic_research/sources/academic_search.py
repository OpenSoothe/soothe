"""Academic paper search via DeepXiv."""

from __future__ import annotations

import logging
import re
import threading
from typing import Any

from soothe_nano.subagents.academic_research.json_util import compact_search_query
from soothe_nano.subagents.academic_research.protocol import GatherContext, SourceResult
from soothe_nano.toolkits.deepxiv import resolve_deepxiv_token
from soothe_nano.toolkits.url_crawl.polite_http import (
    DomainRateLimiter,
    PoliteHTTPClient,
    RateLimit,
    RateLimitConfig,
)

logger = logging.getLogger(__name__)

_ARXIV_URL = re.compile(
    r"https?://(?:arxiv\.org/abs/|arxiv\.org/pdf/)(\d{4}\.\d{4,5}(?:v\d+)?)",
    re.IGNORECASE,
)

_DEEPXIV_AUTH_MARKERS = (
    "Invalid DeepXiv token",
    "Invalid or expired token",
    "DEEPXIV_API_KEY",
    "DEEPXIV_TOKEN",
)


def _is_deepxiv_auth_error(text: str) -> bool:
    return any(marker in text for marker in _DEEPXIV_AUTH_MARKERS)


class AcademicSearchSource:
    """Semantic academic search via DeepXiv toolkit."""

    def __init__(self, config: Any | None = None) -> None:
        self._config = config
        self._deepxiv_tool: Any | None = None
        self._tools_loaded = False
        self._load_lock = threading.Lock()
        self._auth_failed = False
        self._auth_failure_logged = False
        self._polite_client: PoliteHTTPClient | None = None

    def _ar_config(self) -> Any | None:
        if not self._config or not hasattr(self._config, "subagents"):
            return None
        sub = self._config.subagents.get("academic_research")
        return sub.config if sub and hasattr(sub, "config") else None

    def _get_polite_client(self) -> PoliteHTTPClient | None:
        if self._polite_client is not None:
            return self._polite_client
        cfg = self._ar_config()
        if not cfg or not getattr(cfg, "enable_polite_concurrency", True):
            return None
        limits = {
            "deepxiv": RateLimit(
                rps=getattr(cfg, "polite_rate_limit_rps", 1.0),
                burst=getattr(cfg, "polite_burst_size", 3),
                concurrent=getattr(cfg, "polite_max_concurrent", 5),
            )
        }
        rate_limiter = DomainRateLimiter(config=RateLimitConfig(limits=limits))
        self._polite_client = PoliteHTTPClient(
            rate_limiter=rate_limiter,
            max_retries=getattr(cfg, "polite_retry_max", 3),
            base_delay=getattr(cfg, "polite_retry_base_delay", 1.0),
            enable_circuit_breaker=True,
            circuit_breaker_threshold=getattr(cfg, "polite_circuit_breaker_threshold", 5),
            circuit_breaker_reset_sec=getattr(cfg, "polite_circuit_breaker_reset_sec", 60.0),
        )
        return self._polite_client

    def _ensure_tools(self) -> None:
        with self._load_lock:
            if self._tools_loaded:
                return
            self._tools_loaded = True
            try:
                from soothe_nano.toolkits.deepxiv import DeepxivToolkit

                token: str | None = None
                timeout = 60
                max_retries = 3
                if self._config and hasattr(self._config, "tools"):
                    dx = getattr(self._config.tools, "deepxiv", None)
                    if dx:
                        token = getattr(dx, "token", None)
                        timeout = getattr(dx, "timeout", 60)
                        max_retries = getattr(dx, "max_retries", 3)
                toolkit = DeepxivToolkit(
                    token=resolve_deepxiv_token(token),
                    timeout=timeout,
                    max_retries=max_retries,
                )
                for tool in toolkit.get_tools():
                    if getattr(tool, "name", "") == "deepxiv_search":
                        self._deepxiv_tool = tool
                        break
            except Exception:
                logger.debug("[academic_research] DeepXiv toolkit unavailable", exc_info=True)

    def _note_auth_failure(self, search_q: str) -> None:
        self._auth_failed = True
        if not self._auth_failure_logged:
            self._auth_failure_logged = True
            logger.warning(
                "[academic_research] DeepXiv authentication failed; skipping further searches. "
                "Set DEEPXIV_API_KEY or DEEPXIV_TOKEN."
            )
        else:
            logger.info("[academic_research] query=%r skipped (auth failed)", search_q)

    @property
    def name(self) -> str:
        return "academic_search"

    @property
    def source_type(self) -> str:
        return "academic"

    async def query(self, query: str, context: GatherContext) -> list[SourceResult]:
        _ = context
        search_q = compact_search_query(query, max_len=200)
        if self._auth_failed:
            return []
        self._ensure_tools()
        if not self._deepxiv_tool:
            return []

        polite_client = self._get_polite_client()

        async def _execute_search() -> str:
            if polite_client is not None:
                await polite_client.rate_limiter.acquire("deepxiv")
                try:
                    result = await self._deepxiv_tool._arun(query=search_q, size=5)
                    return str(result) if result is not None else ""
                finally:
                    polite_client.rate_limiter.release("deepxiv")
            result = await self._deepxiv_tool._arun(query=search_q, size=5)
            return str(result) if result is not None else ""

        try:
            text = await _execute_search()
            if text.startswith("Error"):
                if _is_deepxiv_auth_error(text):
                    self._note_auth_failure(search_q)
                return []
            if not text or text.startswith("No papers found"):
                return []
            url_match = _ARXIV_URL.search(text)
            paper_url = url_match.group(0) if url_match else None
            if not paper_url:
                id_match = re.search(r"\b(\d{4}\.\d{4,5}(?:v\d+)?)\b", text)
                if id_match:
                    paper_url = f"https://arxiv.org/abs/{id_match.group(1)}"
            return [
                SourceResult(
                    content=text[:4000],
                    source_ref=paper_url or "deepxiv",
                    source_name="academic_search",
                    metadata={"url": paper_url, "query": search_q, "sub_source": "deepxiv"},
                )
            ]
        except Exception as exc:
            if _is_deepxiv_auth_error(str(exc)):
                self._note_auth_failure(search_q)
            else:
                logger.debug("[academic_research] search failed", exc_info=True)
        return []
