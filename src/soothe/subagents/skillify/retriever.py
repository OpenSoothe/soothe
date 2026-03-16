"""SkillRetriever -- semantic search over the skill index (RFC-0004)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from langchain_core.embeddings import Embeddings

from soothe.protocols.vector_store import VectorStoreProtocol
from soothe.subagents.skillify.models import SkillBundle, SkillRecord, SkillSearchResult

logger = logging.getLogger(__name__)

_INDEXING_WAIT_TIMEOUT = 10.0


class LazyEmbeddings:
    """Wrapper that creates fresh embedding instances per event loop."""

    def __init__(self, factory: Callable[[], Embeddings]):
        self._factory = factory
        self._instances: dict[int, Embeddings] = {}

    def _get_instance(self) -> Embeddings:
        loop_id = id(asyncio.get_running_loop())
        if loop_id not in self._instances:
            self._instances[loop_id] = self._factory()
        return self._instances[loop_id]

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._get_instance().aembed_documents(texts)

    async def aembed_query(self, text: str) -> list[float]:
        return await self._get_instance().aembed_query(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._get_instance().embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._get_instance().embed_query(text)


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
        embeddings: Embeddings | Callable[[], Embeddings],
        top_k: int = 10,
        ready_event: asyncio.Event | None = None,
        policy: Any | None = None,
        policy_profile: str = "standard",
    ) -> None:
        self._vector_store = vector_store
        if callable(embeddings):
            self._embeddings = LazyEmbeddings(embeddings)
        else:
            self._embeddings = embeddings
        self._top_k = top_k
        self._ready_event = ready_event
        self._policy = policy
        self._policy_profile = policy_profile

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
        self._check_policy(query)

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

    def _check_policy(self, query: str) -> None:
        """Apply PolicyProtocol guard to retrieval actions."""
        if self._policy is None:
            return
        from soothe.protocols.policy import ActionRequest, PermissionSet, PolicyContext

        permissions = PermissionSet(frozenset())
        get_profile = getattr(self._policy, "get_profile", None)
        if callable(get_profile):
            profile = get_profile(self._policy_profile)
            if profile is not None:
                permissions = profile.permissions

        decision = self._policy.check(
            ActionRequest(
                action_type="skillify_retrieve",
                tool_name="skillify.retrieve",
                tool_args={"query": query[:200]},
            ),
            PolicyContext(active_permissions=permissions, thread_id=None),
        )
        if decision.verdict == "deny":
            msg = f"Policy denied skill retrieval: {decision.reason}"
            raise ValueError(msg)

    async def _count_indexed(self) -> int:
        """Estimate total indexed skills via list_records."""
        try:
            all_records = await self._vector_store.list_records(limit=10000)
            return len(all_records)
        except Exception:
            return 0
