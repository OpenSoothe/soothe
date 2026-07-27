"""Locate a process listening on a local TCP port (daemon stop/status)."""

from __future__ import annotations

import contextlib
import subprocess

# macOS ``lsof -i`` often exceeds 300ms under load; 0.3s caused orphan stop failures.
LSOF_PORT_LOOKUP_TIMEOUT_S = 2.0


def find_listening_pid(port: int, *, timeout: float = LSOF_PORT_LOOKUP_TIMEOUT_S) -> int | None:
    """Return PID listening on ``port``, or ``None`` if not found / lookup fails.

    Args:
        port: TCP port number.
        timeout: Seconds to wait for ``lsof`` before giving up.

    Returns:
        First LISTEN PID for the port, or ``None``.
    """
    with contextlib.suppress(subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        result = subprocess.run(
            ["lsof", "-nP", "-i", f"TCP:{port}", "-t", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            pids = result.stdout.strip().split("\n")
            if pids:
                return int(pids[0])
    return None


__all__ = ["LSOF_PORT_LOOKUP_TIMEOUT_S", "find_listening_pid"]
