"""Tests for TUI daemon bootstrap and resume behavior."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from soothe.config import SootheConfig
from soothe.ux.cli.commands.thread_cmd import thread_continue
from soothe.ux.tui import app as tui_app
from soothe.ux.tui.utils import make_welcome_banner, shorten_display_path


def test_start_daemon_uses_external_process(monkeypatch, tmp_path: Path) -> None:
    spawned: list[list[str]] = []
    config = SootheConfig()

    monkeypatch.setattr(tui_app.SootheDaemon, "is_running", staticmethod(lambda: False))
    monkeypatch.setattr(tui_app.SootheDaemon, "_is_port_live", staticmethod(lambda h, p: True))
    monkeypatch.setattr(tui_app.time, "sleep", lambda _delay: None)
    monkeypatch.setattr(tui_app.subprocess, "Popen", lambda cmd, **_kwargs: spawned.append(cmd))

    tui_app._start_daemon_in_background(config, config_path="/tmp/custom.yml")

    assert spawned
    assert spawned[0][:3] == [spawned[0][0], "-m", "soothe.daemon"]
    assert "--config" in spawned[0]
    assert "/tmp/custom.yml" in spawned[0]


def test_shorten_display_path() -> None:
    short = "/a/b"
    assert shorten_display_path(short, max_len=100) == short
    long_p = "/" + "x" * 100
    out = shorten_display_path(long_p, max_len=40)
    assert len(out) <= 40
    assert "..." in out


def test_make_welcome_banner_contains_title_and_logo() -> None:
    from rich.panel import Panel

    banner = make_welcome_banner(workspace="/tmp/proj", provider="openai", model_name="gpt-4o")
    assert isinstance(banner, Panel)
    inner_plain = banner.renderable.plain
    assert "╭────────╮" in inner_plain
    assert "/tmp/proj" in inner_plain
    assert "openai" in inner_plain
    assert "gpt-4o" in inner_plain
    title_plain = banner.title.plain if hasattr(banner.title, "plain") else str(banner.title)
    assert "Welcome aboard" in title_plain


def test_start_daemon_skips_when_already_running(monkeypatch) -> None:
    spawned = {"count": 0}
    monkeypatch.setattr(tui_app.SootheDaemon, "is_running", staticmethod(lambda: True))
    monkeypatch.setattr(tui_app.subprocess, "Popen", lambda *args, **kwargs: spawned.__setitem__("count", 1))

    tui_app._start_daemon_in_background(SootheConfig())

    assert spawned["count"] == 0


class _FakeConversationPanel:
    def __init__(self) -> None:
        self.entries: list[Any] = []
        self.cleared = 0

    def append_entry(self, renderable: Any) -> None:
        self.entries.append(renderable)

    def update_last_entry(self, renderable: Any) -> None:
        if self.entries:
            self.entries[-1] = renderable
        else:
            self.entries.append(renderable)

    def clear(self) -> None:
        self.cleared += 1
        self.entries.clear()
