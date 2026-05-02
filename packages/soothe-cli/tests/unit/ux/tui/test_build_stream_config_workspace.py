"""Tests for LangGraph stream config workspace (IG-341)."""

from __future__ import annotations

from pathlib import Path

from soothe_cli.tui.config import build_stream_config


def test_build_stream_config_sets_workspace_from_argument(tmp_path: Path) -> None:
    """Explicit workspace is resolved and placed under configurable."""
    ws = tmp_path / "proj"
    ws.mkdir()
    cfg = build_stream_config("tid-1", None, workspace=str(ws))
    assert cfg["configurable"]["thread_id"] == "tid-1"
    assert cfg["configurable"]["workspace"] == str(ws.resolve())


def test_build_stream_config_workspace_defaults_to_cwd(monkeypatch, tmp_path: Path) -> None:
    """When workspace is omitted, configurable.workspace matches cwd."""
    monkeypatch.chdir(tmp_path)
    cfg = build_stream_config("tid-2", None)
    assert cfg["configurable"]["workspace"] == str(tmp_path.resolve())
