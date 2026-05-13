"""Explore wire middleware: thread workspace on state for shell cwd (IG-328)."""

from __future__ import annotations

from unittest.mock import MagicMock

from langchain_core.messages import HumanMessage

from soothe.subagents.explore.middleware import (
    ExploreWireMiddleware,
    _thread_workspace_from_agent_runtime,
)


def test_thread_workspace_from_runtime_config() -> None:
    """Reads workspace from Runtime.config.configurable."""
    runtime = MagicMock()
    runtime.config = {"configurable": {"workspace": "/client/proj"}}
    assert _thread_workspace_from_agent_runtime(runtime) == "/client/proj"


def test_explore_wire_before_agent_seeds_workspace() -> None:
    """before_agent copies configurable workspace onto graph state when missing."""
    mw = ExploreWireMiddleware(thoroughness="medium", resolver_workspace="/fallback")
    runtime = MagicMock()
    runtime.config = {"configurable": {"workspace": "/thread/ws"}}
    state: dict = {
        "messages": [HumanMessage(content="find widgets")],
        "explore_wire_started": True,
    }
    out = mw.before_agent(state, runtime)
    assert out is not None
    assert out.get("workspace") == "/thread/ws"
