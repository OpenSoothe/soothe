"""Goal-runtime shell drain — kill a goal's spawned shell process groups."""

from __future__ import annotations

import contextlib
import logging
import os
import re
import signal
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Default SIGTERM→SIGKILL grace period when draining shell spawns.
_DRAIN_GRACE_SECONDS = 2.0
_BG_LOG_PID_RE = re.compile(r"bg-(\d+)\.log$")
_FG_SESSION_PID_RE = re.compile(r"fg-(\d+)\.session$")


def _kill_pgid(pgid: int, *, sig: int) -> bool:
    """Send `sig` to a process group. True if delivered, False if gone."""
    try:
        os.killpg(pgid, sig)
    except ProcessLookupError:
        return False
    except PermissionError:
        logger.warning("drain_goal_runtime: no permission to signal pgid=%d", pgid)
        return False
    except OSError as exc:
        logger.debug("drain_goal_runtime: killpg(%d, %d) failed: %s", pgid, sig, exc)
        return False
    return True


def _pid_alive(pid: int) -> bool:
    """True if `pid` exists."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    else:
        return True


def _reap_tracked_shell_pids(
    marker_dir: Path,
    *,
    glob_pattern: str,
    pid_re: re.Pattern[str],
    grace_seconds: float,
) -> int:
    """SIGTERM→SIGKILL process groups named by marker files under `marker_dir`."""
    if not marker_dir.is_dir():
        return 0
    reaped = 0
    for marker in marker_dir.glob(glob_pattern):
        match = pid_re.search(marker.name)
        if match is None:
            continue
        pid = int(match.group(1))
        try:
            pgid = os.getpgid(pid)
        except ProcessLookupError:
            with contextlib.suppress(OSError):
                marker.unlink(missing_ok=True)
            continue
        except (OSError, PermissionError):
            continue
        if not _pid_alive(pid):
            with contextlib.suppress(OSError):
                marker.unlink(missing_ok=True)
            continue
        if not _kill_pgid(pgid, sig=signal.SIGTERM):
            continue
        reaped += 1
        deadline = time.monotonic() + grace_seconds
        while time.monotonic() < deadline and _pid_alive(pid):
            time.sleep(0.05)
        if _pid_alive(pid):
            _kill_pgid(pgid, sig=signal.SIGKILL)
        with contextlib.suppress(OSError):
            marker.unlink(missing_ok=True)
    return reaped


def drain_goal_runtime(workspace: str, *, grace_seconds: float = _DRAIN_GRACE_SECONDS) -> int:
    """Kill shell processes this goal spawned (`run_command` + `run_background`).

    Workspace-scoped: only touches PIDs whose markers live under THIS workspace.
    Not a global `ps` scan. Safe at goal completion and on cancel.

    Args:
        workspace: Workspace path that owns the spawned shell markers.
        grace_seconds: SIGTERM→SIGKILL grace period.

    Returns:
        Count of process groups reaped.
    """
    if not workspace:
        return 0
    root = Path(workspace).expanduser() / ".soothe"
    reaped = _reap_tracked_shell_pids(
        root / "foreground",
        glob_pattern="fg-*.session",
        pid_re=_FG_SESSION_PID_RE,
        grace_seconds=grace_seconds,
    )
    reaped += _reap_tracked_shell_pids(
        root / "background",
        glob_pattern="bg-*.log",
        pid_re=_BG_LOG_PID_RE,
        grace_seconds=grace_seconds,
    )
    if reaped:
        logger.info(
            "drain_goal_runtime: reaped %d shell process group(s) under %s",
            reaped,
            workspace,
        )
    return reaped


__all__ = ["drain_goal_runtime"]
