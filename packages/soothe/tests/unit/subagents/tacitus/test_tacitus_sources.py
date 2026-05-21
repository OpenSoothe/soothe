"""Unit tests for Tacitus gather sources (academic)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.subagents.tacitus.protocol import GatherContext
from soothe.subagents.tacitus.sources.academic import AcademicSearchSource


@pytest.fixture
def gather_context() -> GatherContext:
    return GatherContext(topic="test")


class TestAcademicAuthCircuitBreaker:
    """Academic source stops after first DeepXiv auth failure."""

    async def test_skips_follow_up_queries_after_auth_error(self, gather_context: GatherContext):
        source = AcademicSearchSource()
        mock_tool = MagicMock()
        mock_tool.name = "deepxiv_search"
        mock_tool._arun = AsyncMock(
            return_value="Error: Invalid DeepXiv token. Set DEEPXIV_API_KEY",
        )
        source._deepxiv_tool = mock_tool
        source._tools_loaded = True

        first = await source.query("MoE papers", gather_context)
        second = await source.query("Mamba SSM", gather_context)

        assert first == []
        assert second == []
        assert mock_tool._arun.await_count == 1
        assert source._auth_failed is True
