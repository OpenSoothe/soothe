"""Unit tests for LazyCoreAgent (IG-506)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from soothe.foundation.coreagent.coding.lazy import LazyCoreAgent


def test_lazy_core_agent_defers_factory_until_graph_access() -> None:
    """Factory runs only when Layer-1 surface is accessed."""
    calls = 0
    mock_agent = MagicMock()
    mock_agent.graph = MagicMock()

    def factory() -> MagicMock:
        nonlocal calls
        calls += 1
        return mock_agent

    lazy = LazyCoreAgent(factory)
    assert calls == 0
    assert lazy.is_materialized is False

    _ = lazy.graph
    assert calls == 1
    assert lazy.is_materialized is True

    _ = lazy.graph
    assert calls == 1


@pytest.mark.asyncio
async def test_lazy_core_agent_runs_materialize_hook() -> None:
    """Async materialize invokes optional hook once."""
    hook_calls = 0
    mock_agent = MagicMock()

    async def hook(_agent: MagicMock) -> None:
        nonlocal hook_calls
        hook_calls += 1

    lazy = LazyCoreAgent(lambda: mock_agent, materialize_hook=hook)
    agent = await lazy.amaterialize()

    assert agent is mock_agent
    assert hook_calls == 1
