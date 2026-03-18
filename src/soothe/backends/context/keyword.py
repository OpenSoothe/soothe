"""KeywordContext -- lightweight context implementation using keyword matching."""

from __future__ import annotations

import logging
import re

from soothe.backends.persistence import PersistStore
from soothe.core.classification import count_tokens
from soothe.protocols.context import ContextEntry, ContextProjection

logger = logging.getLogger(__name__)

_SUMMARY_LIMIT = 10


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"\w{3,}", text.lower()))


class KeywordContext:
    """Lightweight ContextProtocol implementation using keyword matching.

    Stores entries in a list. Projection ranks entries by keyword overlap
    with the query plus a recency boost. No embedding dependencies.
    Supports JSON, RocksDB, or PostgreSQL persistence backends.
    """

    def __init__(self, persist_store: PersistStore | None = None, *, use_tiktoken: bool = False) -> None:
        """Initialize KeywordContext.

        Args:
            persist_store: Optional PersistStore instance for persistence.
                          None for in-memory only (no persistence).
            use_tiktoken: Use tiktoken for token counting if available (default: False).
        """
        self._entries: list[ContextEntry] = []
        self._store = persist_store
        self._use_tiktoken = use_tiktoken

    @property
    def entries(self) -> list[ContextEntry]:
        """All entries in the ledger."""
        return list(self._entries)

    async def ingest(self, entry: ContextEntry) -> None:
        """Add an entry to the ledger."""
        self._entries.append(entry)

    async def project(self, query: str, token_budget: int) -> ContextProjection:
        """Project relevant entries within a token budget.

        Ranking: keyword overlap score + recency boost + importance weight.
        """
        if not self._entries:
            return ContextProjection(entries=[], total_entries=0, token_count=0)

        scored = self._score_entries(query)
        selected, token_count = self._select_within_budget(scored, token_budget)

        return ContextProjection(
            entries=selected,
            summary=None,
            total_entries=len(self._entries),
            token_count=token_count,
        )

    async def project_for_subagent(self, goal: str, token_budget: int) -> ContextProjection:
        """Project a focused briefing for a subagent."""
        return await self.project(goal, token_budget)

    async def summarize(self, scope: str | None = None) -> str:
        """Produce a text summary of the ledger."""
        entries = self._entries
        if scope:
            entries = [e for e in entries if scope in e.source or scope in e.tags]

        if not entries:
            return "No context entries."

        lines = [f"Context ledger: {len(entries)} entries"]
        lines.extend(f"- [{entry.source}] {entry.content[:100]}" for entry in entries[-_SUMMARY_LIMIT:])
        if len(entries) > _SUMMARY_LIMIT:
            lines.insert(1, f"  (showing last {_SUMMARY_LIMIT} of {len(entries)})")
        return "\n".join(lines)

    async def persist(self, thread_id: str) -> None:
        """Persist the ledger via the configured backend."""
        if not self._store:
            return
        data = [e.model_dump(mode="json") for e in self._entries]
        self._store.save(f"context_{thread_id}", data)

    async def restore(self, thread_id: str) -> bool:
        """Restore the ledger from the configured backend."""
        if not self._store:
            return False
        data = self._store.load(f"context_{thread_id}")
        if data is None:
            return False
        try:
            self._entries = [ContextEntry.model_validate(d) for d in data]
        except (TypeError, ValueError):
            logger.warning("Failed to restore context for thread %s", thread_id)
            return False
        else:
            return True

    def _score_entries(self, query: str) -> list[tuple[float, ContextEntry]]:
        query_tokens = _tokenize(query)
        scored: list[tuple[float, ContextEntry]] = []
        total = len(self._entries)
        for idx, entry in enumerate(self._entries):
            entry_tokens = _tokenize(entry.content) | _tokenize(" ".join(entry.tags))
            overlap = len(query_tokens & entry_tokens)
            keyword_score = overlap / max(len(query_tokens), 1)
            recency = (idx + 1) / total
            score = keyword_score * 0.6 + recency * 0.2 + entry.importance * 0.2
            scored.append((score, entry))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored

    def _select_within_budget(
        self,
        scored: list[tuple[float, ContextEntry]],
        token_budget: int,
    ) -> tuple[list[ContextEntry], int]:
        selected: list[ContextEntry] = []
        used = 0
        for _, entry in scored:
            # Use shared token counting (offline, no model needed)
            entry_tokens = count_tokens(entry.content, use_tiktoken=self._use_tiktoken)
            if used + entry_tokens > token_budget:
                continue
            selected.append(entry)
            used += entry_tokens
        return selected, used
