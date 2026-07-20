"""Background loop for embedding and upserting skills."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Any

from soothe_sdk.protocols.vector_store import VectorStoreProtocol
from soothe_sdk.skillify.models import SkillRecord

from .events import (
    SkillifyIndexFailedEvent,
    SkillifyIndexStartedEvent,
    SkillifyIndexUnchangedEvent,
    SkillifyIndexUpdatedEvent,
)
from .warehouse import SkillWarehouse

if TYPE_CHECKING:
    from collections.abc import Callable

    from langchain_core.embeddings import Embeddings

logger = logging.getLogger(__name__)


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


class SkillIndexer:
    """Background indexing loop that keeps the vector store in sync with the warehouse."""

    def __init__(
        self,
        warehouse: SkillWarehouse,
        vector_store: VectorStoreProtocol,
        embeddings: Embeddings | Callable[[], Embeddings],
        interval_seconds: int = 300,
        collection: str = "soothe_skillify",
        embedding_dims: int = 1536,
        event_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._warehouse = warehouse
        self._vector_store = vector_store
        if callable(embeddings):
            self._embeddings: Embeddings | LazyEmbeddings = LazyEmbeddings(embeddings)
        else:
            self._embeddings = embeddings
        self._interval = interval_seconds
        self._collection = collection
        self._embedding_dims = embedding_dims
        self._hash_cache: dict[str, str] = {}
        self._task: asyncio.Task[None] | None = None
        self._initialized = False
        self._total_indexed = 0
        self._ready_event: asyncio.Event | None = None
        self._event_callback = event_callback

    @property
    def total_indexed(self) -> int:
        return self._total_indexed

    @property
    def ready_event(self) -> asyncio.Event:
        if self._ready_event is None:
            self._ready_event = asyncio.Event()
        return self._ready_event

    @property
    def is_ready(self) -> bool:
        if self._ready_event is None:
            return False
        return self._ready_event.is_set()

    async def start(self) -> None:
        if self._task is not None:
            return
        await self._ensure_collection()
        await self._bootstrap_hash_cache()
        self._emit(SkillifyIndexStartedEvent(collection=self._collection).to_dict())
        self._task = asyncio.create_task(self._index_loop())
        logger.info("Skillify background indexer started (interval=%ds)", self._interval)

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

        if hasattr(self._vector_store, "close"):
            owns_pool = getattr(self._vector_store, "_owns_pool", True)
            if owns_pool:
                try:
                    await self._vector_store.close()
                except Exception:
                    logger.debug("Failed to close vector store", exc_info=True)

        logger.info("Skillify background indexer stopped")

    async def run_once(self) -> dict[str, int]:
        stats: dict[str, int] = {"new": 0, "changed": 0, "deleted": 0}

        current_records = self._warehouse.scan()
        current_ids = {record.id for record in current_records}

        to_embed: list[SkillRecord] = []
        for record in current_records:
            cached_hash = self._hash_cache.get(record.id)
            if cached_hash is None:
                to_embed.append(record)
                stats["new"] += 1
            elif cached_hash != record.content_hash:
                to_embed.append(record)
                stats["changed"] += 1

        deleted_ids = set(self._hash_cache.keys()) - current_ids
        for deleted_id in deleted_ids:
            try:
                await self._vector_store.delete(deleted_id)
            except Exception:
                logger.warning("Failed to delete stale record %s", deleted_id, exc_info=True)
            self._hash_cache.pop(deleted_id, None)
            stats["deleted"] += 1

        if to_embed:
            await self._embed_and_upsert(to_embed)

        for record in current_records:
            self._hash_cache[record.id] = record.content_hash

        self._total_indexed = len(current_ids)
        return stats

    async def _embed_and_upsert(self, records: list[SkillRecord]) -> None:
        texts = [self._embedding_text(record) for record in records]
        sanitized_texts: list[str] = []
        for index, text in enumerate(texts):
            sanitized = text if isinstance(text, str) else str(text or "Untitled skill")
            if not sanitized.strip():
                logger.warning("Text %d is empty, using placeholder", index)
                sanitized = "Untitled skill"
            sanitized_texts.append(sanitized)

        if not sanitized_texts:
            logger.error("No valid texts for embedding")
            return

        try:
            vectors = await self._embeddings.aembed_documents(sanitized_texts)
        except Exception:
            logger.exception(
                "Embedding generation failed for %d skills. First text sample: %.200s",
                len(records),
                sanitized_texts[0] if sanitized_texts else "N/A",
            )
            return

        if not vectors:
            logger.error("Embedding model returned no vectors for %d skills", len(records))
            return

        actual_dims = len(vectors[0])
        if actual_dims != self._embedding_dims:
            logger.error(
                "Embedding dimension mismatch: model returned %d but config embedding_dims=%d. "
                "Update embedding_profile[].embedding_dims or switch embedding model.",
                actual_dims,
                self._embedding_dims,
            )
            return

        payloads: list[dict[str, Any]] = []
        ids: list[str] = []
        for record in records:
            payloads.append(
                {
                    "skill_id": record.id,
                    "name": record.name,
                    "description": record.description,
                    "path": record.path,
                    "tags": record.tags,
                    "content_hash": record.content_hash,
                }
            )
            ids.append(record.id)

        try:
            await self._vector_store.insert(vectors=vectors, payloads=payloads, ids=ids)
        except Exception:
            logger.exception("Vector store upsert failed for %d skills", len(records))

    @staticmethod
    def _embedding_text(record: SkillRecord) -> str:
        parts: list[str] = []
        if record.name and str(record.name).strip():
            parts.append(str(record.name).strip())
        if record.description and str(record.description).strip():
            parts.append(str(record.description).strip())
        if record.tags:
            tag_strs = [str(tag).strip() for tag in record.tags if tag and str(tag).strip()]
            if tag_strs:
                parts.append("Tags: " + ", ".join(tag_strs))
        result = "\n".join(parts)
        return result if result.strip() else "Untitled skill"

    async def _ensure_collection(self) -> None:
        if self._initialized:
            return
        try:
            await self._vector_store.create_collection(
                vector_size=self._embedding_dims,
                distance="cosine",
            )
        except Exception:
            logger.warning("Collection creation failed (may already exist)", exc_info=True)
        self._initialized = True

    async def _index_loop(self) -> None:
        first_pass = True
        while True:
            try:
                stats = await self.run_once()
                total_changes = stats["new"] + stats["changed"] + stats["deleted"]
                if total_changes > 0:
                    self._emit(
                        SkillifyIndexUpdatedEvent(
                            new=stats["new"],
                            changed=stats["changed"],
                            deleted=stats["deleted"],
                            total=self._total_indexed,
                        ).to_dict()
                    )
                else:
                    self._emit(SkillifyIndexUnchangedEvent(total=self._total_indexed).to_dict())
                if first_pass:
                    self.ready_event.set()
                    first_pass = False
                    logger.info("Skillify index ready (total=%d)", self._total_indexed)
            except asyncio.CancelledError:
                raise
            except Exception:
                self._emit(SkillifyIndexFailedEvent().to_dict())
                logger.exception("Skillify index pass failed")
                if first_pass:
                    self.ready_event.set()
                    first_pass = False

            await asyncio.sleep(self._interval)

    async def _bootstrap_hash_cache(self) -> None:
        try:
            records = await self._vector_store.list_records(limit=10000)
        except Exception:
            logger.debug("Skillify hash cache bootstrap failed", exc_info=True)
            return

        for record in records:
            payload = record.payload or {}
            skill_id = payload.get("skill_id")
            content_hash = payload.get("content_hash")
            if (
                isinstance(skill_id, str)
                and isinstance(content_hash, str)
                and skill_id
                and content_hash
            ):
                self._hash_cache[skill_id] = content_hash

    def _emit(self, event: dict[str, Any]) -> None:
        if self._event_callback is None:
            return
        try:
            self._event_callback(event)
        except Exception:
            logger.debug("Skillify event callback failed", exc_info=True)
