"""Tests for IG-477 ephemeral execute graph selection."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from soothe.foundation.core.agent._core import CoreAgent
from soothe.foundation.sloop.engine.executor import ephemeral_execute_stream_enabled


def test_ephemeral_execute_stream_enabled_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SOOTHE_EPHEMERAL_EXECUTE_STREAM", raising=False)
    assert ephemeral_execute_stream_enabled() is True


def test_ephemeral_execute_stream_disabled_by_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOOTHE_EPHEMERAL_EXECUTE_STREAM", "0")
    assert ephemeral_execute_stream_enabled() is False


def test_core_agent_execution_graph_prefers_twin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SOOTHE_EPHEMERAL_EXECUTE_STREAM", raising=False)
    main = MagicMock(name="main_graph")
    twin = MagicMock(name="execute_graph")
    from soothe.config import SootheConfig

    agent = CoreAgent(
        graph=main,
        config=SootheConfig(),
        execute_graph=twin,
    )
    assert agent.execution_graph is twin


def test_core_agent_execution_graph_falls_back_without_twin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SOOTHE_EPHEMERAL_EXECUTE_STREAM", raising=False)
    main = MagicMock(name="main_graph")
    from soothe.config import SootheConfig

    agent = CoreAgent(graph=main, config=SootheConfig())
    assert agent.execution_graph is main
