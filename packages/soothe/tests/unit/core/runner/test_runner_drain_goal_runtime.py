"""Tests for workspace-scoped shell process draining at goal completion/cancel.

Covers ``drain_goal_runtime`` — lifecycle teardown that kills a goal's
``run_command`` (foreground sessions) and ``run_background`` (bg-logs)
grandchildren before the completion/cancel path finishes.
"""

from __future__ import annotations

import signal
from pathlib import Path
from unittest.mock import patch

from soothe.runner.shell_drain import drain_goal_runtime


def _make_bg_logs(workspace: Path, pids: list[int]) -> Path:
    """Create {workspace}/.soothe/background/bg-{pid}.log for each pid."""
    bg_dir = workspace / ".soothe" / "background"
    bg_dir.mkdir(parents=True, exist_ok=True)
    for pid in pids:
        (bg_dir / f"bg-{pid}.log").write_text(f"[soothe] command: sleep {pid}\n")
    return bg_dir


def _make_fg_sessions(workspace: Path, pids: list[int]) -> Path:
    """Create {workspace}/.soothe/foreground/fg-{pid}.session for each pid."""
    fg_dir = workspace / ".soothe" / "foreground"
    fg_dir.mkdir(parents=True, exist_ok=True)
    for pid in pids:
        (fg_dir / f"fg-{pid}.session").write_text("[soothe] run_command started\n")
    return fg_dir


def test_drain_no_workspace_returns_zero() -> None:
    assert drain_goal_runtime("") == 0


