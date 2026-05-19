"""Tests for TUI workspace propagation into app startup."""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any

import soothe_cli.tui.app._module_init as source_module
from soothe_cli.tui import app as app_module


def test_run_textual_tui_uses_caller_cwd(monkeypatch) -> None:
    """run_textual_tui passes caller's cwd (os.getcwd()), not config.workspace_dir.

    Per IG-344, the TUI uses the caller's actual cwd for thread isolation,
    not the daemon-level default workspace (~/.soothe/Workspace).
    """
    captured: dict[str, Any] = {}

    async def fake_run_textual_app(**kwargs: Any) -> app_module.AppResult:
        captured.update(kwargs)
        return app_module.AppResult(return_code=0, loop_id=None)

    # Patch source module (where run_textual_tui calls run_textual_app locally)
    monkeypatch.setattr(source_module, "run_textual_app", fake_run_textual_app)

    # config.workspace_dir is ignored - cwd comes from os.getcwd()
    cfg = SimpleNamespace(workspace_dir="/some/ignored/path")
    expected_cwd = os.getcwd()

    app_module.run_textual_tui(cfg)

    assert captured["cwd"] == expected_cwd
