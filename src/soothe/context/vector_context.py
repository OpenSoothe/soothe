"""VectorContext -- semantic context implementation using vector store."""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from soothe.protocols.context import ContextEntry, ContextProjection

if TYPE_CHECKING:
    from langchain_core.embeddings import Embeddings

    from soothe.protocols.vector_store import VectorStoreProtocol

logger = logging.getLogger(__name__)

_CHARS_PER_TOKEN = 4
_SUMMARY_LIMIT = 10


def _estimate_tokens(text: str) -> int:
    return len(text) // _CHARS_PER_TOKEN


class VectorContext:
    """ContextProtocol implementation using VectorStoreProtocol + Embeddings.

    Embeds entries on ingest for semantic projection. Maintains an
    in-memory cache for summarization and fast access.
    """

    def __init__(
        self,
        vector_store: VectorStoreProtocol,
        embeddings: Embeddings,
    ) -> None:
        """Initialize VectorContext.

        Args:
            vector_store: Vector database for storing embedded context entries.
            embeddings: Langchain embeddings model for generating vectors.
        """
        self._store = vector_store
        self._embeddings = embeddings
        self._entries: list[ContextEntry] = []

    @property
    def entries(self) -> list[ContextEntry]:
        """All entries in the in-memory cache."""
        return list(self._entries)

    async def ingest(self, entry: ContextEntry) -> None:
        """Embed and store a context entry."""
        self._entries.append(entry)
        record_id = str(uuid.uuid4())
        vectors = await self._embeddings.aembed_documents([entry.content])
        payload = entry.model_dump(mode="json")
        payload["_record_id"] = record_id
        await self._store.insert(
            vectors=vectors,
            payloads=[payload],
            ids=[record_id],
        )

    async def project(self, query: str, token_budget: int) -> ContextProjection:
        """Semantically project relevant entries within a token budget."""
        if not self._entries:
            return ContextProjection(entries=[], total_entries=0, token_count=0)

        query_vector = await self._embeddings.aembed_query(query)
        results = await self._store.search(
            query=query,
            vector=query_vector,
            limit=50,
        )

        selected: list[ContextEntry] = []
        used = 0
        for record in results:
            try:
                entry = ContextEntry.model_validate(record.payload)
            except (TypeError, ValueError):
                continue
            entry_tokens = _estimate_tokens(entry.content)
            if used + entry_tokens > token_budget:
                continue
            selected.append(entry)
            used += entry_tokens

        return ContextProjection(
            entries=selected,
            summary=None,
            total_entries=len(self._entries),
            token_count=used,
        )

    async def project_for_subagent(self, goal: str, token_budget: int) -> ContextProjection:
        """Project a focused briefing for a subagent's goal."""
        return await self.project(goal, token_budget)

    async def summarize(self, scope: str | None = None) -> str:
        """Produce a text summary from the in-memory cache."""
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
        """No-op -- vector store is inherently persistent."""

    async def restore(self, thread_id: str) -> bool:
        """Restore in-memory cache from the vector store.

        Loads all records with matching ``thread_id`` filter. If no
        thread_id filtering is available, loads recent records.
        """
        try:
            records = await self._store.list_records(
                filters={"source_thread": thread_id},
                limit=1000,
            )
            self._entries = []
            for record in records:
                try:
                    entry = ContextEntry.model_validate(record.payload)
                    self._entries.append(entry)
                except (TypeError, ValueError):
                    continue
        except Exception:
            logger.warning("Failed to restore vector context for thread %s", thread_id)
            return False
        else:
            return bool(self._entries)
