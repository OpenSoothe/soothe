"""Daemon-shared Skillify indexing and semantic skill search."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from soothe.config import SOOTHE_HOME

from .indexer import SkillIndexer
from .models import SkillBundle
from .retriever import SkillRetriever, configure_vector_search_concurrency
from .warehouse import SkillWarehouse

if TYPE_CHECKING:
    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)

_shared_instance: SkillifyService | None = None
_shared_lock = asyncio.Lock()


def _default_warehouse_paths(soothe_home: Path) -> list[str]:
    """Default Skillify scan roots (same user skill dirs as the skill catalog)."""
    return [
        str(soothe_home / "skills"),
        str(Path.home() / ".agents" / "skills"),
    ]


def resolve_warehouse_paths(soothe_home: Path, configured: list[str]) -> list[str]:
    """Prepend default warehouse roots when not already configured."""
    warehouse_paths = list(configured)
    existing = {str(Path(path).expanduser().resolve()) for path in warehouse_paths}
    for default in reversed(_default_warehouse_paths(soothe_home)):
        resolved = str(Path(default).expanduser().resolve())
        if resolved in existing:
            continue
        warehouse_paths.insert(0, default)
        existing.add(resolved)
    return warehouse_paths


class SkillifyService:
    """Process-scoped skill warehouse indexer and semantic retriever."""

    def __init__(
        self,
        config: SootheConfig,
        *,
        indexer_event_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._config = config
        self._started = False
        self._start_lock = asyncio.Lock()
        self._inflight: dict[str, asyncio.Task[SkillBundle]] = {}

        skillify_opts = config.skillify
        soothe_home = Path(getattr(config, "home", SOOTHE_HOME))
        warehouse_paths = resolve_warehouse_paths(soothe_home, list(skillify_opts.warehouse_paths))

        self._vector_store = config.create_vector_store_for_role("skillify")
        embeddings_factory = config.create_embedding_model
        warehouse = SkillWarehouse(paths=warehouse_paths)

        self._indexer = SkillIndexer(
            warehouse=warehouse,
            vector_store=self._vector_store,
            embeddings=embeddings_factory,
            interval_seconds=skillify_opts.index_interval_seconds,
            collection=skillify_opts.index_collection,
            embedding_dims=config.embedding_dims,
            event_callback=indexer_event_callback,
        )

        configure_vector_search_concurrency(
            config.progressive_skills.max_concurrent_vector_searches
        )

        self._retriever = SkillRetriever(
            vector_store=self._vector_store,
            embeddings=embeddings_factory,
            top_k=skillify_opts.retrieval_top_k,
            ready_event=self._indexer.ready_event,
            total_indexed_fn=lambda: self._indexer.total_indexed,
        )

    @property
    def retriever(self) -> SkillRetriever:
        """Underlying retriever for direct access (e.g. Weaver plugin)."""
        return self._retriever

    @property
    def is_ready(self) -> bool:
        return self._indexer.is_ready

    async def start(self) -> None:
        """Start the background indexer."""
        async with self._start_lock:
            if self._started:
                return
            await self._indexer.start()
            self._started = True
            logger.info("SkillifyService started")

    async def stop(self) -> None:
        """Stop the background indexer without closing shared PG pools."""
        async with self._start_lock:
            if not self._started:
                return
            await self._indexer.stop()
            self._started = False
            logger.info("SkillifyService stopped")

    async def retrieve(self, query: str, *, top_k: int | None = None) -> SkillBundle:
        """Semantic search over indexed skills with in-flight query deduplication."""
        if not self._started:
            await self.start()

        limit = top_k or self._config.skillify.retrieval_top_k
        key = f"{query.strip().lower()}|{limit}"
        existing = self._inflight.get(key)
        if existing is not None:
            return await asyncio.shield(existing)

        async def _do_retrieve() -> SkillBundle:
            return await self._retriever.retrieve(query, top_k=top_k)

        task = asyncio.create_task(_do_retrieve())
        self._inflight[key] = task
        try:
            return await task
        finally:
            self._inflight.pop(key, None)


def get_skillify_service(config: SootheConfig) -> SkillifyService | None:
    """Return the shared SkillifyService instance, creating it if needed (not started).

    Returns ``None`` when Skillify is disabled or vector store/embeddings are unavailable.
    """
    global _shared_instance  # noqa: PLW0603

    if not config.skillify.enabled:
        return None

    if _shared_instance is not None:
        return _shared_instance

    try:
        _shared_instance = SkillifyService(config)
        return _shared_instance
    except Exception:
        logger.debug("[Skillify] service unavailable", exc_info=True)
        return None


async def start_skillify_service(
    config: SootheConfig,
    *,
    indexer_event_callback: Callable[[dict[str, Any]], None] | None = None,
) -> SkillifyService | None:
    """Start or return the process-wide SkillifyService singleton."""
    global _shared_instance  # noqa: PLW0603

    if not config.skillify.enabled:
        return None

    async with _shared_lock:
        if _shared_instance is None:
            try:
                _shared_instance = SkillifyService(
                    config,
                    indexer_event_callback=indexer_event_callback,
                )
            except Exception:
                logger.debug("[Skillify] service unavailable", exc_info=True)
                return None
        if not _shared_instance._started:  # noqa: SLF001
            await _shared_instance.start()
        return _shared_instance


async def stop_skillify_service() -> None:
    """Stop and clear the process-wide SkillifyService singleton."""
    global _shared_instance  # noqa: PLW0603

    async with _shared_lock:
        if _shared_instance is None:
            return
        await _shared_instance.stop()
        _shared_instance = None
