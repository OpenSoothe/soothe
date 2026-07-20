"""Unit tests for kill_process daemon/self protection (IG-665)."""

from __future__ import annotations

import os
import signal
from pathlib import Path

from soothe_nano.toolkits.execution import (
    KillProcessTool,
    _kill_process_tree,
    _protected_kill_refusal,
)


def test_kill_process_refuses_self_pid() -> None:
    tool = KillProcessTool()
    result = tool._run(os.getpid())
    assert "refusing to kill" in result
    assert "current agent/daemon" in result


def test_protected_kill_refusal_soothed_pidfile(tmp_path: Path, monkeypatch) -> None:
    pid_file = tmp_path / "soothed.pid"
    pid_file.write_text("424242\n", encoding="utf-8")
    monkeypatch.setattr("soothe_nano.config.SOOTHE_HOME", tmp_path)

    msg = _protected_kill_refusal(424242)
    assert msg is not None
    assert "soothed.pid" in msg

    tool = KillProcessTool()
    result = tool._run(424242)
    assert "soothed.pid" in result


def test_protected_kill_refusal_ws_listener(monkeypatch) -> None:
    monkeypatch.setattr(
        "soothe_nano.toolkits.execution._soothed_pid_from_pidfile",
        lambda: None,
    )
    monkeypatch.setattr(
        "soothe_nano.toolkits.execution._pid_listening_on_port",
        lambda _port: 55555,
    )
    msg = _protected_kill_refusal(55555)
    assert msg is not None
    assert "8765" in msg


def test_kill_process_tree_avoids_killpg_on_own_group(monkeypatch) -> None:
    kills: list[tuple[int, int]] = []

    monkeypatch.setattr("soothe_nano.toolkits.execution.os.getpgid", lambda _pid: 77)
    monkeypatch.setattr(
        "soothe_nano.toolkits.execution.os.kill",
        lambda pid, sig: kills.append((pid, sig)),
    )

    def boom(*_a, **_k):
        raise AssertionError("killpg must not run for own process group")

    monkeypatch.setattr("soothe_nano.toolkits.execution.os.killpg", boom)
    _kill_process_tree(99, sig=signal.SIGTERM)
    assert kills == [(99, signal.SIGTERM)]


def test_kill_process_tree_uses_killpg_for_foreign_group(monkeypatch) -> None:
    killpg_calls: list[tuple[int, int]] = []

    def fake_getpgid(pid: int) -> int:
        return 10 if pid == 0 else 99

    monkeypatch.setattr("soothe_nano.toolkits.execution.os.getpgid", fake_getpgid)
    monkeypatch.setattr(
        "soothe_nano.toolkits.execution.os.killpg",
        lambda pgid, sig: killpg_calls.append((pgid, sig)),
    )
    _kill_process_tree(42, sig=signal.SIGKILL)
    assert killpg_calls == [(99, signal.SIGKILL)]
