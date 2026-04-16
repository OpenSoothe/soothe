"""SkillRetriever -- semantic search over the skill index (RFC-0004)."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from .models import SkillBundle, SkillRecord, SkillSearchResult

if TYPE_CHECKING:
    from collections.abc import Callable

    from langchain_core.embeddings import Embeddings

    from soothe_sdk import VectorStoreProtocol

logger = logging.getLogger(__name__)

_INDEXING_WAIT_TIMEOUT = 10.0


class LazyEmbeddings:
    """Wrapper that creates fresh embedding instances per event loop."""

    def __init__(self, factory: Callable[[], Embeddings]) -> None:
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
    """Semantic search over the Skillify vector index."""

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
        if self._ready_event is None:
            return True
        return self._ready_event.is_set()

    async def retrieve(self, query: str, top_k: int | None = None) -> SkillBundle:
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
            logger.exception("Query embedding failed for: %s", query[:100])
            return SkillBundle(query=query)

        try:
            records = await self._vector_store.search(
                query=query,
                vector=vector,
                limit=k,
            )
        except Exception:
            logger.exception("Vector store search failed")
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
        if self._policy is None:
            return
        from soothe_sdk import ActionRequest, PermissionSet, PolicyContext

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
        try:
            all_records = await self._vector_store.list_records(limit=10000)
            return len(all_records)
        except Exception:
            return 0
