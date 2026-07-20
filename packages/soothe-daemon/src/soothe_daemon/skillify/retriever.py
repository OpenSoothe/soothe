"""Semantic search over the Skillify vector index."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from soothe.foundation.sloop.utils.stream_normalize import extract_text_from_message_content
from soothe_sdk.protocols.policy import ActionRequest, PermissionSet, PolicyContext
from soothe_sdk.skillify.models import SkillBundle, SkillRecord, SkillSearchResult

if TYPE_CHECKING:
    from collections.abc import Callable

    from langchain_core.embeddings import Embeddings
    from soothe_sdk.protocols.vector_store import VectorStoreProtocol

logger = logging.getLogger(__name__)

_INDEXING_WAIT_TIMEOUT = 10.0
_VECTOR_SEARCH_MAX_ATTEMPTS = 3
_VECTOR_SEARCH_BACKOFF_BASE = 0.5
_EMBEDDING_MAX_ATTEMPTS = 3
_EMBEDDING_BACKOFF_BASE = 0.5
_INDEXING_IN_PROGRESS_PREFIX = "[Indexing in progress]"
_EMBEDDING_UNAVAILABLE_PREFIX = "[Embedding unavailable]"
_vector_search_semaphore: asyncio.Semaphore | None = None


def configure_vector_search_concurrency(limit: int) -> None:
    """Set the process-wide Skillify vector search concurrency limit."""
    global _vector_search_semaphore

    _vector_search_semaphore = asyncio.Semaphore(max(1, limit))


def _get_vector_search_semaphore() -> asyncio.Semaphore:
    if _vector_search_semaphore is None:
        configure_vector_search_concurrency(4)
    assert _vector_search_semaphore is not None
    return _vector_search_semaphore


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
        total_indexed: int | None = None,
        total_indexed_fn: Callable[[], int] | None = None,
    ) -> None:
        self._vector_store = vector_store
        if callable(embeddings):
            self._embeddings: Embeddings | LazyEmbeddings = LazyEmbeddings(embeddings)
        else:
            self._embeddings = embeddings
        self._top_k = top_k
        self._ready_event = ready_event
        self._policy = policy
        self._policy_profile = policy_profile
        self._total_indexed = total_indexed
        self._total_indexed_fn = total_indexed_fn

    @property
    def is_ready(self) -> bool:
        if self._ready_event is None:
            return True
        return self._ready_event.is_set()

    async def retrieve(self, query: str, top_k: int | None = None) -> SkillBundle:
        query = extract_text_from_message_content(query)
        self._check_policy(query)

        if self._ready_event and not self._ready_event.is_set():
            logger.info("Skillify index not ready, waiting up to %.0fs", _INDEXING_WAIT_TIMEOUT)
            try:
                await asyncio.wait_for(self._ready_event.wait(), timeout=_INDEXING_WAIT_TIMEOUT)
            except TimeoutError:
                logger.warning(
                    "Skillify index still not ready after %.0fs timeout",
                    _INDEXING_WAIT_TIMEOUT,
                )
                return SkillBundle(
                    query=(
                        f"{_INDEXING_IN_PROGRESS_PREFIX} "
                        "The skill warehouse is still being indexed. "
                        "Please retry shortly."
                    ),
                )

        limit = top_k or self._top_k

        try:
            vector = await self._embed_query_with_retry(query)
        except Exception as exc:
            if self._is_transient_embedding_error(exc):
                logger.warning(
                    "Skillify embedding service temporarily unavailable (%s): %s",
                    type(exc).__name__,
                    exc,
                )
                return SkillBundle(
                    query=(
                        f"{_EMBEDDING_UNAVAILABLE_PREFIX} "
                        "Semantic skill search is temporarily unavailable. "
                        "Falling back to keyword matching."
                    ),
                )
            logger.exception("Query embedding failed for: %s", query[:100])
            return SkillBundle(
                query=(
                    f"{_EMBEDDING_UNAVAILABLE_PREFIX} "
                    "Semantic skill search is unavailable due to an embedding provider error."
                ),
            )

        try:
            records = await self._search_with_retry(
                query=query,
                vector=vector,
                limit=limit,
            )
        except Exception:
            logger.exception("Vector store search failed")
            return SkillBundle(query=query)

        results: list[SkillSearchResult] = []
        for vector_record in records:
            payload = vector_record.payload
            record = SkillRecord(
                id=payload.get("skill_id", vector_record.id),
                name=payload.get("name", "unknown"),
                description=payload.get("description", ""),
                path=payload.get("path", ""),
                tags=payload.get("tags", []),
                status="indexed",
                indexed_at=datetime.now(UTC),
                content_hash=payload.get("content_hash", ""),
            )
            results.append(SkillSearchResult(record=record, score=vector_record.score or 0.0))

        total_records = await self._count_indexed()

        return SkillBundle(
            query=query,
            results=results,
            total_indexed=total_records,
        )

    async def _search_with_retry(
        self,
        *,
        query: str,
        vector: list[float],
        limit: int,
    ) -> list[Any]:
        """Search vector store with backoff when the connection pool is saturated."""
        last_exc: Exception | None = None
        sem = _get_vector_search_semaphore()
        for attempt in range(_VECTOR_SEARCH_MAX_ATTEMPTS):
            try:
                async with sem:
                    return await self._vector_store.search(
                        query=query,
                        vector=vector,
                        limit=limit,
                    )
            except Exception as exc:
                last_exc = exc
                exc_name = type(exc).__name__
                is_pool_timeout = exc_name == "PoolTimeout" or "PoolTimeout" in str(exc)
                if not is_pool_timeout or attempt >= _VECTOR_SEARCH_MAX_ATTEMPTS - 1:
                    raise
                delay = _VECTOR_SEARCH_BACKOFF_BASE * (2**attempt)
                logger.warning(
                    "Vector store pool timeout (attempt %d/%d), retrying in %.1fs",
                    attempt + 1,
                    _VECTOR_SEARCH_MAX_ATTEMPTS,
                    delay,
                )
                await asyncio.sleep(delay)
        if last_exc is not None:
            raise last_exc
        return []

    @staticmethod
    def _is_transient_embedding_error(exc: Exception) -> bool:
        exc_name = type(exc).__name__
        if exc_name in {"APIConnectionError", "APITimeoutError"}:
            return True
        # Compatibility for HTTP client wrappers raised by OpenAI/LangChain.
        msg = str(exc)
        return any(token in msg for token in ("ConnectError", "ReadTimeout", "PoolTimeout"))

    async def _embed_query_with_retry(self, query: str) -> list[float]:
        last_exc: Exception | None = None
        for attempt in range(_EMBEDDING_MAX_ATTEMPTS):
            try:
                return await self._embeddings.aembed_query(query)
            except Exception as exc:
                last_exc = exc
                is_transient = self._is_transient_embedding_error(exc)
                if not is_transient or attempt >= _EMBEDDING_MAX_ATTEMPTS - 1:
                    raise
                delay = _EMBEDDING_BACKOFF_BASE * (2**attempt)
                logger.warning(
                    "Skillify embedding transient failure (%s, attempt %d/%d), retrying in %.1fs",
                    type(exc).__name__,
                    attempt + 1,
                    _EMBEDDING_MAX_ATTEMPTS,
                    delay,
                )
                await asyncio.sleep(delay)

        if last_exc is not None:
            raise last_exc
        msg = "Unexpected empty embedding retry loop."
        raise RuntimeError(msg)

    def _check_policy(self, query: str) -> None:
        if self._policy is None:
            return

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
        if self._total_indexed_fn is not None:
            return self._total_indexed_fn()
        if self._total_indexed is not None:
            return self._total_indexed
        return 0
