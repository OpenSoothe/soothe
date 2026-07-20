"""Unit tests for kill_process process-group teardown."""

from __future__ import annotations

import signal
from unittest.mock import patch

import pytest

from soothe_nano.toolkits.execution import KillProcessTool, _kill_process_tree


def test_kill_process_rejects_invalid_pid() -> None:
    tool = KillProcessTool()
    assert "invalid process ID" in tool._run(0)
    assert "invalid process ID" in tool._run(-1)


def test_kill_process_not_found() -> None:
    tool = KillProcessTool()
    with patch("soothe_nano.toolkits.execution.os.kill", side_effect=ProcessLookupError):
        result = tool._run(99999)
    assert "not found" in result


def test_kill_process_permission_denied_on_probe() -> None:
    tool = KillProcessTool()
    with patch("soothe_nano.toolkits.execution.os.kill", side_effect=PermissionError):
        result = tool._run(42)
    assert "permission denied" in result


def test_kill_process_uses_process_group_teardown(monkeypatch) -> None:
    tool = KillProcessTool()
    calls: list[tuple[int, int]] = []

    def fake_kill(pid: int, sig: int) -> None:
        if sig == 0:
            return
        raise AssertionError("unexpected direct kill")

    def fake_kill_tree(pid: int, *, sig: int = signal.SIGKILL) -> None:
        calls.append((pid, sig))

    monkeypatch.setattr("soothe_nano.toolkits.execution.os.kill", fake_kill)
    monkeypatch.setattr("soothe_nano.toolkits.execution._kill_process_tree", fake_kill_tree)
    monkeypatch.setattr("soothe_nano.toolkits.execution._process_is_alive", lambda _pid: False)

    result = tool._run(42)
    assert result == "Process 42 terminated"
    assert calls == [(42, signal.SIGTERM)]


def test_kill_process_escalates_to_sigkill_when_still_alive(monkeypatch) -> None:
    tool = KillProcessTool()
    calls: list[int] = []

    def fake_kill_tree(pid: int, *, sig: int = signal.SIGKILL) -> None:
        calls.append(sig)

    alive_checks = iter([True, False])

    monkeypatch.setattr("soothe_nano.toolkits.execution.os.kill", lambda _pid, _sig: None)
    monkeypatch.setattr("soothe_nano.toolkits.execution._kill_process_tree", fake_kill_tree)
    monkeypatch.setattr(
        "soothe_nano.toolkits.execution._process_is_alive", lambda _pid: next(alive_checks)
    )

    result = tool._run(42)
    assert result == "Process 42 terminated"
    assert calls == [signal.SIGTERM, signal.SIGKILL]


def test_kill_process_signals_shutdown_when_process_survives(monkeypatch) -> None:
    tool = KillProcessTool()
    monkeypatch.setattr("soothe_nano.toolkits.execution.os.kill", lambda _pid, _sig: None)
    monkeypatch.setattr("soothe_nano.toolkits.execution._kill_process_tree", lambda *_a, **_k: None)
    monkeypatch.setattr("soothe_nano.toolkits.execution._process_is_alive", lambda _pid: True)

    result = tool._run(42)
    assert "termination signaled" in result


@pytest.mark.asyncio
async def test_kill_process_arun_delegates_to_sync() -> None:
    tool = KillProcessTool()
    with patch.object(tool, "_run", return_value="Process 1 terminated") as mock_run:
        result = await tool._arun(1)
    assert result == "Process 1 terminated"
    mock_run.assert_called_once_with(1, runtime=None)


def test_kill_process_tree_noop_for_invalid_pid() -> None:
    with patch("soothe_nano.toolkits.execution.os.killpg") as mock_killpg:
        _kill_process_tree(0)
        _kill_process_tree(-5)
    mock_killpg.assert_not_called()


def test_kill_process_appends_footer_to_log(tmp_path, monkeypatch) -> None:
    ws = tmp_path / "project"
    ws.mkdir()
    log_dir = ws / ".soothe" / "background"
    log_dir.mkdir(parents=True)
    log_path = log_dir / "bg-42.log"
    log_path.write_text("[soothe] background started\n", encoding="utf-8")

    tool = KillProcessTool(workspace_root=str(ws))
    monkeypatch.setattr("soothe_nano.toolkits.execution.os.kill", lambda _pid, _sig: None)
    monkeypatch.setattr("soothe_nano.toolkits.execution._kill_process_tree", lambda *_a, **_k: None)
    monkeypatch.setattr("soothe_nano.toolkits.execution._process_is_alive", lambda _pid: False)

    result = tool._run(42)
    assert result == "Process 42 terminated"
    content = log_path.read_text(encoding="utf-8")
    assert "process 42 terminated" in content
