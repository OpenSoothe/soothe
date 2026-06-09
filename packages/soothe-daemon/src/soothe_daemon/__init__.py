"""Soothe daemon subpackage - background agent runner with WebSocket IPC."""

import importlib.metadata

try:
    __version__ = importlib.metadata.version("soothe-daemon")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.0.0"

# Lazy imports to avoid heavy module loading (5+ seconds for channels/nio/crypto)
# These are only imported when actually accessed, not at package load time
__all__ = ["SootheDaemon", "WebSocketClient", "__version__", "pid_path", "run_daemon"]


def __getattr__(name: str):
    """Lazy import heavy modules only when accessed."""
    if name == "SootheDaemon":
        from soothe_daemon.server import SootheDaemon

        return SootheDaemon
    if name == "WebSocketClient":
        from soothe_sdk.client import WebSocketClient

        return WebSocketClient
    if name == "run_daemon":
        from soothe_daemon.bootstrap.entrypoint import run_daemon

        return run_daemon
    if name == "pid_path":
        from soothe_daemon.bootstrap.paths import pid_path

        return pid_path
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
