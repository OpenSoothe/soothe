"""Tests for Claude subagent dynamic cwd (IG-201)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from soothe.subagents.claude.implementation import _resolve_claude_cwd


def test_resolve_prefers_configurable_workspace() -> None:
    """LangGraph configurable.workspace wins over fallback."""
    with patch("langgraph.config.get_config") as mock_gc:
        mock_gc.return_value = {"configurable": {"workspace": "/tmp/repo-from-thread"}}
        out = _resolve_claude_cwd("/fallback/ignored")
    assert out.endswith("repo-from-thread")


def test_resolve_uses_framework_filesystem_when_no_config_workspace() -> None:
    """ContextVar workspace is second priority."""
    with patch("langgraph.config.get_config") as mock_gc:
        mock_gc.return_value = {"configurable": {}}
        from soothe.core import FrameworkFilesystem

        try:
            FrameworkFilesystem.set_current_workspace("/tmp/from-contextvar")
            out = _resolve_claude_cwd("/fallback/ignored")
        finally:
            FrameworkFilesystem.clear_current_workspace()
    assert Path(out).name == "from-contextvar"


def test_resolve_falls_back_when_no_dynamic_workspace() -> None:
    """Factory fallback when config and ContextVar are empty."""
    with patch("langgraph.config.get_config") as mock_gc:
        mock_gc.side_effect = RuntimeError("no graph context")
        out = _resolve_claude_cwd("/tmp/fallback-only")
    assert "fallback-only" in out
