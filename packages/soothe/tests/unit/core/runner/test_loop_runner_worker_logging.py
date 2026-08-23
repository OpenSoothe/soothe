"""Tests for loop worker file logging (RFC-221)."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

import soothe.config as soothe_config
from soothe.config.settings import SootheConfig
from soothe.logging import COMMUNITY_LOGGER_NAME, PACKAGE_LOGGER_NAMES
from soothe.runner import worker_logging as _worker_logging
from soothe.runner.worker_logging import (
    RUNNER_LOG_FILENAME,
    configure_loop_runner_worker_logging,
    release_loop_runner_logging,
)


@pytest.fixture
def soothe_home_tmp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(soothe_config, "SOOTHE_HOME", tmp_path)
    return tmp_path


@pytest.fixture(autouse=True)
def _reset_active_loop_ids() -> None:
    """Clear the process-level active-loop set between tests."""
    with _worker_logging._active_loop_ids_lock:
        _worker_logging._active_loop_ids.clear()
    yield
    with _worker_logging._active_loop_ids_lock:
        _worker_logging._active_loop_ids.clear()


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
    """Pooled workers must not accumulate runner.log handlers across loop runs.

    Once a loop's request has ended (``release_loop_runner_logging``), a later
    ``configure`` call for a different loop may tear down the stale handler.
    """
    cfg = SootheConfig()
    loop_a = "loop-a-1111"
    loop_b = "loop-b-2222"

    _clear_package_handlers()

    path_a = configure_loop_runner_worker_logging(cfg, loop_a)
    # Loop A's request finished — release the in-flight marker.
    release_loop_runner_logging(loop_a)
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


def test_active_loop_handler_not_torn_down(soothe_home_tmp: Path) -> None:
    """An in-flight loop's handler must survive another loop's configure call.

    Regression for the d15f incident: pooled ThreadPool workers share one
    process and the same ``soothe.*`` package loggers. When worker-1
    configured loop B, ``_remove_stale_loop_runner_handlers`` tore down
    worker-0's still-active handler for loop A, silencing loop A's
    runner.log 12 min before its crash.
    """
    cfg = SootheConfig()
    loop_a = "loop-a-active"
    loop_b = "loop-b-other"

    _clear_package_handlers()

    path_a = configure_loop_runner_worker_logging(cfg, loop_a)
    # Loop A is still in-flight (no release) when loop B is configured on
    # another worker thread sharing this process.
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
        # Both handlers must remain attached — loop A is still writing.
        handler_paths = {Path(h.baseFilename).resolve() for h in loop_handlers}
        assert path_a.resolve() in handler_paths
        assert path_b.resolve() in handler_paths

    # After loop A's request finishes, a subsequent configure for loop C
    # may finally tear down loop A's handler.
    release_loop_runner_logging(loop_a)
    path_c = configure_loop_runner_worker_logging(cfg, "loop-c-after")
    for name in PACKAGE_LOGGER_NAMES:
        pkg_logger = logging.getLogger(name)
        handler_paths = {
            Path(h.baseFilename).resolve()
            for h in pkg_logger.handlers
            if isinstance(h, RotatingFileHandler)
            and getattr(h, "baseFilename", "").endswith(RUNNER_LOG_FILENAME)
        }
        # Loop A's handler is gone; B (still active) and C remain.
        assert path_a.resolve() not in handler_paths
        assert path_b.resolve() in handler_paths
        assert path_c is not None and path_c.resolve() in handler_paths

    release_loop_runner_logging(loop_b)
    release_loop_runner_logging("loop-c-after")
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
