"""Tests for Skillify retriever query normalization."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe_daemon.skillify.retriever import SkillRetriever


def _fake_embeddings() -> SimpleNamespace:
    return SimpleNamespace(
        aembed_query=AsyncMock(return_value=[0.1, 0.2]),
        aembed_documents=AsyncMock(return_value=[]),
    )


@pytest.mark.asyncio
async def test_retrieve_normalizes_block_list_query_before_embedding() -> None:
    vector_store = MagicMock()
    vector_store.search = AsyncMock(return_value=[])

    embeddings = _fake_embeddings()
    retriever = SkillRetriever(vector_store=vector_store, embeddings=embeddings)

    block_query = [{"type": "text", "text": "EXECUTION TASK: Run make test"}]
    await retriever.retrieve(block_query)  # type: ignore[arg-type]

    embeddings.aembed_query.assert_awaited_once_with("EXECUTION TASK: Run make test")
