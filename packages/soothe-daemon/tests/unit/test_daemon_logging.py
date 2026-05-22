"""Tests for daemon logging setup."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

from soothe.logging.setup import PACKAGE_LOGGER_NAMES
from soothe_daemon.logging import DEFAULT_DAEMON_LOG, default_daemon_log_path, setup_daemon_logging


class TestDaemonLogging:
    """Daemon log path and handler setup."""

    @pytest.fixture(autouse=True)
    def clear_logger_handlers(self) -> None:
        """Clear daemon and soothe package logger handlers before each test."""
        for name in ("soothe_daemon", *PACKAGE_LOGGER_NAMES):
            logging.getLogger(name).handlers.clear()
        yield
        for name in ("soothe_daemon", *PACKAGE_LOGGER_NAMES):
            logging.getLogger(name).handlers.clear()

    def test_default_daemon_log_path_ends_with_daemon_log(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Default path is under SOOTHE_HOME/logs/daemon.log."""
        home = Path("/tmp/soothe-test-home")
        monkeypatch.setattr("soothe_daemon.logging.SOOTHE_HOME", str(home))
        assert default_daemon_log_path() == home / "logs" / DEFAULT_DAEMON_LOG

    def test_setup_daemon_logging_uses_explicit_log_file(self, tmp_path: Path) -> None:
        """setup_daemon_logging honors custom log_file."""
        log_file = tmp_path / "custom-daemon.log"
        setup_daemon_logging(log_file=str(log_file))

        daemon_logger = logging.getLogger("soothe_daemon")
        file_handlers = [h for h in daemon_logger.handlers if isinstance(h, RotatingFileHandler)]
        assert len(file_handlers) == 1
        assert Path(file_handlers[0].baseFilename) == log_file
