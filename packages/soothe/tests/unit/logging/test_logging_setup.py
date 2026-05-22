"""Tests for logging setup."""

import logging
import sys
from logging import StreamHandler
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

from soothe.config import SootheConfig
from soothe.logging import setup_logging
from soothe.logging.setup import COMMUNITY_LOGGER_NAME, PACKAGE_LOGGER_NAMES


class TestLoggingSetup:
    """Tests for logging setup function."""

    @pytest.fixture(autouse=True)
    def clear_logger_handlers(self):
        """Clear package logger handlers before each test."""
        for name in PACKAGE_LOGGER_NAMES:
            logging.getLogger(name).handlers.clear()
        yield
        for name in PACKAGE_LOGGER_NAMES:
            logging.getLogger(name).handlers.clear()

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

    def test_community_logger_receives_file_handler(self, tmp_path: Path) -> None:
        """soothe_community.* loggers share the same rotating file handler as soothe.*."""
        log_file = tmp_path / "test.log"
        cfg = SootheConfig(
            observability={
                "log_file_level": "INFO",
                "log_file_path": str(log_file),
            }
        )

        setup_logging(cfg)

        community_logger = logging.getLogger(COMMUNITY_LOGGER_NAME)
        file_handlers = [h for h in community_logger.handlers if isinstance(h, RotatingFileHandler)]
        assert len(file_handlers) == 1
        assert Path(file_handlers[0].baseFilename) == log_file

        community_logger.info("community runtime probe")
        assert "community runtime probe" in log_file.read_text(encoding="utf-8")

    def test_no_duplicate_handlers_on_community_logger(self, tmp_path: Path) -> None:
        """Repeated setup_logging does not duplicate soothe_community file handlers."""
        log_file = tmp_path / "test.log"
        cfg = SootheConfig(
            observability={
                "log_file_path": str(log_file),
            }
        )

        setup_logging(cfg)
        setup_logging(cfg)

        community_logger = logging.getLogger(COMMUNITY_LOGGER_NAME)
        file_handlers = [h for h in community_logger.handlers if isinstance(h, RotatingFileHandler)]
        assert len(file_handlers) == 1


class TestThreadFormatter:
    """Tests for conversation thread id tags in log lines."""

    def test_thread_tag_shows_last_four_chars_only(self) -> None:
        """Log tag uses the last four characters of the conversation thread id."""
        from soothe.logging.context import set_thread_id
        from soothe.logging.setup import ThreadFormatter

        set_thread_id("abcdefghijklmnop")
        try:
            fmt = ThreadFormatter("%(thread_id)s %(message)s")
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="",
                lineno=0,
                msg="x",
                args=(),
                exc_info=None,
            )
            line = fmt.format(record)
        finally:
            set_thread_id(None)

        assert line.startswith("[mnop]")

    def test_thread_tag_uuid7_loops_differ_by_suffix(self) -> None:
        """UUID7 loop ids created in the same second get distinct suffix tags."""
        from soothe.logging.context import set_thread_id
        from soothe.logging.setup import ThreadFormatter, _short_thread_id_for_log

        a = "019e3fe2-bcea-78d0-81d7-bb6656b1a56b"
        b = "019e3fe5-5a47-7443-8722-1844f8cfa4e5"
        assert _short_thread_id_for_log(a) == "a56b"
        assert _short_thread_id_for_log(b) == "a4e5"
        assert _short_thread_id_for_log(a) != _short_thread_id_for_log(b)

        fmt = ThreadFormatter("%(thread_id)s %(message)s")
        set_thread_id(a)
        try:
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="",
                lineno=0,
                msg="x",
                args=(),
                exc_info=None,
            )
            assert fmt.format(record).startswith("[a56b]")
        finally:
            set_thread_id(None)

    def test_thread_tag_main_when_no_context(self) -> None:
        """Without set_thread_id, tag is ``[main]``."""
        from soothe.logging.context import set_thread_id
        from soothe.logging.setup import ThreadFormatter

        set_thread_id(None)
        fmt = ThreadFormatter("%(thread_id)s %(message)s")
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="x",
            args=(),
            exc_info=None,
        )
        line = fmt.format(record)
        assert line.startswith("[main]")
