"""Tests for daemon port PID lookup and stop_running orphan handling."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from soothe_daemon.bootstrap.port_lookup import LSOF_PORT_LOOKUP_TIMEOUT_S, find_listening_pid
from soothe_daemon.server.core import SootheDaemon


def test_lsof_port_lookup_timeout_is_generous() -> None:
    """Regression: 0.3s timed out on macOS and left orphans unstoppable."""
    assert LSOF_PORT_LOOKUP_TIMEOUT_S >= 1.0


def test_find_listening_pid_returns_first_listen_pid() -> None:
    completed = MagicMock()
    completed.returncode = 0
    completed.stdout = "111\n222\n"
    with patch("soothe_daemon.bootstrap.port_lookup.subprocess.run", return_value=completed) as run:
        assert find_listening_pid(8765) == 111
    run.assert_called_once()
    assert run.call_args.kwargs["timeout"] == LSOF_PORT_LOOKUP_TIMEOUT_S


def test_find_listening_pid_swallows_timeout() -> None:
    with patch(
        "soothe_daemon.bootstrap.port_lookup.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="lsof", timeout=2.0),
    ):
        assert find_listening_pid(8765) is None


def test_stop_running_kills_orphan_by_port(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("soothe_daemon.server.core.pid_path", lambda: tmp_path / "soothed.pid")
    monkeypatch.setattr(
        "soothe_daemon.server.core.SootheDaemon._default_ws_endpoint",
        staticmethod(lambda: ("127.0.0.1", 8765)),
    )
    monkeypatch.setattr(
        "soothe_daemon.server.core.SootheDaemon._find_port_process",
        staticmethod(lambda _port: 94448),
    )
    kills: list[tuple[int, int]] = []

    def _fake_kill(pid: int, sig: int) -> None:
        kills.append((pid, sig))
        if sig == 0:
            raise ProcessLookupError

    monkeypatch.setattr("soothe_daemon.server.core.os.kill", _fake_kill)

    assert SootheDaemon.stop_running(timeout=0.5) is True
    assert any(pid == 94448 for pid, _sig in kills)


def test_stop_running_keeps_pid_file_when_stop_fails(tmp_path: Path, monkeypatch) -> None:
    pid_file = tmp_path / "soothed.pid"
    pid_file.write_text("12345")
    monkeypatch.setattr("soothe_daemon.server.core.pid_path", lambda: pid_file)
    monkeypatch.setattr(
        "soothe_daemon.server.core.SootheDaemon._default_ws_endpoint",
        staticmethod(lambda: ("127.0.0.1", 8765)),
    )
    monkeypatch.setattr(
        "soothe_daemon.server.core.SootheDaemon._find_port_process",
        staticmethod(lambda _port: None),
    )
    monkeypatch.setattr("soothe_daemon.server.core.os.kill", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "soothe_daemon.server.core.SootheDaemon._wait_for_pid_exit",
        staticmethod(lambda *_a, **_k: False),
    )

    assert SootheDaemon.stop_running(timeout=0.1) is False
    assert pid_file.exists()
    assert pid_file.read_text() == "12345"


def test_stop_running_cleans_pid_file_after_success(tmp_path: Path, monkeypatch) -> None:
    pid_file = tmp_path / "soothed.pid"
    pid_file.write_text("12345")
    monkeypatch.setattr("soothe_daemon.server.core.pid_path", lambda: pid_file)
    monkeypatch.setattr("soothe_daemon.bootstrap.singleton.pid_path", lambda: pid_file)
    monkeypatch.setattr("soothe_daemon.server.core.os.kill", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "soothe_daemon.server.core.SootheDaemon._wait_for_pid_exit",
        staticmethod(lambda *_a, **_k: True),
    )

    assert SootheDaemon.stop_running(timeout=0.1) is True
    assert not pid_file.exists()
