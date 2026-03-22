"""Tests for TUI daemon bootstrap behavior."""

from __future__ import annotations

from pathlib import Path

from soothe.config import SootheConfig
from soothe.ux.tui import app as tui_app


def test_start_daemon_uses_external_process(monkeypatch, tmp_path: Path) -> None:
    spawned: list[list[str]] = []
    ready_socket = tmp_path / "soothe.sock"
    ready_socket.write_text("")

    monkeypatch.setattr(tui_app.SootheDaemon, "is_running", staticmethod(lambda: False))
    monkeypatch.setattr(tui_app, "socket_path", lambda: ready_socket)
    monkeypatch.setattr(tui_app.subprocess, "Popen", lambda cmd, **_kwargs: spawned.append(cmd))

    tui_app._start_daemon_in_background(SootheConfig(), config_path="/tmp/custom.yml")

    assert spawned
    assert spawned[0][:3] == [spawned[0][0], "-m", "soothe.daemon"]
    assert "--config" in spawned[0]
    assert "/tmp/custom.yml" in spawned[0]


def test_start_daemon_skips_when_already_running(monkeypatch) -> None:
    spawned = {"count": 0}
    monkeypatch.setattr(tui_app.SootheDaemon, "is_running", staticmethod(lambda: True))
    monkeypatch.setattr(tui_app.subprocess, "Popen", lambda *args, **kwargs: spawned.__setitem__("count", 1))

    tui_app._start_daemon_in_background(SootheConfig())

    assert spawned["count"] == 0
