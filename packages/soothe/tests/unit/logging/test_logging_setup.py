"""Tests for logging setup."""

import logging
import sys
from logging import StreamHandler
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

from soothe.config import SootheConfig
from soothe.logging import setup_logging


class TestLoggingSetup:
    """Tests for logging setup function."""

    @pytest.fixture(autouse=True)
    def clear_logger_handlers(self):
        """Clear soothe logger handlers before each test."""
        logger = logging.getLogger("soothe")
        logger.handlers.clear()
        yield
        logger.handlers.clear()

    def test_file_handler_creation(self, tmp_path: Path) -> None:
        """Test that file handler is created with correct configuration."""
        log_file = tmp_path / "test.log"
        cfg = SootheConfig(
            observability={
                "log_file_level": "INFO",
                "log_file_path": str(log_file),
                "log_file_max_bytes": 5242880,  # 5 MB
                "log_file_backup_count": 2,
            }
        )

        setup_logging(cfg)

        root_logger = logging.getLogger("soothe")
        file_handlers = [h for h in root_logger.handlers if isinstance(h, RotatingFileHandler)]
        assert len(file_handlers) == 1

        handler = file_handlers[0]
        assert handler.level == logging.INFO
        assert handler.maxBytes == 5242880
        assert handler.backupCount == 2

    def test_console_handler_not_added_when_disabled(self, tmp_path: Path) -> None:
        """Test that console handler is not added by default."""
        cfg = SootheConfig(
            observability={
                "log_file_path": str(tmp_path / "test.log"),
            }
        )

        setup_logging(cfg)

        root_logger = logging.getLogger("soothe")
        stream_handlers = [
            h
            for h in root_logger.handlers
            if isinstance(h, StreamHandler) and not isinstance(h, RotatingFileHandler)
        ]
        assert len(stream_handlers) == 0

    def test_console_handler_writes_to_stderr(self, tmp_path: Path) -> None:
        """Test that console handler writes to stderr in foreground mode."""
        cfg = SootheConfig(
            observability={
                "log_file_path": str(tmp_path / "test.log"),
            }
        )

        setup_logging(cfg, foreground=True)

        root_logger = logging.getLogger("soothe")
        stream_handlers = [
            h
            for h in root_logger.handlers
            if isinstance(h, StreamHandler) and not isinstance(h, RotatingFileHandler)
        ]
        assert len(stream_handlers) == 1

        handler = stream_handlers[0]
        assert handler.level == logging.INFO
        assert handler.stream == sys.stderr

    def test_console_handler_writes_to_stdout(self, tmp_path: Path) -> None:
        """Test console stdout stream (foreground mode always stderr now)."""
        cfg = SootheConfig(
            observability={
                "log_file_path": str(tmp_path / "test.log"),
            }
        )

        setup_logging(cfg, foreground=True)

        root_logger = logging.getLogger("soothe")
        stream_handlers = [
            h
            for h in root_logger.handlers
            if isinstance(h, StreamHandler) and not isinstance(h, RotatingFileHandler)
        ]
        assert len(stream_handlers) == 1
        assert stream_handlers[0].stream == sys.stderr

    def test_debug_flag_overrides_all_levels(self, tmp_path: Path) -> None:
        """Test that debug flag overrides file level."""
        log_file = tmp_path / "test.log"
        cfg = SootheConfig(
            debug=True,
            observability={
                "log_file_level": "WARNING",
                "log_file_path": str(log_file),
            },
        )

        setup_logging(cfg)

        root_logger = logging.getLogger("soothe")
        file_handlers = [h for h in root_logger.handlers if isinstance(h, RotatingFileHandler)]
        assert len(file_handlers) == 1
        assert file_handlers[0].level == logging.DEBUG

    def test_independent_levels_file_and_console(self, tmp_path: Path) -> None:
        """Test file and console have independent levels."""
        log_file = tmp_path / "test.log"
        cfg = SootheConfig(
            observability={
                "log_file_level": "DEBUG",
                "log_file_path": str(log_file),
            }
        )

        setup_logging(cfg, foreground=True)

        root_logger = logging.getLogger("soothe")
        file_handlers = [h for h in root_logger.handlers if isinstance(h, RotatingFileHandler)]
        stream_handlers = [
            h
            for h in root_logger.handlers
            if isinstance(h, StreamHandler) and not isinstance(h, RotatingFileHandler)
        ]

        assert len(file_handlers) == 1
        assert len(stream_handlers) == 1
        assert file_handlers[0].level == logging.DEBUG
        assert stream_handlers[0].level == logging.INFO

    def test_no_duplicate_handlers(self, tmp_path: Path) -> None:
        """Test that calling setup_logging multiple times doesn't duplicate handlers."""
        log_file = tmp_path / "test.log"
        cfg = SootheConfig(
            observability={
                "log_file_path": str(log_file),
            }
        )

        setup_logging(cfg)
        setup_logging(cfg)

        root_logger = logging.getLogger("soothe")
        file_handlers = [h for h in root_logger.handlers if isinstance(h, RotatingFileHandler)]
        assert len(file_handlers) == 1

    def test_console_format_applied(self, tmp_path: Path) -> None:
        """Test console format (uses default format)."""
        cfg = SootheConfig(
            observability={
                "log_file_path": str(tmp_path / "test.log"),
            }
        )

        setup_logging(cfg, foreground=True)

        root_logger = logging.getLogger("soothe")
        stream_handlers = [
            h
            for h in root_logger.handlers
            if isinstance(h, StreamHandler) and not isinstance(h, RotatingFileHandler)
        ]
        assert len(stream_handlers) == 1

    def test_third_party_logging_suppressed(self, tmp_path: Path) -> None:
        """Test that third-party library logging is suppressed."""
        log_file = tmp_path / "test.log"
        cfg = SootheConfig(
            observability={
                "log_file_level": "DEBUG",
                "log_file_path": str(log_file),
            }
        )

        setup_logging(cfg)

        third_party_logger = logging.getLogger("requests")
        assert third_party_logger.level >= logging.WARNING

    def test_foreground_forces_console_to_stdout(self, tmp_path: Path) -> None:
        """Test foreground enables console (stderr only)."""
        cfg = SootheConfig(
            observability={
                "log_file_path": str(tmp_path / "test.log"),
            }
        )

        setup_logging(cfg, foreground=True)

        root_logger = logging.getLogger("soothe")
        stream_handlers = [
            h
            for h in root_logger.handlers
            if isinstance(h, StreamHandler) and not isinstance(h, RotatingFileHandler)
        ]
        assert len(stream_handlers) == 1
        assert stream_handlers[0].stream == sys.stderr

    def test_foreground_console_level_overridden_by_debug(self, tmp_path: Path) -> None:
        """Test foreground console level overridden by debug flag."""
        cfg = SootheConfig(
            debug=True,
            observability={
                "log_file_path": str(tmp_path / "test.log"),
            },
        )

        setup_logging(cfg, foreground=True)

        root_logger = logging.getLogger("soothe")
        stream_handlers = [
            h
            for h in root_logger.handlers
            if isinstance(h, StreamHandler) and not isinstance(h, RotatingFileHandler)
        ]
        assert len(stream_handlers) == 1
        assert stream_handlers[0].level == logging.DEBUG

    def test_foreground_still_creates_file_handler(self, tmp_path: Path) -> None:
        """Test foreground still creates file handler."""
        log_file = tmp_path / "test.log"
        cfg = SootheConfig(
            observability={
                "log_file_path": str(log_file),
            }
        )

        setup_logging(cfg, foreground=True)

        root_logger = logging.getLogger("soothe")
        file_handlers = [h for h in root_logger.handlers if isinstance(h, RotatingFileHandler)]
        assert len(file_handlers) == 1
        assert Path(file_handlers[0].baseFilename) == log_file
