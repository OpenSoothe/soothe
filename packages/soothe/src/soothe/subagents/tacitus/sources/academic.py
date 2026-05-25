"""Academic paper search via DeepXiv."""

from __future__ import annotations

import logging
import re
import threading
from typing import Any

from soothe.subagents.tacitus.json_util import compact_search_query
from soothe.subagents.tacitus.protocol import CapabilityId, GatherContext, SourceResult, SourceType
from soothe.toolkits.deepxiv import resolve_deepxiv_token

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
    """Semantic academic search (DeepxivSearchTool via DeepxivToolkit)."""

    capability_id: CapabilityId = "academic_search"
    capability_description: str = _CAPABILITY_DESCRIPTION

    def __init__(self, config: Any | None = None) -> None:
        self._config = config
        self._deepxiv_tool: Any | None = None
        self._tools_loaded = False
        self._load_lock = threading.Lock()
        self._auth_failed = False
        self._auth_failure_logged = False

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
        try:
            raw = await self._deepxiv_tool._arun(query=search_q, size=5)
            text = str(raw) if raw is not None else ""
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
