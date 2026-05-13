"""Daemon-side loop runners (worker pool, Ray actors, factory).

The in-proc agent core (``soothe.core.runner``) ships only ``SootheRunner`` and
``LocalLoopRunner``. Pool/Ray runners live here because they are managed by
``SootheDaemon``.
"""

from soothe_daemon.runner.factory import LoopRunnerFactory

__all__ = ["LoopRunnerFactory"]
