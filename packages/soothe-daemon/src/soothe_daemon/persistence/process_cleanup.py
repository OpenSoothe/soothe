"""Reap orphaned soothe multiprocessing worker processes."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)

_SPAWN_MARKERS = ("multiprocessing.spawn", "spawn_main")
_SOOTHE_MARKERS = ("soothe", "soothe_daemon", "Soothe", "soothe_daemon")
# Paths that mark a process as a worktree/background spawn of a soothe job.
_WORKTREE_PATH_MARKERS = (".soothe/worktrees/", ".soothe/background/bg-")


def _read_cmdline(pid: int) -> str:
    """Best-effort process command line for *pid*."""
    try:
        out = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            check=False,
            timeout=2,
        )
        return (out.stdout or "").strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _parent_alive(pid: int) -> bool:
    """Return whether *pid* exists."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    else:
        return True


def _looks_like_soothe_spawn(cmdline: str, soothe_root: Path | None) -> bool:
    if not any(marker in cmdline for marker in _SPAWN_MARKERS):
        return False
    if "multiprocessing" not in cmdline:
        return False
    if soothe_root is not None and str(soothe_root) in cmdline:
        return True
    if any(marker in cmdline for marker in _SOOTHE_MARKERS):
        return True
    # worker_pool children often show only spawn_main in ps(1) output
    return "spawn_main" in cmdline


def _looks_like_orphaned_worktree_spawn(cmdline: str) -> bool:
    """True when a process references a leaked worktree/background path.

    These are agent ``run_background`` grandchildren (jest/pytest/npm/…)
    whose parent worker died, leaving them reparented to PID 1 with a
    command line still pointing at a ``.soothe/worktrees/`` workspace or a
    ``.soothe/background/bg-`` log path. Bounded to soothe-workspace paths,
    not a global match.
    """
    return any(marker in cmdline for marker in _WORKTREE_PATH_MARKERS)


def reap_stale_soothe_worker_processes(
    *,
    dry_run: bool = False,
    soothe_project_root: Path | None = None,
    daemon_pid: int | None = None,
    protect_pids: frozenset[int] | None = None,
) -> int:
    """Terminate orphaned ``multiprocessing.spawn`` workers from old daemon runs.

    Targets child processes whose command line includes ``multiprocessing.spawn``
    and a soothe path, when the parent PID is not alive or is not the current daemon.

    Args:
        dry_run: Log candidates without sending SIGTERM.
        soothe_project_root: Optional repo/venv root to narrow matches.
        daemon_pid: Skip spawn workers whose parent is this PID (defaults to current process).
        protect_pids: Optional PIDs to never terminate (e.g. live pool workers).

    Returns:
        Number of processes sent SIGTERM (0 in dry_run).
    """
    root = soothe_project_root
    if root is None:
        root = Path(__file__).resolve().parents[4]

    effective_daemon_pid = os.getpid() if daemon_pid is None else daemon_pid
    protected = protect_pids or frozenset()

    try:
        out = subprocess.run(
            ["ps", "-ax", "-o", "pid=,pgid=,ppid=,command="],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("Could not list processes for stale worker cleanup: %s", exc)
        return 0

    current_pid = os.getpid()
    reaped = 0

    for line in out.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 3)
        if len(parts) < 4:
            continue
        try:
            pid = int(parts[0])
            pgid = int(parts[1])
            ppid = int(parts[2])
        except ValueError:
            continue
        cmd = parts[3]
        if pid == current_pid or pid <= 1:
            continue
        if pid in protected or pgid in protected:
            continue

        is_spawn = _looks_like_soothe_spawn(cmd, root)
        is_wt_spawn = _looks_like_orphaned_worktree_spawn(cmd)
        if not is_spawn and not is_wt_spawn:
            continue

        # Worktree/background grandchildren are only reaped when orphaned
        # (parent dead / reparented to init) so live workers are untouched.
        if is_wt_spawn:
            parent_dead = not _parent_alive(ppid)
            if not parent_dead and ppid != 1:
                continue
        else:
            if ppid == effective_daemon_pid:
                continue
            parent_cmd = _read_cmdline(ppid) if _parent_alive(ppid) else ""
            parent_is_daemon = "soothe_daemon" in parent_cmd
            parent_dead = not _parent_alive(ppid)
            if parent_is_daemon and not parent_dead:
                continue

        if dry_run:
            logger.info(
                "Would reap stale soothe process pid=%d pgid=%d ppid=%d cmd=%s",
                pid,
                pgid,
                ppid,
                cmd[:120],
            )
            continue
        # Kill the whole process group — run_background spawns with
        # start_new_session=True, so the shell leader and its children
        # (jest workers, pytest, node) share the pgid.
        try:
            os.killpg(pgid, signal.SIGTERM)
            reaped += 1
            logger.info("Sent SIGTERM to stale soothe process pid=%d pgid=%d", pid, pgid)
        except ProcessLookupError:
            pass
        except PermissionError:
            logger.warning("No permission to terminate pid=%d pgid=%d", pid, pgid)

    if reaped:
        logger.info("Reaped %d stale soothe process(es)", reaped)
    return reaped


async def periodic_stale_worker_reap(
    *,
    is_running: Callable[[], bool],
    interval_s: int,
    daemon_pid: int | None = None,
    protect_pids: frozenset[int] | None = None,
) -> None:
    """Reap orphaned spawn workers on a fixed interval without blocking the event loop."""
    while is_running():
        await asyncio.sleep(interval_s)
        if not is_running():
            break
        try:
            await asyncio.to_thread(
                reap_stale_soothe_worker_processes,
                daemon_pid=daemon_pid,
                protect_pids=protect_pids,
            )
        except Exception:
            logger.debug("Periodic stale worker reap failed", exc_info=True)


def reap_from_cli() -> None:
    """CLI entry: ``python -m soothe_daemon.persistence``."""
    count = reap_stale_soothe_worker_processes(dry_run="--dry-run" in sys.argv)
    print(f"reaped={count}")
