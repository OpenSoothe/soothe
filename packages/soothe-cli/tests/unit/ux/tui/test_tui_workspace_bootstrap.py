"""Tests for TUI workspace propagation into app startup."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from soothe_cli.tui import app as app_module


def test_run_textual_tui_forwards_non_default_workspace(monkeypatch, tmp_path: Path) -> None:
    """Configured workspace_dir is passed as TUI cwd."""
    captured: dict[str, Any] = {}

    async def fake_run_textual_app(**kwargs: Any) -> app_module.AppResult:
        captured.update(kwargs)
        return app_module.AppResult(return_code=0, thread_id=None)

    monkeypatch.setattr(app_module, "run_textual_app", fake_run_textual_app)

    cfg = SimpleNamespace(workspace_dir=str((tmp_path / "ws").resolve()))
    app_module.run_textual_tui(cfg)

    assert captured["cwd"] == cfg.workspace_dir


def test_run_textual_tui_keeps_default_cwd_when_workspace_is_dot(monkeypatch) -> None:
    """Default ``workspace_dir='.'`` keeps cwd unset for runtime resolution."""
    captured: dict[str, Any] = {}

    async def fake_run_textual_app(**kwargs: Any) -> app_module.AppResult:
        captured.update(kwargs)
        return app_module.AppResult(return_code=0, thread_id=None)

    monkeypatch.setattr(app_module, "run_textual_app", fake_run_textual_app)

    cfg = SimpleNamespace(workspace_dir=".")
    app_module.run_textual_tui(cfg)

    assert captured["cwd"] is None
