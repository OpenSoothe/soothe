"""Tests for host-injected daemon kill_process guards."""

from __future__ import annotations

from pathlib import Path

from soothe_nano.toolkits.execution import (
    _protected_kill_refusal,
    clear_protected_kill_hooks,
)

from soothe.security.daemon_kill_guards import (
    PRODUCTION_DAEMON_WS_PORT,
    daemon_protected_kill_refusal,
    ensure_daemon_kill_guards_installed,
)


def test_daemon_protected_kill_refusal_soothed_pidfile(tmp_path: Path, monkeypatch) -> None:
    pid_file = tmp_path / "soothed.pid"
    pid_file.write_text("424242\n", encoding="utf-8")
    monkeypatch.setattr("soothe.security.daemon_kill_guards.SOOTHE_HOME", tmp_path)

    msg = daemon_protected_kill_refusal(424242)
    assert msg is not None
    assert "soothed.pid" in msg


def test_daemon_protected_kill_refusal_ws_listener(monkeypatch) -> None:
    monkeypatch.setattr(
        "soothe.security.daemon_kill_guards._soothed_pid_from_pidfile",
        lambda: None,
    )
    monkeypatch.setattr(
        "soothe.security.daemon_kill_guards._pid_listening_on_port",
        lambda _port: 55555,
    )
    msg = daemon_protected_kill_refusal(55555)
    assert msg is not None
    assert str(PRODUCTION_DAEMON_WS_PORT) in msg


def test_ensure_daemon_kill_guards_installed_wires_nano_hook(monkeypatch) -> None:
    clear_protected_kill_hooks()
    # Reset install flag so ensure runs again
    monkeypatch.setattr("soothe.security.daemon_kill_guards._installed", False)
    monkeypatch.setattr(
        "soothe.security.daemon_kill_guards._soothed_pid_from_pidfile",
        lambda: 777,
    )
    monkeypatch.setattr(
        "soothe.security.daemon_kill_guards._pid_listening_on_port",
        lambda _port: None,
    )

    ensure_daemon_kill_guards_installed()
    try:
        msg = _protected_kill_refusal(777)
        assert msg is not None
        assert "soothed.pid" in msg
    finally:
        clear_protected_kill_hooks()
        monkeypatch.setattr("soothe.security.daemon_kill_guards._installed", False)
