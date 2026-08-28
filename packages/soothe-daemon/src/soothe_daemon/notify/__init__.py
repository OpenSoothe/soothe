"""Daemon job lifecycle notify sinks."""

from soothe_daemon.notify.factory import (
    build_notify_dispatcher,
    build_notify_dispatcher_from_autopilot,
)
from soothe_daemon.notify.protocol import NotifyDispatcher, NotifySink

__all__ = [
    "NotifyDispatcher",
    "NotifySink",
    "build_notify_dispatcher",
    "build_notify_dispatcher_from_autopilot",
]
