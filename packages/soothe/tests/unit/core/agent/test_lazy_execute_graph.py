"""Unit tests for lazy execute graph compilation (IG-506)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from soothe.foundation.coreagent import CoreAgent
from soothe.foundation.sloop.engine.executor import ephemeral_execute_stream_enabled


def test_execution_graph_compiles_lazily(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ephemeral execute twin compiles on first execution_graph access."""
    monkeypatch.setenv("SOOTHE_EPHEMERAL_EXECUTE_STREAM", "1")
    assert ephemeral_execute_stream_enabled() is True

    main_graph = MagicMock(name="main")
    execute_graph = MagicMock(name="execute")
    calls = 0

    def compiler() -> MagicMock:
        nonlocal calls
        calls += 1
        return execute_graph

    agent = CoreAgent(
        graph=main_graph,
        config=MagicMock(),
        execute_graph_compiler=compiler,
    )

    assert calls == 0
    assert agent.execution_graph is execute_graph
    assert calls == 1
    assert agent.execution_graph is execute_graph
    assert calls == 1
