"""Unit tests for worker runner reuse helpers (IG-506)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from soothe_daemon.runner._worker_runner import acquire_worker_runner


@patch("soothe.runner.SootheRunner")
def test_acquire_worker_runner_reuses_cached(mock_runner_cls: MagicMock) -> None:
    """Cached runner is reset and returned when reuse is enabled."""
    cached = MagicMock()
    config = MagicMock()

    runner, updated = acquire_worker_runner(
        config=config,
        cached_runner=cached,
        reuse_runner=True,
        warmup_runner=False,
    )

    assert runner is cached
    assert updated is cached
    cached.prepare_for_request.assert_called_once()
    mock_runner_cls.assert_not_called()


@patch("soothe.runner.SootheRunner")
def test_acquire_worker_runner_warmup_creates_runner(mock_runner_cls: MagicMock) -> None:
    """Warmup path creates a runner when cache is empty."""
    created = MagicMock()
    mock_runner_cls.return_value = created
    config = MagicMock()

    runner, updated = acquire_worker_runner(
        config=config,
        cached_runner=None,
        reuse_runner=True,
        warmup_runner=True,
    )

    assert runner is created
    assert updated is created
    mock_runner_cls.assert_called_once()
