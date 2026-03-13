"""SkillIndexer -- background loop for embedding and upserting skills (RFC-0004)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from langchain_core.embeddings import Embeddings

from soothe.protocols.vector_store import VectorStoreProtocol
from soothe.subagents.skillify.models import SkillRecord
from soothe.subagents.skillify.warehouse import SkillWarehouse

logger = logging.getLogger(__name__)


class SkillIndexer:
    """Background indexing loop that keeps the vector store in sync with the warehouse.

    Uses content hashes for change detection so only new or modified skills
    are re-embedded on each pass.

    Args:
        warehouse: Warehouse scanner instance.
        vector_store: Vector store for skill embeddings.
        embeddings: Embedding model for generating vectors.
        interval_seconds: Seconds between indexing passes.
        collection: Vector store collection name.
        embedding_dims: Embedding vector dimensionality.
    """

    def __init__(
        self,
        warehouse: SkillWarehouse,
        vector_store: VectorStoreProtocol,
        embeddings: Embeddings,
        interval_seconds: int = 300,
        collection: str = "soothe_skillify",
        embedding_dims: int = 1536,
    ) -> None:
        self._warehouse = warehouse
        self._vector_store = vector_store
        self._embeddings = embeddings
        self._interval = interval_seconds
        self._collection = collection
        self._embedding_dims = embedding_dims
        self._hash_cache: dict[str, str] = {}
        self._task: asyncio.Task[None] | None = None
        self._initialized = False
        self._total_indexed = 0
        self._ready_event = asyncio.Event()

    @property
    def total_indexed(self) -> int:
        """Number of skills currently indexed."""
        return self._total_indexed

    @property
    def ready_event(self) -> asyncio.Event:
        """Event that is set once the first indexing pass completes."""
        return self._ready_event

    @property
    def is_ready(self) -> bool:
        """Whether the first indexing pass has completed."""
        return self._ready_event.is_set()

    async def start(self) -> None:
        """Start the background indexing loop as an asyncio.Task."""
        if self._task is not None:
            return
        await self._ensure_collection()
        self._task = asyncio.create_task(self._index_loop())
        logger.info("Skillify background indexer started (interval=%ds)", self._interval)

    async def stop(self) -> None:
        """Cancel the background task and wait for cleanup."""
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        logger.info("Skillify background indexer stopped")

    async def run_once(self) -> dict[str, int]:
        """Run a single indexing pass.

        Returns:
            Dict with counts: ``new``, ``changed``, ``deleted``.
        """
        stats: dict[str, int] = {"new": 0, "changed": 0, "deleted": 0}

        current_records = self._warehouse.scan()
        current_ids = {r.id for r in current_records}

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
        for did in deleted_ids:
            try:
                await self._vector_store.delete(did)
            except Exception:
                logger.warning("Failed to delete stale record %s", did, exc_info=True)
            self._hash_cache.pop(did, None)
            stats["deleted"] += 1

        if to_embed:
            await self._embed_and_upsert(to_embed)

        for record in current_records:
            self._hash_cache[record.id] = record.content_hash

        self._total_indexed = len(current_ids)
        return stats

    async def _embed_and_upsert(self, records: list[SkillRecord]) -> None:
        """Generate embeddings and upsert records into the vector store."""
        texts = [self._embedding_text(r) for r in records]

        try:
            vectors = await self._embeddings.aembed_documents(texts)
        except Exception:
            logger.error("Embedding generation failed for %d skills", len(records), exc_info=True)
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
            logger.error("Vector store upsert failed for %d skills", len(records), exc_info=True)

    @staticmethod
    def _embedding_text(record: SkillRecord) -> str:
        """Build the text to embed for a skill record."""
        parts = [record.name]
        if record.description:
            parts.append(record.description)
        if record.tags:
            parts.append("Tags: " + ", ".join(record.tags))
        return "\n".join(parts)

    async def _ensure_collection(self) -> None:
        """Create the vector store collection if it does not exist."""
        if self._initialized:
            return
        try:
            await self._vector_store.create_collection(
                vector_size=self._embedding_dims,
                distance="cosine",
            )
            self._initialized = True
        except Exception:
            logger.warning("Collection creation failed (may already exist)", exc_info=True)
            self._initialized = True

    async def _index_loop(self) -> None:
        """Perpetual loop: run_once() then sleep(interval)."""
        first_pass = True
        while True:
            try:
                stats = await self.run_once()
                total_changes = stats["new"] + stats["changed"] + stats["deleted"]
                if total_changes > 0:
                    logger.info(
                        "Skillify index pass: new=%d changed=%d deleted=%d total=%d",
                        stats["new"],
                        stats["changed"],
                        stats["deleted"],
                        self._total_indexed,
                    )
                else:
                    logger.debug("Skillify index pass: no changes (total=%d)", self._total_indexed)
                if first_pass:
                    self._ready_event.set()
                    first_pass = False
                    logger.info("Skillify index ready (total=%d)", self._total_indexed)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.error("Skillify index pass failed", exc_info=True)
                if first_pass:
                    self._ready_event.set()
                    first_pass = False

            await asyncio.sleep(self._interval)
