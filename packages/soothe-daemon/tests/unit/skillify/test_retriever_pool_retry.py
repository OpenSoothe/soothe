"""Tests for Skillify retriever pool retry."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe_daemon.skillify.retriever import SkillRetriever


class _FakeEmbeddings:
    async def aembed_query(self, text: str) -> list[float]:
        return [0.1, 0.2]


@pytest.mark.asyncio
async def test_search_retries_on_pool_timeout() -> None:
    vector_store = MagicMock()
    vector_store.search = AsyncMock(
        side_effect=[
            Exception("PoolTimeout: couldn't get a connection after 30.00 sec"),
            [],
        ]
    )

    retriever = SkillRetriever(vector_store=vector_store, embeddings=_FakeEmbeddings(), top_k=3)
    bundle = await retriever.retrieve("test query")

    assert bundle.query == "test query"
    assert vector_store.search.await_count == 2


@pytest.mark.asyncio
async def test_search_raises_after_retry_exhausted() -> None:
    vector_store = MagicMock()
    vector_store.search = AsyncMock(
        side_effect=Exception("PoolTimeout: couldn't get a connection after 30.00 sec")
    )

    retriever = SkillRetriever(vector_store=vector_store, embeddings=_FakeEmbeddings(), top_k=3)
    bundle = await retriever.retrieve("test query")

    assert bundle.query == "test query"
    assert vector_store.search.await_count == 3
