"""Tests for loop worker file logging (RFC-221)."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

import soothe.config as soothe_config
from soothe.config.settings import SootheConfig
from soothe.logging import COMMUNITY_LOGGER_NAME, PACKAGE_LOGGER_NAMES
from soothe.runner.worker_logging import (
    RUNNER_LOG_FILENAME,
    configure_loop_runner_worker_logging,
)


@pytest.fixture
def soothe_home_tmp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(soothe_config, "SOOTHE_HOME", tmp_path)
    return tmp_path


def _clear_package_handlers() -> None:
    for name in PACKAGE_LOGGER_NAMES:
        logging.getLogger(name).handlers.clear()


def test_configure_writes_runner_log(soothe_home_tmp: Path) -> None:
    cfg = SootheConfig()
    loop_id = "019e0bcd-fead-7531-a0bb-b6d1dfba353f"

    _clear_package_handlers()

    path = configure_loop_runner_worker_logging(cfg, loop_id)
    assert path is not None
    expected = soothe_home_tmp / "data" / "loops" / loop_id / RUNNER_LOG_FILENAME
    assert path == expected
    assert path.exists()

    community = logging.getLogger(COMMUNITY_LOGGER_NAME)
    community_handlers = [h for h in community.handlers if isinstance(h, RotatingFileHandler)]
    assert len(community_handlers) == 1
    assert Path(community_handlers[0].baseFilename) == path

    _clear_package_handlers()


def test_configure_sets_log_context_to_loop_id(soothe_home_tmp: Path) -> None:
    """Worker log tags use the daemon loop_id, not a separate checkpoint id."""
    from soothe_nano.logging.context import get_thread_id

    cfg = SootheConfig()
    loop_id = "019e0bcd-fead-7531-a0bb-b6d1dfba353f"
    _clear_package_handlers()

    configure_loop_runner_worker_logging(cfg, loop_id)
    assert get_thread_id() == loop_id
    _clear_package_handlers()


def test_configure_skips_empty_loop_id(soothe_home_tmp: Path) -> None:
    cfg = SootheConfig()
    _clear_package_handlers()

    assert configure_loop_runner_worker_logging(cfg, "") is None
    assert configure_loop_runner_worker_logging(cfg, "   ") is None

    _clear_package_handlers()


def test_configure_replaces_handler_when_loop_id_changes(soothe_home_tmp: Path) -> None:
    """Pooled workers must not accumulate runner.log handlers across loop runs."""
    cfg = SootheConfig()
    loop_a = "loop-a-1111"
    loop_b = "loop-b-2222"

    _clear_package_handlers()

    path_a = configure_loop_runner_worker_logging(cfg, loop_a)
    path_b = configure_loop_runner_worker_logging(cfg, loop_b)
    assert path_a is not None and path_b is not None

    for name in PACKAGE_LOGGER_NAMES:
        pkg_logger = logging.getLogger(name)
        loop_handlers = [
            h
            for h in pkg_logger.handlers
            if isinstance(h, RotatingFileHandler)
            and getattr(h, "baseFilename", "").endswith(RUNNER_LOG_FILENAME)
        ]
        assert len(loop_handlers) == 1
        assert Path(loop_handlers[0].baseFilename).resolve() == path_b.resolve()

    _clear_package_handlers()


def test_configure_idempotent_same_path(soothe_home_tmp: Path) -> None:
    cfg = SootheConfig()
    loop_id = "loop-idem-1"

    _clear_package_handlers()

    p1 = configure_loop_runner_worker_logging(cfg, loop_id)
    soothe_handlers_after_first = len(logging.getLogger("soothe").handlers)
    community_handlers_after_first = len(logging.getLogger(COMMUNITY_LOGGER_NAME).handlers)
    p2 = configure_loop_runner_worker_logging(cfg, loop_id)

    assert p1 == p2
    assert len(logging.getLogger("soothe").handlers) == soothe_handlers_after_first
    assert len(logging.getLogger(COMMUNITY_LOGGER_NAME).handlers) == community_handlers_after_first

    _clear_package_handlers()
