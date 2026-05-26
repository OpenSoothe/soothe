"""Academic paper search via DeepXiv."""

from __future__ import annotations

import logging
import re
import threading
from typing import TYPE_CHECKING, Any

from soothe.subagents.tacitus.json_util import compact_search_query
from soothe.subagents.tacitus.protocol import CapabilityId, GatherContext, SourceResult, SourceType
from soothe.toolkits.deepxiv import resolve_deepxiv_token

if TYPE_CHECKING:
    from soothe.subagents.tacitus.protocol import TacitusConfig

logger = logging.getLogger(__name__)

_ARXIV_URL = re.compile(
    r"https?://(?:arxiv\.org/abs/|arxiv\.org/pdf/)(\d{4}\.\d{4,5}(?:v\d+)?)",
    re.IGNORECASE,
)

_CAPABILITY_DESCRIPTION = (
    "Scientific papers, preprints, peer-reviewed research, citations, methods, "
    "and literature from arXiv, bioRxiv, medRxiv, and PubMed Central."
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
    """Semantic academic search (DeepxivSearchTool via DeepxivToolkit).

    Uses PoliteHTTPClient for rate limiting and circuit breaker protection
    when configured via TacitusConfig.
    """

    capability_id: CapabilityId = "academic_search"
    capability_description: str = _CAPABILITY_DESCRIPTION

    def __init__(self, config: Any | None = None) -> None:
        self._config = config
        self._deepxiv_tool: Any | None = None
        self._tools_loaded = False
        self._load_lock = threading.Lock()
        self._auth_failed = False
        self._auth_failure_logged = False
        self._polite_client: Any | None = None
        self._tacitus_config: TacitusConfig | None = None

    def _get_polite_client(self) -> Any | None:
        """Get or create PoliteHTTPClient from TacitusConfig."""
        if self._polite_client is not None:
            return self._polite_client

        # Extract TacitusConfig from SootheConfig
        tacitus_config = self._extract_tacitus_config()
        if tacitus_config is None:
            return None

        # Only create client if polite concurrency is enabled
        if not tacitus_config.enable_polite_concurrency:
            return None

        from soothe.subagents.tacitus.polite_http import (
            DomainRateLimiter,
            PoliteHTTPClient,
            RateLimit,
            RateLimitConfig,
        )

        # Build rate limit config with domain overrides
        limits: dict[str, RateLimit] = {}
        for domain, overrides in tacitus_config.polite_domain_overrides.items():
            limits[domain] = RateLimit(
                rps=float(overrides.get("rps", tacitus_config.polite_rate_limit_rps)),
                burst=int(overrides.get("burst", tacitus_config.polite_burst_size)),
                concurrent=int(overrides.get("concurrent", tacitus_config.polite_max_concurrent)),
            )

        # Default DeepXiv rate limit
        limits["deepxiv"] = RateLimit(
            rps=tacitus_config.polite_rate_limit_rps,
            burst=tacitus_config.polite_burst_size,
            concurrent=tacitus_config.polite_max_concurrent,
        )

        rate_limit_config = RateLimitConfig(limits=limits)
        rate_limiter = DomainRateLimiter(config=rate_limit_config)

        self._polite_client = PoliteHTTPClient(
            rate_limiter=rate_limiter,
            max_retries=tacitus_config.polite_retry_max,
            base_delay=tacitus_config.polite_retry_base_delay,
            enable_circuit_breaker=True,
            circuit_breaker_threshold=tacitus_config.polite_circuit_breaker_threshold,
            circuit_breaker_reset_sec=tacitus_config.polite_circuit_breaker_reset_sec,
        )

        logger.debug(
            "[Tacitus/academic] PoliteHTTPClient initialized "
            "(rps=%.1f, burst=%d, concurrent=%d, retries=%d)",
            tacitus_config.polite_rate_limit_rps,
            tacitus_config.polite_burst_size,
            tacitus_config.polite_max_concurrent,
            tacitus_config.polite_retry_max,
        )

        return self._polite_client

    def _extract_tacitus_config(self) -> TacitusConfig | None:
        """Extract TacitusConfig from SootheConfig or direct config."""
        if self._tacitus_config is not None:
            return self._tacitus_config

        if self._config is None:
            return None

        # Check if config is already a TacitusConfig
        from soothe.subagents.tacitus.protocol import TacitusConfig

        if isinstance(self._config, TacitusConfig):
            self._tacitus_config = self._config
            return self._tacitus_config

        # Try to get TacitusConfig from subagents.tacitus config
        try:
            sub_cfg = getattr(self._config, "subagents", None)
            if sub_cfg:
                tacitus_subcfg = (
                    sub_cfg.get("tacitus")
                    if hasattr(sub_cfg, "get")
                    else getattr(sub_cfg, "tacitus", None)
                )
                if tacitus_subcfg and hasattr(tacitus_subcfg, "config"):
                    self._tacitus_config = TacitusConfig(**dict(tacitus_subcfg.config))
                    return self._tacitus_config
        except Exception:
            logger.debug("[Tacitus/academic] Could not extract TacitusConfig from SootheConfig")

        return None

    def _ensure_tools(self) -> None:
        with self._load_lock:
            if self._tools_loaded:
                return
            self._tools_loaded = True
            try:
                from soothe.toolkits.deepxiv import DeepxivToolkit

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
                        logger.info("[Tacitus/academic] DeepXiv search tool loaded")
                        break
                if not self._deepxiv_tool:
                    logger.warning(
                        "[Tacitus/academic] DeepXiv toolkit loaded but deepxiv_search tool missing"
                    )
            except Exception:
                logger.warning(
                    "[Tacitus/academic] DeepXiv toolkit not available",
                    exc_info=True,
                )

    def _note_auth_failure(self, search_q: str) -> None:
        self._auth_failed = True
        if not self._auth_failure_logged:
            self._auth_failure_logged = True
            logger.warning(
                "[Tacitus/academic] DeepXiv authentication failed; "
                "skipping further academic searches this run. "
                "Set DEEPXIV_API_KEY or DEEPXIV_TOKEN or register at https://data.rag.ac.cn"
            )
        else:
            logger.info(
                "[Tacitus/academic] query=%r status=skipped reason=deepxiv_auth_failed",
                search_q,
            )

    @property
    def name(self) -> str:
        return "academic"

    @property
    def source_type(self) -> SourceType:
        return "academic"

    async def query(self, query: str, context: GatherContext) -> list[SourceResult]:
        _ = context
        search_q = compact_search_query(query, max_len=200)

        if self._auth_failed:
            logger.info(
                "[Tacitus/academic] query=%r status=skipped reason=deepxiv_auth_failed",
                search_q,
            )
            return []

        self._ensure_tools()
        if not self._deepxiv_tool:
            logger.warning(
                "[Tacitus/academic] query=%r status=skipped reason=deepxiv_unavailable",
                search_q,
            )
            return []

        logger.info("[Tacitus/academic] query=%r status=start backend=deepxiv", search_q)

        # Get polite client for rate limiting
        polite_client = self._get_polite_client()

        async def _execute_search() -> str:
            """Execute the search with optional polite rate limiting."""
            if polite_client is not None:
                # Apply rate limiting via polite client
                await polite_client.rate_limiter.acquire("deepxiv")
                try:
                    result = await self._deepxiv_tool._arun(query=search_q, size=5)
                    return str(result) if result is not None else ""
                finally:
                    polite_client.rate_limiter.release("deepxiv")
            else:
                # No rate limiting - direct call
                result = await self._deepxiv_tool._arun(query=search_q, size=5)
                return str(result) if result is not None else ""

        try:
            text = await _execute_search()

            if text.startswith("Error"):
                if _is_deepxiv_auth_error(text):
                    self._note_auth_failure(search_q)
                else:
                    logger.warning(
                        "[Tacitus/academic] query=%r status=error preview=%r",
                        search_q,
                        text[:200],
                    )
                return []
            if not text or text.startswith("No papers found"):
                logger.info("[Tacitus/academic] query=%r status=no_results", search_q)
                return []
            logger.info(
                "[Tacitus/academic] query=%r status=success output_chars=%d",
                search_q,
                len(text),
            )
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
                    source_name="academic",
                    metadata={
                        "sub_source": "deepxiv",
                        "url": paper_url,
                        "query": search_q,
                    },
                )
            ]
        except Exception as exc:
            if _is_deepxiv_auth_error(str(exc)):
                self._note_auth_failure(search_q)
            else:
                logger.warning(
                    "[Tacitus/academic] query=%r status=exception error=%s",
                    search_q,
                    exc,
                )
        return []
