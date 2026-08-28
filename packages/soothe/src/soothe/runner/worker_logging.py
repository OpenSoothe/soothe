"""File logging for isolated loop workers (multiprocessing subprocess or Ray actor).

 workers run outside the daemon process and need their own ``soothe.*``
handlers so diagnostics land under each loop's persistence directory.
"""

from __future__ import annotations

import logging
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

from soothe_nano.logging.context import set_thread_id
from soothe_nano.logging.setup import (
    ThreadFormatter,
    _has_rotating_file_handler_at,
    _package_loggers,
    _suppress_noisy_third_party,
)

from soothe.config.settings import SootheConfig
from soothe.logging import HOST_LOGGER_NAME
from soothe.sloop.checkpoints.directory_manager import PersistenceDirectoryManager

_LOG = logging.getLogger(__name__)

RUNNER_LOG_FILENAME = "runner.log"

# Process-level set of loops with an in-flight worker request. Pooled ThreadPool
# workers share one process and the same ``soothe.*`` package loggers; without
# this guard, configuring loop B would tear down loop A's still-active
# ``runner.log`` handler mid-run (the d15f incident: runner.log went silent
# 12 min before the crash while the loop kept executing).
_active_loop_ids: set[str] = set()
_active_loop_ids_lock = threading.Lock()


def configure_loop_runner_worker_logging(config: SootheConfig, loop_id: str) -> Path | None:
    """Attach rotating file logging for this worker process.

    Writes to ``SOOTHE_HOME/data/loops/{loop_id}/runner.log`` (same layout as
    loop isolation persistence). Safe to call more than once for the same path:
    duplicate handlers are skipped.

    Args:
        config: Worker configuration (rotation/size mirrors ``observability``).
        loop_id: Active StrangeLoop identifier.

    Returns:
        Path to ``runner.log``, or ``None`` when ``loop_id`` is empty.
    """
    lid = (loop_id or "").strip()
    if not lid:
        return None

    with _active_loop_ids_lock:
        _active_loop_ids.add(lid)

    loop_dir = PersistenceDirectoryManager.get_loop_directory(lid)
    loop_dir.mkdir(parents=True, exist_ok=True)
    log_path = loop_dir / RUNNER_LOG_FILENAME
    resolved = log_path.resolve()

    package_loggers = _package_loggers((HOST_LOGGER_NAME,))
    for pkg_logger in package_loggers:
        _remove_stale_loop_runner_handlers(pkg_logger, keep_path=resolved)

    file_level_name = config.logging.file.level.upper()
    if config.debug:
        file_level_name = "DEBUG"
    file_level = getattr(logging, file_level_name, logging.INFO)

    for pkg_logger in package_loggers:
        pkg_logger.setLevel(file_level)

    formatter = ThreadFormatter(
        "%(asctime)s %(level_short)s %(thread_id)s %(name)s:%(lineno)d %(message)s"
    )
    for pkg_logger in package_loggers:
        if _has_rotating_file_handler_at(pkg_logger, resolved):
            continue
        fh = RotatingFileHandler(
            str(log_path),
            maxBytes=config.logging.file.max_bytes,
            backupCount=config.logging.file.backup_count,
            encoding="utf-8",
        )
        fh.setFormatter(formatter)
        fh.setLevel(file_level)
        pkg_logger.addHandler(fh)

    _suppress_noisy_third_party()

    set_thread_id(lid)

    _LOG.info("Loop worker file logging enabled at %s", log_path)
    return log_path


def release_loop_runner_logging(loop_id: str) -> None:
    """Release the in-flight marker for ``loop_id`` and close its ``runner.log`` handler.

    Call from the worker request's ``finally`` block. After release, a later
    ``configure_loop_runner_worker_logging`` call for a different loop may
    remove this loop's handler (it is no longer actively writing). Without
    this teardown, pooled workers accumulate one handler per loop across the
    process lifetime.
    """
    lid = (loop_id or "").strip()
    if not lid:
        return
    with _active_loop_ids_lock:
        _active_loop_ids.discard(lid)
    # Close+remove this loop's handler now that it is no longer active —
    # pooled workers reuse the shared package loggers and stale handlers
    # would otherwise pin fd's and double-write if the loop is re-dispatched.
    package_loggers = _package_loggers((HOST_LOGGER_NAME,))
    loop_dir = PersistenceDirectoryManager.get_loop_directory(lid)
    log_path = (loop_dir / RUNNER_LOG_FILENAME).resolve()
    for pkg_logger in package_loggers:
        _remove_handler_at_path(pkg_logger, log_path)


def _remove_handler_at_path(root_logger: logging.Logger, target: Path) -> None:
    """Remove and close the ``runner.log`` handler at ``target`` if present."""
    target_resolved = target.resolve()
    for handler in list(root_logger.handlers):
        if not isinstance(handler, RotatingFileHandler):
            continue
        base = getattr(handler, "baseFilename", None)
        if base is None:
            continue
        try:
            path = Path(str(base)).resolve()
        except OSError:
            continue
        if path == target_resolved:
            root_logger.removeHandler(handler)
            handler.close()


def _remove_stale_loop_runner_handlers(root_logger: logging.Logger, *, keep_path: Path) -> None:
    """Remove loop ``runner.log`` handlers for other loops (pooled workers reuse one process).

    Skips handlers whose loop still has an in-flight request — tearing those
    down mid-run silences the active loop's diagnostics (the d15f incident).
    """
    keep_resolved = keep_path.resolve()
    with _active_loop_ids_lock:
        active = set(_active_loop_ids)
    stale: list[logging.Handler] = []
    for handler in root_logger.handlers:
        if not isinstance(handler, RotatingFileHandler):
            continue
        base = getattr(handler, "baseFilename", None)
        if base is None:
            continue
        try:
            path = Path(str(base)).resolve()
        except OSError:
            continue
        if path.name != RUNNER_LOG_FILENAME or path == keep_resolved:
            continue
        # The loop directory name is the loop id (data/loops/{loop_id}/runner.log).
        candidate_loop_id = path.parent.name
        if candidate_loop_id in active:
            # Another worker thread still has this loop in-flight; do not
            # tear down its handler.
            continue
        stale.append(handler)
    for handler in stale:
        root_logger.removeHandler(handler)
        handler.close()


__all__ = [
    "RUNNER_LOG_FILENAME",
    "configure_loop_runner_worker_logging",
    "release_loop_runner_logging",
]
