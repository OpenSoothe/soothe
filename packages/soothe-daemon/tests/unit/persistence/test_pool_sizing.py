"""Pool sizing helpers for thread_pool + PostgreSQL."""

from soothe_daemon.persistence.pool_sizing import (
    recommended_checkpointer_pool_size,
    recommended_sloop_pool_size,
)


def test_recommended_sloop_pool_size() -> None:
    assert recommended_sloop_pool_size(max_thread_workers=6) == 8
    assert recommended_sloop_pool_size(max_thread_workers=30) == 32


def test_recommended_checkpointer_pool_size() -> None:
    assert recommended_checkpointer_pool_size(max_thread_workers=6) == 5
    assert recommended_checkpointer_pool_size(max_thread_workers=2) == 3
