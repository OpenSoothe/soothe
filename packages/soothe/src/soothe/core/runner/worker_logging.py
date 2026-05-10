"""File logging for isolated loop workers (multiprocessing subprocess or Ray actor).

RFC-221 workers run outside the daemon process and need their own ``soothe.*``
handlers so diagnostics land under each loop's persistence directory.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from soothe.config.settings import SootheConfig
from soothe.core.loop.state.persistence.directory_manager import PersistenceDirectoryManager
from soothe.logging.setup import ThreadFormatter, _suppress_noisy_third_party

_LOG = logging.getLogger(__name__)

RUNNER_LOG_FILENAME = "runner.log"


def configure_loop_runner_worker_logging(config: SootheConfig, loop_id: str) -> Path | None:
    """Attach rotating file logging for this worker process.

    Writes to ``SOOTHE_HOME/data/loops/{loop_id}/runner.log`` (same layout as
    loop isolation persistence). Safe to call more than once for the same path:
    duplicate handlers are skipped.

    Args:
        config: Worker configuration (rotation/size mirrors ``observability``).
        loop_id: Active AgentLoop identifier.

    Returns:
        Path to ``runner.log``, or ``None`` when ``loop_id`` is empty.
    """
    lid = (loop_id or "").strip()
    if not lid:
        return None

    loop_dir = PersistenceDirectoryManager.get_loop_directory(lid)
    loop_dir.mkdir(parents=True, exist_ok=True)
    log_path = loop_dir / RUNNER_LOG_FILENAME
    resolved = log_path.resolve()

    file_level_name = config.logging.file.level.upper()
    if config.debug:
        file_level_name = "DEBUG"
    file_level = getattr(logging, file_level_name, logging.INFO)

    root_logger = logging.getLogger("soothe")
    root_logger.setLevel(file_level)

    for h in root_logger.handlers:
        if isinstance(h, RotatingFileHandler):
            bf = getattr(h, "baseFilename", None)
            try:
                if bf is not None and Path(str(bf)).resolve() == resolved:
                    return log_path
            except OSError:
                continue

    fh = RotatingFileHandler(
        str(log_path),
        maxBytes=config.logging.file.max_bytes,
        backupCount=config.logging.file.backup_count,
        encoding="utf-8",
    )
    fh.setFormatter(
        ThreadFormatter("%(asctime)s %(level_short)s %(thread_id)s %(name)s:%(lineno)d %(message)s")
    )
    fh.setLevel(file_level)
    root_logger.addHandler(fh)

    _suppress_noisy_third_party()

    _LOG.info("Loop worker file logging enabled at %s", log_path)
    return log_path


__all__ = ["RUNNER_LOG_FILENAME", "configure_loop_runner_worker_logging"]
