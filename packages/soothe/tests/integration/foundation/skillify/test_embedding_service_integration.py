"""Integration coverage for Skillify embedding behavior with local config wiring."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe.config import SootheConfig
from soothe.foundation.skillify.models import SkillBundle
from soothe.foundation.skillify.service import SkillifyService


class APIConnectionError(Exception):
    """Test double mirroring the OpenAI transient connection error class name."""


@pytest.mark.asyncio
async def test_local_config_wires_skillify_embedding_role_and_retries(
    test_config: SootheConfig,
) -> None:
    """Skillify should use local embedding role wiring and recover from transient failures."""
    # tests/conftest.py loads config/develop/config.yml as test_config by default.
    assert test_config.active_router_profile == "production"
    assert test_config.skillify.model_role == "embedding"
    assert test_config.resolve_model("embedding") == "openai:text-embedding-3-small"

    vector_store = MagicMock()
    vector_store.search = AsyncMock(return_value=[])

    class _FlakyEmbeddings:
        def __init__(self) -> None:
            self.calls = 0

        async def aembed_query(self, _text: str) -> list[float]:
            self.calls += 1
            if self.calls < 3:
                raise APIConnectionError("Connection error.")
            return [0.11, 0.22]

    flaky = _FlakyEmbeddings()

    with patch.object(SootheConfig, "create_vector_store_for_role", return_value=vector_store):
        with patch.object(SootheConfig, "create_embedding_model", return_value=flaky):
            service = SkillifyService(test_config)
            service._started = True  # noqa: SLF001
            service._retriever._ready_event.set()  # noqa: SLF001
            result = await service.retrieve("find markdown skill")

    assert result.query == "find markdown skill"
    assert isinstance(result, SkillBundle)
    assert flaky.calls == 3
    vector_store.search.assert_awaited_once()


@pytest.mark.asyncio
async def test_local_config_skillify_returns_empty_bundle_after_embedding_connection_error(
    test_config: SootheConfig,
) -> None:
    """Persistent embedding connection errors should not crash Skillify retrieval."""
    vector_store = MagicMock()
    vector_store.search = AsyncMock(return_value=[])

    class _AlwaysFailEmbeddings:
        async def aembed_query(self, _text: str) -> list[float]:
            raise APIConnectionError("Connection error.")

    with patch.object(SootheConfig, "create_vector_store_for_role", return_value=vector_store):
        with patch.object(
            SootheConfig, "create_embedding_model", return_value=_AlwaysFailEmbeddings()
        ):
            service = SkillifyService(test_config)
            service._started = True  # noqa: SLF001
            service._retriever._ready_event.set()  # noqa: SLF001
            result = await service.retrieve("find agent skill")

    assert result.query.startswith("[Embedding unavailable]")
    assert result.results == []
    assert result.total_indexed == 0
    vector_store.search.assert_not_awaited()
