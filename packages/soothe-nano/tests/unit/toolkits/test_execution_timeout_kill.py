"""Unit tests for run_command timeout process-group teardown."""

from __future__ import annotations

import subprocess
import time
from unittest.mock import MagicMock, patch

import pytest

from soothe_nano.config.constants import (
    DEFAULT_TASK_TIMEOUT_SECONDS,
    MAX_EXECUTE_TIMEOUT,
    clamp_execute_timeout,
)
from soothe_nano.toolkits.execution import (
    RunCommandShellTool,
    _kill_process_tree,
    _run_shell_command_sync,
)


def test_max_execute_timeout_is_five_hours() -> None:
    assert MAX_EXECUTE_TIMEOUT == 18_000
    assert DEFAULT_TASK_TIMEOUT_SECONDS == MAX_EXECUTE_TIMEOUT


def test_clamp_execute_timeout_respects_ceiling() -> None:
    assert clamp_execute_timeout(60) == 60
    assert clamp_execute_timeout(99_999) == MAX_EXECUTE_TIMEOUT


def test_kill_process_tree_uses_killpg_on_unix(monkeypatch) -> None:
    monkeypatch.setattr("soothe_nano.toolkits.execution.sys.platform", "linux")

    def fake_getpgid(pid: int) -> int:
        # Distinct from the caller's group so killpg is used (IG-665).
        return 1 if pid == 0 else 999

    monkeypatch.setattr("soothe_nano.toolkits.execution.os.getpgid", fake_getpgid)
    killed: list[tuple[int, int]] = []

    def fake_killpg(pgid: int, sig: int) -> None:
        killed.append((pgid, sig))

    monkeypatch.setattr("soothe_nano.toolkits.execution.os.killpg", fake_killpg)
    _kill_process_tree(42)
    assert killed == [(999, 9)]


def test_run_shell_command_sync_kills_tree_on_timeout(monkeypatch) -> None:
    proc = MagicMock()
    proc.pid = 123
    proc.communicate.side_effect = subprocess.TimeoutExpired(cmd="sleep", timeout=1)
    monkeypatch.setattr("soothe_nano.toolkits.execution.subprocess.Popen", lambda *a, **k: proc)
    killed: list[int] = []
    monkeypatch.setattr(
        "soothe_nano.toolkits.execution._kill_process_tree",
        lambda pid, **kw: killed.append(pid),
    )

    with pytest.raises(subprocess.TimeoutExpired):
        _run_shell_command_sync("sleep 9", cwd=None, timeout=1)

    proc.kill.assert_called_once()
    assert killed == [123]


def test_run_command_timeout_message_mentions_process_group() -> None:
    tool = RunCommandShellTool(workspace_root="/tmp", timeout=1)
    with patch(
        "soothe_nano.toolkits.execution._run_shell_command_sync",
        side_effect=subprocess.TimeoutExpired(cmd="sleep", timeout=1),
    ):
        result = tool._run("sleep 9")
    assert "timed out" in result.lower()
    assert "process group" in result.lower()
    assert "run_background" in result.lower()


def test_run_shell_command_sync_times_out_silent_process_with_output_cap() -> None:
    """Silent children must not bypass timeout when max_output_chars is enabled."""
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        _run_shell_command_sync(
            "sleep 30",
            cwd=None,
            timeout=1,
            max_output_chars=100_000,
        )
    assert time.monotonic() - started < 5
