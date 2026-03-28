"""Soothe daemon subpackage - background agent runner with Unix socket IPC."""

from soothe.daemon.client import DaemonClient
from soothe.daemon.entrypoint import run_daemon
from soothe.daemon.paths import pid_path, resolve_socket_path, socket_path
from soothe.daemon.server import SootheDaemon

__all__ = ["DaemonClient", "SootheDaemon", "pid_path", "resolve_socket_path", "run_daemon", "socket_path"]
