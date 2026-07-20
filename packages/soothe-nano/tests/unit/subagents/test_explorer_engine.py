"""Unit tests for explorer graph configuration."""

from __future__ import annotations

from types import SimpleNamespace

from soothe_nano.subagents.explore import engine
from soothe_nano.subagents.explore.schemas import ExploreSubagentConfig


class _FakeGraph:
    def __init__(self) -> None:
        self.last_config: dict | None = None

    def with_config(self, **kwargs):  # type: ignore[no-untyped-def]
        self.last_config = kwargs
        return self


def test_build_explorer_engine_applies_default_recursion_limit(monkeypatch) -> None:
    fake_graph = _FakeGraph()
    monkeypatch.setattr(engine, "create_agent", lambda **_kwargs: fake_graph)
    monkeypatch.setattr(engine, "get_explore_tools", lambda **_kwargs: [])
    monkeypatch.setattr(engine, "build_explore_middleware_stack", lambda *_args, **_kwargs: [])

    out = engine.build_explore_engine(
        model=SimpleNamespace(),
        config=ExploreSubagentConfig(),
        workspace="/tmp",
    )

    assert out is fake_graph
    assert fake_graph.last_config == {"recursion_limit": 999}


def test_build_explorer_engine_applies_custom_recursion_limit(monkeypatch) -> None:
    fake_graph = _FakeGraph()
    monkeypatch.setattr(engine, "create_agent", lambda **_kwargs: fake_graph)
    monkeypatch.setattr(engine, "get_explore_tools", lambda **_kwargs: [])
    monkeypatch.setattr(engine, "build_explore_middleware_stack", lambda *_args, **_kwargs: [])

    out = engine.build_explore_engine(
        model=SimpleNamespace(),
        config=ExploreSubagentConfig(recursion_limit=1234),
        workspace="/tmp",
    )

    assert out is fake_graph
    assert fake_graph.last_config == {"recursion_limit": 1234}
