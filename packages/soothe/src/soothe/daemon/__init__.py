"""Soothe daemon subpackage - background agent runner with WebSocket IPC."""

from soothe_sdk.client import WebSocketClient

from soothe.daemon.entrypoint import run_daemon
from soothe.daemon.paths import pid_path, socket_path
from soothe.daemon.server import SootheDaemon

__all__ = ["SootheDaemon", "WebSocketClient", "pid_path", "run_daemon", "socket_path"]