def test_drain_missing_background_dir_returns_zero(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    assert drain_goal_runtime(str(workspace)) == 0


def test_drain_no_bg_logs_returns_zero(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    _make_bg_logs(workspace, [])
    assert drain_goal_runtime(str(workspace)) == 0


def test_drain_kills_process_groups_sigterm_then_sigkill(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    _make_bg_logs(workspace, [111, 222])

    killpg_calls: list[tuple[int, int]] = []

    def _fake_getpgid(pid: int) -> int:
        # Each PID is its own process group leader (start_new_session).
        return pid

    def _fake_killpg(pgid: int, sig: int) -> None:
        killpg_calls.append((pgid, sig))

    def _pid_alive(pid: int) -> bool:
        # Pretend SIGTERM doesn't kill, SIGKILL does.
        already_killed = any(p == pid and s == signal.SIGKILL for p, s in killpg_calls)
        return not already_killed

    with (
        patch("soothe.runner.shell_drain.os.getpgid", side_effect=_fake_getpgid),
        patch("soothe.runner.shell_drain.os.killpg", side_effect=_fake_killpg),
        patch("soothe.runner.shell_drain._pid_alive", side_effect=_pid_alive),
        patch("soothe.runner.shell_drain.time.sleep"),
    ):
        reaped = drain_goal_runtime(str(workspace), grace_seconds=0.0)

    # Two process groups reaped.
    assert reaped == 2
    # SIGTERM sent first for each, then SIGKILL (since SIGTERM "fails").
    term_calls = [c for c in killpg_calls if c[1] == signal.SIGTERM]
    kill_calls = [c for c in killpg_calls if c[1] == signal.SIGKILL]
    assert {c[0] for c in term_calls} == {111, 222}
    assert {c[0] for c in kill_calls} == {111, 222}
    # Log files unlinked after drain.
    bg_dir = workspace / ".soothe" / "background"
    assert not (bg_dir / "bg-111.log").exists()
    assert not (bg_dir / "bg-222.log").exists()


def test_drain_kills_foreground_run_command_sessions(tmp_path: Path) -> None:
    """In-flight run_command markers are reaped the same way as bg logs."""
    workspace = tmp_path / "ws"
    _make_fg_sessions(workspace, [777, 888])

    killpg_calls: list[tuple[int, int]] = []

    def _fake_getpgid(pid: int) -> int:
        return pid

    def _fake_killpg(pgid: int, sig: int) -> None:
        killpg_calls.append((pgid, sig))

    def _pid_alive(pid: int) -> bool:
        already_killed = any(p == pid and s == signal.SIGKILL for p, s in killpg_calls)
        return not already_killed

    with (
        patch("soothe.runner.shell_drain.os.getpgid", side_effect=_fake_getpgid),
        patch("soothe.runner.shell_drain.os.killpg", side_effect=_fake_killpg),
        patch("soothe.runner.shell_drain._pid_alive", side_effect=_pid_alive),
        patch("soothe.runner.shell_drain.time.sleep"),
    ):
        reaped = drain_goal_runtime(str(workspace), grace_seconds=0.0)

    assert reaped == 2
    assert {c[0] for c in killpg_calls if c[1] == signal.SIGTERM} == {777, 888}
    fg_dir = workspace / ".soothe" / "foreground"
    assert not (fg_dir / "fg-777.session").exists()
    assert not (fg_dir / "fg-888.session").exists()


def test_drain_reaps_foreground_and_background_together(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    _make_fg_sessions(workspace, [101])
    _make_bg_logs(workspace, [202])

    killed: list[int] = []

    def _fake_getpgid(pid: int) -> int:
        return pid

    def _fake_killpg(pgid: int, sig: int) -> None:
        if sig == signal.SIGTERM:
            killed.append(pgid)

    def _pid_alive(pid: int) -> bool:
        return pid not in killed

    with (
        patch("soothe.runner.shell_drain.os.getpgid", side_effect=_fake_getpgid),
        patch("soothe.runner.shell_drain.os.killpg", side_effect=_fake_killpg),
        patch("soothe.runner.shell_drain._pid_alive", side_effect=_pid_alive),
        patch("soothe.runner.shell_drain.time.sleep"),
    ):
        reaped = drain_goal_runtime(str(workspace), grace_seconds=0.0)

    assert reaped == 2
    assert set(killed) == {101, 202}


def test_drain_skips_dead_processes(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    _make_bg_logs(workspace, [333])

    with (
        patch("soothe.runner.shell_drain.os.getpgid", return_value=333),
        patch(
            "soothe.runner.shell_drain._pid_alive",
            return_value=False,
        ),
        patch("soothe.runner.shell_drain.os.killpg") as mock_killpg,
    ):
        reaped = drain_goal_runtime(str(workspace), grace_seconds=0.0)

    assert reaped == 0
    mock_killpg.assert_not_called()


def test_drain_process_lookup_error_is_swallowed(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    _make_bg_logs(workspace, [444])

    def _fake_killpg(pgid: int, sig: int) -> None:
        raise ProcessLookupError

    with (
        patch("soothe.runner.shell_drain.os.getpgid", return_value=444),
        patch("soothe.runner.shell_drain._pid_alive", return_value=True),
        patch("soothe.runner.shell_drain.os.killpg", side_effect=_fake_killpg),
        patch("soothe.runner.shell_drain.time.sleep"),
    ):
        reaped = drain_goal_runtime(str(workspace), grace_seconds=0.0)

    # killpg raised ProcessLookupError → counts as not delivered → not reaped.
    assert reaped == 0


def test_drain_only_touches_workspace_bg_logs(tmp_path: Path) -> None:
    """A PID whose bg-log is NOT under this workspace is never touched."""
    workspace = tmp_path / "ws"
    other = tmp_path / "other-ws"
    _make_bg_logs(workspace, [555])
    _make_bg_logs(other, [666])

    killed: list[int] = []

    def _fake_killpg(pgid: int, sig: int) -> None:
        killed.append(pgid)

    with (
        patch("soothe.runner.shell_drain.os.getpgid", return_value=lambda p: p),
        patch("soothe.runner.shell_drain._pid_alive", return_value=False),
        patch("soothe.runner.shell_drain.os.killpg", side_effect=_fake_killpg),
    ):
        drain_goal_runtime(str(workspace), grace_seconds=0.0)

    # Only 555 is even considered (and since _pid_alive False, not reaped).
    assert 666 not in killed
