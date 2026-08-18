"""Rotating file handler for CLI ``setup_logging``."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

import pytest

from soothe_sdk.utils.logging import (
    DEFAULT_LOG_BACKUP_COUNT,
    DEFAULT_LOG_MAX_BYTES,
    setup_logging,
)


@pytest.fixture(autouse=True)
def _isolate_root_log_handlers() -> None:
    """Avoid cross-test pollution on the process root logger."""
    root = logging.getLogger()
    saved = list(root.handlers)
    saved_level = root.level
    for handler in saved:
        root.removeHandler(handler)
    yield
    for handler in list(root.handlers):
        root.removeHandler(handler)
    for handler in saved:
        root.addHandler(handler)
    root.setLevel(saved_level)


def test_setup_logging_uses_rotating_file_handler(tmp_path) -> None:
    log_file = tmp_path / "cli.log"
    setup_logging("INFO", log_file=log_file)

    root = logging.getLogger()
    handlers = [h for h in root.handlers if isinstance(h, RotatingFileHandler)]
    assert len(handlers) == 1
    handler = handlers[0]
    assert handler.maxBytes == DEFAULT_LOG_MAX_BYTES
    assert handler.backupCount == DEFAULT_LOG_BACKUP_COUNT
    assert handler.baseFilename.endswith("cli.log")


def test_setup_logging_skips_duplicate_rotating_handler(tmp_path) -> None:
    log_file = tmp_path / "cli.log"
    setup_logging("INFO", log_file=log_file)
    setup_logging("DEBUG", log_file=log_file)

    log_file.resolve()
    handlers = [
        h
        for h in logging.getLogger().handlers
        if isinstance(h, RotatingFileHandler) and h.baseFilename == str(log_file.resolve())
    ]
    assert len(handlers) == 1
    assert handlers[0].level == logging.DEBUG
