"""The running daemon: SootheDaemon class plus PID-based process discovery."""

# Lazy import to avoid heavy module loading (core.py imports channels/nio/crypto)
__all__ = ["SootheDaemon"]


def __getattr__(name: str):
    """Lazy import SootheDaemon only when accessed."""
    if name == "SootheDaemon":
        from soothe_daemon.server.core import SootheDaemon

        return SootheDaemon
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
