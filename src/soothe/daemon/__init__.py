"""Soothe daemon subpackage - background agent runner with Unix socket IPC.

Public API re-exports for backward compatibility.
"""

from soothe.daemon.client import DaemonClient
from soothe.daemon.entrypoint import run_daemon
from soothe.daemon.paths import pid_path, socket_path
from soothe.daemon.server import SootheDaemon

__all__ = ["DaemonClient", "SootheDaemon", "pid_path", "run_daemon", "socket_path"]
