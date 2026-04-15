"""Soothe logging package — shared logging infrastructure for all layers.

Provides thread-ID context variables, logging setup, and the JSONL
thread logger. Importable by ``core``, ``daemon``, and ``ux`` without
creating cross-layer dependencies.
"""

from soothe_daemon.logging.context import get_thread_id, set_thread_id
from soothe_daemon.logging.global_history import GlobalInputHistory
from soothe_daemon.logging.setup import ThreadFormatter, setup_logging
from soothe_daemon.logging.thread_logger import ThreadLogger

__all__ = [
    "GlobalInputHistory",
    "ThreadFormatter",
    "ThreadLogger",
    "get_thread_id",
    "set_thread_id",
    "setup_logging",
]
