"""Soothe daemon subpackage - background agent runner with WebSocket IPC."""

from soothe.daemon.entrypoint import run_daemon
from soothe.daemon.paths import pid_path
from soothe.daemon.server import SootheDaemon
from soothe.daemon.websocket_client import WebSocketClient

# Backward compatibility alias (deprecated)
DaemonClient = WebSocketClient

__all__ = ["SootheDaemon", "WebSocketClient", "DaemonClient", "pid_path", "run_daemon"]
