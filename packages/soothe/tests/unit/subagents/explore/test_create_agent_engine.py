"""Smoke tests for explore engine built with LangChain ``create_agent``."""

from __future__ import annotations

from unittest.mock import MagicMock

from soothe.subagents.explore.engine import build_explore_engine
from soothe.subagents.explore.schemas import ExploreSubagentConfig


def test_build_explore_engine_returns_compiled_graph() -> None:
    """Engine factory wires readonly tools and middleware into ``create_agent``."""
    model = MagicMock()
    model.bind_tools = MagicMock(return_value=model)
    graph = build_explore_engine(model, ExploreSubagentConfig(), "/tmp")
    assert hasattr(graph, "invoke")
