"""Shared Skillify indexer/retriever runtime for subagent and skill search."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from soothe.config import SOOTHE_HOME, SubagentConfig

from .indexer import SkillIndexer
from .retriever import SkillRetriever, configure_vector_search_concurrency
from .schemas import SkillifySubagentConfig
from .warehouse import SkillWarehouse

if TYPE_CHECKING:
    from soothe.config import SootheConfig

logger = logging.getLogger(__name__)

_INDEXER: SkillIndexer | None = None


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


def _start_background_indexer(indexer: SkillIndexer) -> None:
    try:
        loop = asyncio.get_running_loop()
        indexer._start_task = loop.create_task(indexer.start())  # noqa: SLF001
    except RuntimeError:
        pass


def get_skillify_retriever(
    config: SootheConfig,
    *,
    indexer_event_callback: Callable[[dict[str, Any]], None] | None = None,
) -> SkillRetriever | None:
    """Return a shared SkillRetriever, starting the background indexer if needed.

    Returns ``None`` when Skillify is disabled or vector store/embeddings are unavailable.
    """
    global _INDEXER  # noqa: PLW0603

    sub_cfg = config.subagents.get("skillify", SubagentConfig())
    if not sub_cfg.enabled:
        return None

    try:
        skillify_opts = SkillifySubagentConfig(**sub_cfg.config)
        soothe_home = Path(getattr(config, "home", SOOTHE_HOME))
        warehouse_paths = resolve_warehouse_paths(soothe_home, list(skillify_opts.warehouse_paths))

        vector_store = config.create_vector_store_for_role("skillify")
        embeddings_factory = config.create_embedding_model
        warehouse = SkillWarehouse(paths=warehouse_paths)

        if _INDEXER is None:
            _INDEXER = SkillIndexer(
                warehouse=warehouse,
                vector_store=vector_store,
                embeddings=embeddings_factory,
                interval_seconds=skillify_opts.index_interval_seconds,
                collection=skillify_opts.index_collection,
                embedding_dims=config.embedding_dims,
                event_callback=indexer_event_callback,
            )
            _start_background_indexer(_INDEXER)

        configure_vector_search_concurrency(
            config.progressive_skills.max_concurrent_vector_searches
        )

        return SkillRetriever(
            vector_store=vector_store,
            embeddings=embeddings_factory,
            top_k=skillify_opts.retrieval_top_k,
            ready_event=_INDEXER.ready_event if _INDEXER else None,
            total_indexed_fn=(lambda: _INDEXER.total_indexed if _INDEXER else 0),
        )
    except Exception:
        logger.debug("[Skillify] retriever unavailable", exc_info=True)
        return None
