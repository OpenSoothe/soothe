"""Tests for daemon logging setup."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest
from soothe.config import SootheConfig
from soothe.logging import setup_logging
from soothe.logging.setup import PACKAGE_LOGGER_NAMES

from soothe_daemon.bootstrap.logging import (
    DEFAULT_DAEMON_LOG,
    default_daemon_log_path,
    setup_daemon_logging,
)


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

    def test_default_daemon_log_path_ends_with_daemon_log(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Default path is under SOOTHE_HOME/logs/daemon.log."""
        home = Path("/tmp/soothe-test-home")
        monkeypatch.setattr("soothe_daemon.bootstrap.logging.SOOTHE_HOME", str(home))
        assert default_daemon_log_path() == home / "logs" / DEFAULT_DAEMON_LOG

    def test_setup_daemon_logging_uses_explicit_log_file(self, tmp_path: Path) -> None:
        """setup_daemon_logging honors custom log_file."""
        log_file = tmp_path / "custom-daemon.log"
        setup_daemon_logging(log_file=str(log_file))

        daemon_logger = logging.getLogger("soothe_daemon")
        file_handlers = [h for h in daemon_logger.handlers if isinstance(h, RotatingFileHandler)]
        assert len(file_handlers) == 1
        assert Path(file_handlers[0].baseFilename) == log_file

    def test_daemon_and_soothe_use_separate_default_log_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Daemon startup keeps soothe.* on soothe.log, not daemon.log."""
        home = tmp_path / "soothe-home"
        monkeypatch.setattr("soothe_daemon.bootstrap.logging.SOOTHE_HOME", str(home))
        monkeypatch.setattr("soothe.logging.setup.SOOTHE_HOME", str(home))

        cfg = SootheConfig()
        setup_logging(cfg)
        setup_daemon_logging(log_file=str(default_daemon_log_path()))

        daemon_log = default_daemon_log_path()
        soothe_log = home / "logs" / "soothe.log"

        daemon_handlers = [
            h
            for h in logging.getLogger("soothe_daemon").handlers
            if isinstance(h, RotatingFileHandler)
        ]
        soothe_handlers = [
            h
            for name in PACKAGE_LOGGER_NAMES
            for h in logging.getLogger(name).handlers
            if isinstance(h, RotatingFileHandler)
        ]

        assert len(daemon_handlers) == 1
        assert Path(daemon_handlers[0].baseFilename) == daemon_log
        assert len(soothe_handlers) >= 1
        assert all(Path(h.baseFilename) == soothe_log for h in soothe_handlers)
        assert daemon_log != soothe_log
