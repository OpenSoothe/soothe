"""Filesystem InformationSource wrapping file_edit tools."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from soothe.inquiry.protocol import GatherContext, SourceResult, SourceType

logger = logging.getLogger(__name__)

_BASE_FILESYSTEM_SCORE = 0.1
_PATH_MATCH_BONUS = 0.6
_CODEBASE_PHRASE_BONUS = 0.3
_MIN_SPLIT_PARTS = 2
_FULL_SPLIT_PARTS = 3
_MIN_TERM_LENGTH = 2


class FilesystemSource:
    """Information source backed by filesystem search and read.

    Wraps ``SearchInFilesTool``, ``ReadFileTool``, and ``ListFilesTool``
    from the file_edit tool group.  The query is interpreted as a search
    pattern; results include file paths and matching content.

    Args:
        work_dir: Working directory for file operations.
        allow_outside_workdir: Allow access outside the work directory.
    """

    def __init__(
        self,
        work_dir: str = "",
        *,
        allow_outside_workdir: bool = False,
    ) -> None:
        """Initialize the filesystem source with work directory."""
        self._work_dir = work_dir
        self._allow_outside = allow_outside_workdir
        self._search_tool: Any | None = None
        self._read_tool: Any | None = None
        self._list_tool: Any | None = None

    def _ensure_tools(self) -> None:
        if self._search_tool is not None:
            return
        from soothe.tools.file_edit.tools import ListFilesTool, ReadFileTool, SearchInFilesTool

        self._search_tool = SearchInFilesTool(work_dir=self._work_dir)
        self._read_tool = ReadFileTool(
            work_dir=self._work_dir,
            allow_outside_workdir=self._allow_outside,
        )
        self._list_tool = ListFilesTool(work_dir=self._work_dir)

    # -- InformationSource protocol ------------------------------------------

    @property
    def name(self) -> str:
        """Source name."""
        return "filesystem"

    @property
    def source_type(self) -> SourceType:
        """Canonical source type."""
        return "filesystem"

    async def query(self, query: str, context: GatherContext) -> list[SourceResult]:
        """Search the filesystem for content matching the query.

        Strategy:
        1. If the query looks like a file path, read that file directly.
        2. Otherwise, use ``search_in_files`` with the query as a regex pattern.
        3. For directory-listing queries, fall back to ``list_files``.

        Args:
            query: Search query or file path.
            context: Current research context.

        Returns:
            List of SourceResult with file content and paths.
        """
        _ = context
        self._ensure_tools()
        results: list[SourceResult] = []

        if self._looks_like_path(query):
            content = await self._read_tool._arun(query)
            if content and not content.startswith("Error:"):
                results.append(
                    SourceResult(
                        content=content[:5000],
                        source_ref=query,
                        source_name="filesystem",
                        metadata={"type": "file_read"},
                    )
                )
                return results

        search_pattern = self._query_to_pattern(query)
        raw = await self._search_tool._arun(search_pattern)

        if raw and not raw.startswith("No matches") and not raw.startswith("Error:"):
            for line in raw.split("\n")[:20]:
                if ":" in line:
                    parts = line.split(":", 2)
                    file_path = parts[0] if len(parts) >= _MIN_SPLIT_PARTS else ""
                    content = parts[2].strip() if len(parts) >= _FULL_SPLIT_PARTS else line
                    results.append(
                        SourceResult(
                            content=content,
                            source_ref=file_path,
                            source_name="filesystem",
                            metadata={"type": "search_match", "raw_line": line},
                        )
                    )

        if not results:
            listing = await self._list_tool._arun(pattern=f"*{self._extract_extension(query)}*")
            if listing and not listing.startswith("No files") and not listing.startswith("Error:"):
                results.append(
                    SourceResult(
                        content=listing[:3000],
                        source_ref=".",
                        source_name="filesystem",
                        metadata={"type": "directory_listing"},
                    )
                )

        return results

    def relevance_score(self, query: str) -> float:
        """Score high for queries referencing files, code, or the codebase."""
        from soothe.inquiry.sources._scoring import (
            _CODE_KEYWORDS,
            has_file_path,
            keyword_score,
        )

        score = _BASE_FILESYSTEM_SCORE

        if has_file_path(query) or self._looks_like_path(query):
            score += _PATH_MATCH_BONUS

        code_score = keyword_score(query, _CODE_KEYWORDS, weight=0.15)
        score += code_score

        codebase_phrases = ["in the codebase", "in the code", "in the project", "in the repo", "source file"]
        for phrase in codebase_phrases:
            if phrase in query.lower():
                score += _CODEBASE_PHRASE_BONUS
                break

        return min(1.0, score)

    # -- Helpers -------------------------------------------------------------

    @staticmethod
    def _looks_like_path(query: str) -> bool:
        """Return True if the query looks like a direct file/directory path."""
        stripped = query.strip()
        if stripped.startswith("http"):
            return False
        if "/" in stripped or "\\" in stripped:
            p = Path(stripped)
            return len(p.parts) >= 1
        return False

    @staticmethod
    def _query_to_pattern(query: str) -> str:
        """Convert a natural-language query to a regex search pattern.

        Extracts key terms and joins them as alternation.
        """
        import re

        stop_words = {"the", "a", "an", "in", "of", "for", "to", "is", "are", "how", "what", "where", "which"}
        terms = [
            w for w in re.split(r"\s+", query.strip()) if w.lower() not in stop_words and len(w) > _MIN_TERM_LENGTH
        ]
        if not terms:
            return query.strip()
        if len(terms) == 1:
            return terms[0]
        return "|".join(terms[:5])

    @staticmethod
    def _extract_extension(query: str) -> str:
        """Extract a file extension from the query if present."""
        import re

        m = re.search(r"\.\w{1,6}\b", query)
        return m.group(0) if m else ""
