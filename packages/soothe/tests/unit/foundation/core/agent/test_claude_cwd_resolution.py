"""Tests for ClaudeCoreAgent dynamic cwd resolution."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from soothe.foundation.core.agent.claude_core_agent import _resolve_claude_cwd


def test_resolve_prefers_configurable_workspace() -> None:
    """RunnableConfig configurable.workspace wins over fallback."""
    config = {"configurable": {"workspace": "/tmp/repo-from-thread"}}
    out = _resolve_claude_cwd(config, "/fallback/ignored")
    assert out.endswith("repo-from-thread")


@pytest.mark.skipif(
    True,
    reason="FrameworkFilesystem integration test requires soothe daemon context",
)
def test_resolve_uses_framework_filesystem_when_no_config_workspace() -> None:
    """ContextVar workspace is second priority (requires soothe daemon)."""
    from soothe.foundation.workspace import FrameworkFilesystem

    try:
        FrameworkFilesystem.set_current_workspace("/tmp/from-contextvar")
        out = _resolve_claude_cwd(None, "/fallback/ignored")
    finally:
        FrameworkFilesystem.clear_current_workspace()
    assert Path(out).name == "from-contextvar"


def test_resolve_falls_back_when_no_dynamic_workspace() -> None:
    """Factory fallback when config and ContextVar are empty."""
    with patch(
        "soothe.foundation.core.agent.claude_core_agent._get_langgraph_configurable",
        return_value={},
    ):
        out = _resolve_claude_cwd(None, "/tmp/fallback-only")
    assert "fallback-only" in out
