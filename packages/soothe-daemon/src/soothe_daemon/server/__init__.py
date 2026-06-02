"""The running daemon: SootheDaemon class plus PID-based process discovery."""

from soothe_daemon.server.core import SootheDaemon

# DaemonProcess will be extracted in Commit 3
# from soothe_daemon.server.process import DaemonProcess

__all__ = ["SootheDaemon"]
