"""Tests for PostgreSQL pool sizing helpers."""

from soothe_daemon.persistence.pool_sizing import recommended_checkpoints_pool_size


def test_recommended_checkpoints_pool_size() -> None:
    assert recommended_checkpoints_pool_size(max_thread_workers=6) == 8
    assert recommended_checkpoints_pool_size(max_thread_workers=30) == 32
    assert recommended_checkpoints_pool_size(max_thread_workers=2) == 4
