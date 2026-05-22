"""Stale multiprocessing.spawn worker cleanup."""

from __future__ import annotations

from unittest.mock import patch

from soothe_daemon.persistence.process_cleanup import (
    _looks_like_soothe_spawn,
    reap_stale_soothe_worker_processes,
)


def test_looks_like_soothe_spawn() -> None:
    cmd = (
        "/Users/x/Workspace/Soothe/.venv/bin/python -c from multiprocessing.spawn "
        "import spawn_main; spawn_main(tracker_fd=12) --multiprocessing-fork"
    )
    assert _looks_like_soothe_spawn(cmd, None) is True
    assert _looks_like_soothe_spawn("python -c 'print(1)'", None) is False


def test_reap_skips_live_daemon_child() -> None:
    ps_out = " 100   50 /venv/python -m soothe_daemon --detached\n"
    ps_out += " 200   100 /venv/python -c from multiprocessing.spawn import spawn_main\n"

    with (
        patch(
            "soothe_daemon.persistence.process_cleanup.subprocess.run",
            side_effect=[
                type("R", (), {"stdout": ps_out, "returncode": 0})(),
                type("R", (), {"stdout": "soothe_daemon", "returncode": 0})(),
            ],
        ),
        patch("soothe_daemon.persistence.process_cleanup.os.kill") as mock_kill,
        patch("soothe_daemon.persistence.process_cleanup._parent_alive", return_value=True),
    ):
        count = reap_stale_soothe_worker_processes(dry_run=False)
    assert count == 0
    mock_kill.assert_not_called()


def test_reap_orphan_spawn_worker() -> None:
    ps_out = " 300     1 /venv/python -c from multiprocessing.spawn import spawn_main\n"

    with (
        patch(
            "soothe_daemon.persistence.process_cleanup.subprocess.run",
            return_value=type("R", (), {"stdout": ps_out, "returncode": 0})(),
        ),
        patch("soothe_daemon.persistence.process_cleanup.os.kill") as mock_kill,
        patch("soothe_daemon.persistence.process_cleanup._parent_alive", return_value=False),
    ):
        count = reap_stale_soothe_worker_processes(dry_run=False)
    assert count == 1
    mock_kill.assert_called_once()
