"""Document InformationSource wrapping the document_qa tool."""

from __future__ import annotations

import logging
from typing import Any

from soothe_daemon.subagents.research.protocol import GatherContext, SourceResult, SourceType

logger = logging.getLogger(__name__)

_DOC_EXTENSION_SCORE = 0.85
_MIN_DOCUMENT_SCORE = 0.02

_DOC_EXTENSIONS: frozenset[str] = frozenset({".pdf", ".docx", ".doc", ".txt", ".md", ".rst"})


class DocumentSource:
    """Information source backed by document Q&A (PDF, DOCX, etc.).

    Wraps the ``document_qa`` tool.  Relevant when the query references
    specific document files or asks about content within local documents.
    """

    def __init__(self, config: Any = None) -> None:
        """Initialize the document source.

        Args:
            config: Optional SootheConfig for tool configuration.
        """
        self._config = config
        self._doc_tool: Any | None = None
        self._loaded = False

    def _ensure_tool(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            from soothe_daemon.tools._internal.document import create_document_tools

            tools = create_document_tools(config=self._config)
            if tools:
                self._doc_tool = tools[0]
        except Exception:
            logger.debug("Document QA tool not available", exc_info=True)

    # -- InformationSource protocol ------------------------------------------

    @property
    def name(self) -> str:
        """Source name."""
        return "document"

    @property
    def source_type(self) -> SourceType:
        """Canonical source type."""
        return "document"

    async def query(self, query: str, context: GatherContext) -> list[SourceResult]:
        """Query a document for information.

        The query should reference a file path (e.g. ``docs/spec.pdf: what is the API?``).
        The first colon-separated segment is treated as the file path and the rest
        as the question.  If no colon is present the whole query is the question.

        Args:
            query: Question, optionally prefixed with ``file_path:``.
            context: Current research context.

        Returns:
            List of SourceResult with document content.
        """
        _ = context
        self._ensure_tool()
        if not self._doc_tool:
            return []

        file_path, question = self._split_path_question(query)
        if not file_path:
            return []

        results: list[SourceResult] = []
        try:
            raw = await self._doc_tool._arun(file_path=file_path, question=question)
            if raw and not raw.startswith("Error"):
                results.append(
                    SourceResult(
                        content=raw[:5000],
                        source_ref=file_path,
                        source_name="document",
                        metadata={"question": question},
                    )
                )
        except Exception:
            logger.debug("Document query failed for: %s", file_path, exc_info=True)

        return results

    def relevance_score(self, query: str) -> float:
        """Score high when the query references document files."""
        from ._scoring import _DOCUMENT_KEYWORDS, keyword_score

        q_lower = query.lower()

        for ext in _DOC_EXTENSIONS:
            if ext in q_lower:
                return _DOC_EXTENSION_SCORE

        score = keyword_score(q_lower, _DOCUMENT_KEYWORDS, weight=0.15)
        return min(1.0, max(_MIN_DOCUMENT_SCORE, score))

    # -- Helpers -------------------------------------------------------------

    @staticmethod
    def _split_path_question(query: str) -> tuple[str, str]:
        """Split ``file_path: question`` into components.

        Returns:
            Tuple of (file_path, question).  file_path is empty if not
            detected.
        """
        import re

        m = re.match(
            r"^([\w./ \\-]+\.(?:pdf|docx|doc|txt|md|rst))\s*[:?]\s*(.+)", query, re.IGNORECASE
        )
        if m:
            return m.group(1).strip(), m.group(2).strip()

        for ext in _DOC_EXTENSIONS:
            if ext in query.lower():
                parts = query.split()
                for part in parts:
                    if part.lower().endswith(ext):
                        question = query.replace(part, "").strip().lstrip(":").strip()
                        return part, question or "Summarize this document."

        return "", query
