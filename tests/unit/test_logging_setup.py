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
            logging={
                "file": {
                    "level": "INFO",
                    "path": str(log_file),
                    "max_bytes": 5242880,  # 5 MB
                    "backup_count": 2,
                }
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
        """Test that console handler is not added when disabled."""
        cfg = SootheConfig(
            logging={
                "file": {"path": str(tmp_path / "test.log")},
                "console": {"enabled": False},
            }
        )

        setup_logging(cfg)

        root_logger = logging.getLogger("soothe")
        stream_handlers = [
            h for h in root_logger.handlers if isinstance(h, StreamHandler) and not isinstance(h, RotatingFileHandler)
        ]
        assert len(stream_handlers) == 0

    def test_console_handler_writes_to_stderr(self, tmp_path: Path) -> None:
        """Test that console handler writes to stderr when enabled."""
        cfg = SootheConfig(
            logging={
                "file": {"path": str(tmp_path / "test.log")},
                "console": {
                    "enabled": True,
                    "level": "WARNING",
                    "stream": "stderr",
                },
            }
        )

        setup_logging(cfg)

        root_logger = logging.getLogger("soothe")
        stream_handlers = [
            h for h in root_logger.handlers if isinstance(h, StreamHandler) and not isinstance(h, RotatingFileHandler)
        ]
        assert len(stream_handlers) == 1

        handler = stream_handlers[0]
        assert handler.level == logging.WARNING
        assert handler.stream == sys.stderr

    def test_console_handler_writes_to_stdout(self, tmp_path: Path) -> None:
        """Test that console handler writes to stdout when configured."""
        cfg = SootheConfig(
            logging={
                "file": {"path": str(tmp_path / "test.log")},
                "console": {
                    "enabled": True,
                    "level": "INFO",
                    "stream": "stdout",
                },
            }
        )

        setup_logging(cfg)

        root_logger = logging.getLogger("soothe")
        stream_handlers = [
            h for h in root_logger.handlers if isinstance(h, StreamHandler) and not isinstance(h, RotatingFileHandler)
        ]
        assert len(stream_handlers) == 1

        handler = stream_handlers[0]
        assert handler.level == logging.INFO
        assert handler.stream == sys.stdout

    def test_debug_flag_overrides_all_levels(self, tmp_path: Path) -> None:
        """Test that debug flag sets all handlers to DEBUG level."""
        cfg = SootheConfig(
            debug=True,
            logging={
                "file": {"path": str(tmp_path / "test.log"), "level": "INFO"},
                "console": {"enabled": True, "level": "WARNING"},
            },
        )

        setup_logging(cfg)

        root_logger = logging.getLogger("soothe")
        assert root_logger.level == logging.DEBUG

        for handler in root_logger.handlers:
            assert handler.level == logging.DEBUG

    def test_independent_levels_file_and_console(self, tmp_path: Path) -> None:
        """Test that file and console can have independent log levels."""
        cfg = SootheConfig(
            logging={
                "file": {"path": str(tmp_path / "test.log"), "level": "DEBUG"},
                "console": {"enabled": True, "level": "WARNING"},
            }
        )

        setup_logging(cfg)

        root_logger = logging.getLogger("soothe")

        file_handlers = [h for h in root_logger.handlers if isinstance(h, RotatingFileHandler)]
        assert len(file_handlers) == 1
        assert file_handlers[0].level == logging.DEBUG

        stream_handlers = [
            h for h in root_logger.handlers if isinstance(h, StreamHandler) and not isinstance(h, RotatingFileHandler)
        ]
        assert len(stream_handlers) == 1
        assert stream_handlers[0].level == logging.WARNING

    def test_no_duplicate_handlers(self, tmp_path: Path) -> None:
        """Test that calling setup_logging multiple times doesn't add duplicate handlers."""
        cfg = SootheConfig(logging={"file": {"path": str(tmp_path / "test.log")}})

        setup_logging(cfg)
        setup_logging(cfg)

        root_logger = logging.getLogger("soothe")
        file_handlers = [h for h in root_logger.handlers if isinstance(h, RotatingFileHandler)]
        assert len(file_handlers) == 1

    def test_console_format_applied(self, tmp_path: Path) -> None:
        """Test that custom console format is applied."""
        custom_format = "%(name)s - %(message)s"
        cfg = SootheConfig(
            logging={
                "file": {"path": str(tmp_path / "test.log")},
                "console": {
                    "enabled": True,
                    "format": custom_format,
                },
            }
        )

        setup_logging(cfg)

        root_logger = logging.getLogger("soothe")
        stream_handlers = [
            h for h in root_logger.handlers if isinstance(h, StreamHandler) and not isinstance(h, RotatingFileHandler)
        ]
        assert len(stream_handlers) == 1

        handler = stream_handlers[0]
        assert handler.formatter._fmt == custom_format

    def test_third_party_logging_suppressed(self, tmp_path: Path) -> None:
        """Test that noisy third-party loggers are suppressed to WARNING."""
        cfg = SootheConfig(logging={"file": {"path": str(tmp_path / "test.log")}})

        setup_logging(cfg)

        noisy_loggers = [
            "httpx",
            "httpcore",
            "openai",
            "anthropic",
            "langchain_core",
            "langgraph",
            "browser_use",
            "bubus",
            "cdp_use",
        ]

        for name in noisy_loggers:
            logger = logging.getLogger(name)
            assert logger.level == logging.WARNING
