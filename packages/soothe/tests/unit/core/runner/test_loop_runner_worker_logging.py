"""Tests for loop worker file logging (RFC-221)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

import soothe.config as soothe_config
from soothe.config.settings import SootheConfig
from soothe.core.runner.worker_logging import (
    RUNNER_LOG_FILENAME,
    configure_loop_runner_worker_logging,
)


@pytest.fixture
def soothe_home_tmp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(soothe_config, "SOOTHE_HOME", tmp_path)
    return tmp_path


def test_configure_writes_runner_log(soothe_home_tmp: Path) -> None:
    cfg = SootheConfig()
    loop_id = "019e0bcd-fead-7531-a0bb-b6d1dfba353f"

    root = logging.getLogger("soothe")
    root.handlers.clear()

    path = configure_loop_runner_worker_logging(cfg, loop_id)
    assert path is not None
    expected = soothe_home_tmp / "data" / "loops" / loop_id / RUNNER_LOG_FILENAME
    assert path == expected
    assert path.exists()

    root.handlers.clear()


def test_configure_skips_empty_loop_id(soothe_home_tmp: Path) -> None:
    cfg = SootheConfig()
    root = logging.getLogger("soothe")
    root.handlers.clear()

    assert configure_loop_runner_worker_logging(cfg, "") is None
    assert configure_loop_runner_worker_logging(cfg, "   ") is None

    root.handlers.clear()


def test_configure_idempotent_same_path(soothe_home_tmp: Path) -> None:
    cfg = SootheConfig()
    loop_id = "loop-idem-1"

    root = logging.getLogger("soothe")
    root.handlers.clear()

    p1 = configure_loop_runner_worker_logging(cfg, loop_id)
    handlers_after_first = len(root.handlers)
    p2 = configure_loop_runner_worker_logging(cfg, loop_id)

    assert p1 == p2
    assert len(root.handlers) == handlers_after_first

    root.handlers.clear()
