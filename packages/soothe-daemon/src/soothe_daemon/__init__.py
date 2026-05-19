"""Soothe daemon subpackage - background agent runner with WebSocket IPC."""

from soothe_sdk.client import WebSocketClient

from soothe_daemon.entrypoint import run_daemon
from soothe_daemon.paths import pid_path
from soothe_daemon.server import SootheDaemon

__all__ = ["SootheDaemon", "WebSocketClient", "pid_path", "run_daemon"]
