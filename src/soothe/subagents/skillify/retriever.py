"""SkillRetriever -- semantic search over the skill index (RFC-0004)."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from langchain_core.embeddings import Embeddings

from soothe.protocols.vector_store import VectorStoreProtocol
from soothe.subagents.skillify.models import SkillBundle, SkillRecord, SkillSearchResult

logger = logging.getLogger(__name__)

_INDEXING_WAIT_TIMEOUT = 10.0


class SkillRetriever:
    """Semantic search over the Skillify vector index.

    Embeds a natural-language query, searches the vector store, and returns
    a ranked ``SkillBundle``.  If the indexer has not yet completed its first
    pass, waits up to ``_INDEXING_WAIT_TIMEOUT`` seconds before returning an
    informative "not ready" bundle.

    Args:
        vector_store: Vector store containing skill embeddings.
        embeddings: Embedding model for query vectorization.
        top_k: Maximum number of results to return.
        ready_event: ``asyncio.Event`` set by ``SkillIndexer`` after first pass.
    """

    def __init__(
        self,
        vector_store: VectorStoreProtocol,
        embeddings: Embeddings,
        top_k: int = 10,
        ready_event: asyncio.Event | None = None,
    ) -> None:
        self._vector_store = vector_store
        self._embeddings = embeddings
        self._top_k = top_k
        self._ready_event = ready_event

    @property
    def is_ready(self) -> bool:
        """Whether the skill index has completed its first pass."""
        if self._ready_event is None:
            return True
        return self._ready_event.is_set()

    async def retrieve(self, query: str, top_k: int | None = None) -> SkillBundle:
        """Embed query, search vector store, return ranked SkillBundle.

        If the indexer hasn't completed its first pass, waits up to a bounded
        timeout.  Returns an informative bundle if still not ready.

        Args:
            query: Natural-language retrieval objective.
            top_k: Override the default top-k limit.

        Returns:
            A ``SkillBundle`` with ranked results.
        """
        if self._ready_event and not self._ready_event.is_set():
            logger.info("Skillify index not ready, waiting up to %.0fs", _INDEXING_WAIT_TIMEOUT)
            try:
                await asyncio.wait_for(self._ready_event.wait(), timeout=_INDEXING_WAIT_TIMEOUT)
            except TimeoutError:
                logger.warning("Skillify index still not ready after %.0fs timeout", _INDEXING_WAIT_TIMEOUT)
                return SkillBundle(
                    query="[Indexing in progress] The skill warehouse is still being indexed. Please retry shortly.",
                )

        k = top_k or self._top_k

        try:
            vector = await self._embeddings.aembed_query(query)
        except Exception:
            logger.error("Query embedding failed for: %s", query[:100], exc_info=True)
            return SkillBundle(query=query)

        try:
            records = await self._vector_store.search(
                query=query,
                vector=vector,
                limit=k,
            )
        except Exception:
            logger.error("Vector store search failed", exc_info=True)
            return SkillBundle(query=query)

        results: list[SkillSearchResult] = []
        for vr in records:
            payload = vr.payload
            record = SkillRecord(
                id=payload.get("skill_id", vr.id),
                name=payload.get("name", "unknown"),
                description=payload.get("description", ""),
                path=payload.get("path", ""),
                tags=payload.get("tags", []),
                status="indexed",
                indexed_at=datetime.now(UTC),
                content_hash=payload.get("content_hash", ""),
            )
            results.append(SkillSearchResult(record=record, score=vr.score or 0.0))

        total_records = await self._count_indexed()

        return SkillBundle(
            query=query,
            results=results,
            total_indexed=total_records,
        )

    async def _count_indexed(self) -> int:
        """Estimate total indexed skills via list_records."""
        try:
            all_records = await self._vector_store.list_records(limit=10000)
            return len(all_records)
        except Exception:
            return 0
