"""Host-injected kill_process guards for the live Soothe daemon.

Nano's ``KillProcessTool`` only knows self/parent PID safety. Host daemon
protection (pidfile + production WebSocket listener) is registered here via
``soothe_nano.toolkits.execution.register_protected_kill_hook``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from soothe_nano.toolkits.execution import register_protected_kill_hook

from soothe.config import SOOTHE_HOME

# Matches ``soothe_daemon`` / CLI default WebSocket port.
PRODUCTION_DAEMON_WS_PORT = 8765

_installed = False


def _soothed_pid_from_pidfile() -> int | None:
    """Return the host daemon PID from ``SOOTHE_HOME/soothed.pid`` when present."""
    try:
        pf = Path(SOOTHE_HOME).expanduser() / "soothed.pid"
        if not pf.is_file():
            return None
        return int(pf.read_text(encoding="utf-8").strip())
    except (OSError, ValueError, TypeError):
        return None


def _pid_listening_on_port(port: int) -> int | None:
    """Best-effort PID of the process listening on ``port`` (macOS/Linux ``lsof``)."""
    if port <= 0:
        return None
    try:
        completed = subprocess.run(  # noqa: S603
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    for line in (completed.stdout or "").splitlines():
        token = line.strip()
        if token.isdigit():
            return int(token)
    return None


def daemon_protected_kill_refusal(pid: int) -> str | None:
    """Refuse killing the live host daemon (pidfile or production WS listener)."""
    daemon_pid = _soothed_pid_from_pidfile()
    if daemon_pid is not None and pid == daemon_pid:
        return (
            f"Error: refusing to kill Soothe daemon PID {pid} (soothed.pid). "
            "Stop the host daemon from an outside shell with `soothed stop`, "
            "not via agent tools."
        )

    listener = _pid_listening_on_port(PRODUCTION_DAEMON_WS_PORT)
    if listener is not None and pid == listener:
        return (
            f"Error: refusing to kill PID {pid} listening on "
            f"ws://127.0.0.1:{PRODUCTION_DAEMON_WS_PORT} (live Soothe daemon). "
            "kill_process is only for PIDs returned by run_background."
        )
    return None


def ensure_daemon_kill_guards_installed() -> None:
    """Idempotently register host daemon kill guards into nano's hook registry."""
    global _installed
    register_protected_kill_hook(daemon_protected_kill_refusal)
    _installed = True


__all__ = [
    "PRODUCTION_DAEMON_WS_PORT",
    "daemon_protected_kill_refusal",
    "ensure_daemon_kill_guards_installed",
]
