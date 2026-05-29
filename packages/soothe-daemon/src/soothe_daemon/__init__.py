"""Soothe daemon subpackage - background agent runner with WebSocket IPC."""

import importlib.metadata

try:
    __version__ = importlib.metadata.version("soothe-daemon")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.0.0"

from soothe_sdk.client import WebSocketClient

from soothe_daemon.entrypoint import run_daemon
from soothe_daemon.paths import pid_path
from soothe_daemon.server import SootheDaemon

__all__ = ["SootheDaemon", "WebSocketClient", "__version__", "pid_path", "run_daemon"]
