"""Logging package: nano helpers + host GlobalInputHistory + ThreadLogger.

Wraps nano ``setup_logging`` so the host ``soothe.*`` logger tree shares the
same handlers without nano hardcoding this package name.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from soothe_nano.logging import setup as _nano_logging
from soothe_nano.logging.context import get_thread_id, set_thread_id
from soothe_nano.logging.setup import COMMUNITY_LOGGER_NAME, ThreadFormatter

from soothe.logging.global_history import GlobalInputHistory
from soothe.logging.thread_logger import ThreadLogger

if TYPE_CHECKING:
    from soothe_nano.config import SootheConfig

HOST_LOGGER_NAME = "soothe"
NANO_PACKAGE_LOGGER_NAMES = _nano_logging.PACKAGE_LOGGER_NAMES
PACKAGE_LOGGER_NAMES: tuple[str, ...] = _nano_logging.resolve_package_logger_names(
    (HOST_LOGGER_NAME,)
)


def setup_logging(
    config: SootheConfig | None = None,
    *,
    foreground: bool = False,
    log_file: str | Path | None = None,
    extra_logger_names: Sequence[str] | Iterable[str] | None = None,
) -> None:
    """Configure soothe + nano package loggers with shared file/console handlers.

    Always attaches handlers to ``soothe.*`` in addition to nano defaults.
    Further host/plugin trees may be passed via ``extra_logger_names``.
    """
    extras: list[str] = [HOST_LOGGER_NAME]
    if extra_logger_names is not None:
        extras.extend(extra_logger_names)
    _nano_logging.setup_logging(
        config,
        foreground=foreground,
        log_file=log_file,
        extra_logger_names=extras,
    )


__all__ = [
    "COMMUNITY_LOGGER_NAME",
    "GlobalInputHistory",
    "HOST_LOGGER_NAME",
    "NANO_PACKAGE_LOGGER_NAMES",
    "PACKAGE_LOGGER_NAMES",
    "ThreadFormatter",
    "ThreadLogger",
    "get_thread_id",
    "set_thread_id",
    "setup_logging",
]
