"""Tests for unified workspace runtime resolution."""

from __future__ import annotations

from contextvars import Token
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from soothe_nano.workspace.workspace_api import resolve_workspace_for_tool_execution
from soothe_nano.workspace.workspace_filesystem import FrameworkFilesystem


@pytest.fixture
def workspace_token() -> Token[Path | None]:
    """Set and restore a ContextVar workspace for tests."""
    token = FrameworkFilesystem.set_current_workspace("/ctx/workspace")
    yield token
    FrameworkFilesystem.clear_current_workspace(token)


def test_prefers_runtime_configurable_workspace() -> None:
    runtime = MagicMock()
    runtime.config = {"configurable": {"workspace": "/client/from_config"}}
    runtime.state = {"workspace": "/client/from_state", "messages": []}

    resolved = resolve_workspace_for_tool_execution(runtime=runtime, use_langgraph_config=False)

    assert resolved == Path("/client/from_config")


def test_falls_back_to_state_workspace() -> None:
    runtime = MagicMock()
    runtime.config = {"configurable": {"thread_id": "t1"}}
    runtime.state = {"workspace": "/thread/explore/ws", "messages": []}

    resolved = resolve_workspace_for_tool_execution(runtime=runtime, use_langgraph_config=False)

    assert resolved == Path("/thread/explore/ws")


def test_falls_back_to_loop_human_message_workspace() -> None:
    runtime = MagicMock()
    runtime.config = {"configurable": {"thread_id": "t1"}}
    runtime.state = {
        "messages": [SimpleNamespace(content="Execute: x", workspace="/client/from_state")]
    }

    resolved = resolve_workspace_for_tool_execution(runtime=runtime, use_langgraph_config=False)

    assert resolved == Path("/client/from_state")


def test_uses_contextvar_when_runtime_has_no_workspace(workspace_token: Token[Path | None]) -> None:
    runtime = MagicMock()
    runtime.config = {"configurable": {"thread_id": "t1"}}
    runtime.state = {"messages": []}

    resolved = resolve_workspace_for_tool_execution(runtime=runtime, use_langgraph_config=False)

    assert resolved == Path("/ctx/workspace")


def test_static_fallback_last() -> None:
    resolved = resolve_workspace_for_tool_execution(
        fallback="/daemon/default",
        use_langgraph_config=False,
    )

    assert resolved == Path("/daemon/default")


def test_explicit_config_and_state_without_runtime() -> None:
    resolved = resolve_workspace_for_tool_execution(
        config={"configurable": {"workspace": "/explicit/config"}},
        state={"workspace": "/explicit/state"},
        use_langgraph_config=False,
    )

    assert resolved == Path("/explicit/config")
