"""Tests for SkillifyService daemon-shared lifecycle."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from soothe.config import SootheConfig
from soothe_sdk.skillify.models import SkillBundle

from soothe_daemon.skillify import (
    get_skillify_service,
    start_skillify_service,
    stop_skillify_service,
)
from soothe_daemon.skillify import service as skillify_service_module
from soothe_daemon.skillify.service import SkillifyService


@pytest.fixture(autouse=True)
async def _reset_skillify_singleton() -> None:
    await stop_skillify_service()
    yield
    await stop_skillify_service()


@pytest.mark.asyncio
async def test_start_skillify_service_returns_singleton() -> None:
    config = SootheConfig()
    config.skillify.enabled = True

    with patch.object(SootheConfig, "create_vector_store_for_role", return_value=MagicMock()):
        with patch.object(SootheConfig, "create_embedding_model", return_value=MagicMock()):
            with patch(
                "soothe_daemon.skillify.service.SkillIndexer.start",
                new_callable=AsyncMock,
            ):
                first = await start_skillify_service(config)
                second = await start_skillify_service(config)

    assert first is not None
    assert first is second


@pytest.mark.asyncio
async def test_get_skillify_service_disabled_returns_none() -> None:
    config = SootheConfig()
    config.skillify.enabled = False

    assert get_skillify_service(config) is None


@pytest.mark.asyncio
async def test_stop_skillify_service_clears_singleton() -> None:
    config = SootheConfig()
    config.skillify.enabled = True

    with patch.object(SootheConfig, "create_vector_store_for_role", return_value=MagicMock()):
        with patch.object(SootheConfig, "create_embedding_model", return_value=MagicMock()):
            with patch(
                "soothe_daemon.skillify.service.SkillIndexer.start",
                new_callable=AsyncMock,
            ):
                with patch(
                    "soothe_daemon.skillify.service.SkillIndexer.stop",
                    new_callable=AsyncMock,
                ):
                    service = await start_skillify_service(config)
                    assert service is not None
                    await stop_skillify_service()
                    assert skillify_service_module._shared_instance is None


@pytest.mark.asyncio
async def test_retrieve_deduplicates_inflight_queries() -> None:
    config = SootheConfig()

    with patch.object(SootheConfig, "create_vector_store_for_role", return_value=MagicMock()):
        with patch.object(SootheConfig, "create_embedding_model", return_value=MagicMock()):
            service = SkillifyService(config)
            service._started = True  # noqa: SLF001
            service._retriever.retrieve = AsyncMock(  # noqa: SLF001
                return_value=SkillBundle(query="weather skills")
            )

            results = await asyncio.gather(
                service.retrieve("weather skills"),
                service.retrieve("weather skills"),
            )

    assert results[0].query == "weather skills"
    assert results[1].query == "weather skills"
    service._retriever.retrieve.assert_awaited_once()  # noqa: SLF001


def test_service_uses_configured_skillify_model_role_for_embeddings() -> None:
    config = SootheConfig(skillify={"model_role": "fast"})

    with patch.object(SootheConfig, "create_vector_store_for_role", return_value=MagicMock()):
        with patch.object(
            SootheConfig, "create_embedding_model", return_value=MagicMock()
        ) as create:
            service = SkillifyService(config)
            service._indexer._embeddings._factory()  # noqa: SLF001

    create.assert_called_once_with("fast")


@pytest.mark.asyncio
async def test_indexer_stop_skips_shared_pool_close() -> None:
    from soothe_daemon.skillify.indexer import SkillIndexer

    vector_store = MagicMock()
    vector_store._owns_pool = False
    vector_store.close = AsyncMock()
    warehouse = MagicMock()
    warehouse.scan.return_value = []

    indexer = SkillIndexer(
        warehouse=warehouse,
        vector_store=vector_store,
        embeddings=MagicMock(),
    )
    indexer._task = asyncio.create_task(asyncio.sleep(3600))  # noqa: SLF001

    await indexer.stop()

    vector_store.close.assert_not_awaited()
