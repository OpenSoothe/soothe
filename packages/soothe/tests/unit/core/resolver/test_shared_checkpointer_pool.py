"""Shared checkpointer pool singleton (per-process)."""

from __future__ import annotations

import pytest

from soothe.config import SootheConfig
from soothe.core.resolver.shared_checkpointer_pool import SharedCheckpointerPool


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    """Isolate singleton between tests."""
    import soothe.core.resolver.shared_checkpointer_pool as mod

    mod._shared_checkpointer_pool = None
    yield
    mod._shared_checkpointer_pool = None


def test_get_or_create_returns_same_pool_instance() -> None:
    pytest.importorskip("psycopg_pool")
    pytest.importorskip("langgraph.checkpoint.postgres.aio")

    cfg = SootheConfig(
        persistence={
            "default_backend": "postgresql",
            "postgres_base_dsn": "postgresql://postgres:postgres@127.0.0.1:6432",
            "checkpointer_pool_size": 3,
        }
    )
    p1 = SharedCheckpointerPool.get_or_create_pool(cfg)
    p2 = SharedCheckpointerPool.get_or_create_pool(cfg)
    assert p1 is not None
    assert p1 is p2
    assert SharedCheckpointerPool.is_shared_pool(p1)


def test_is_shared_pool_false_for_foreign_pool() -> None:
    pytest.importorskip("psycopg_pool")

    cfg = SootheConfig(
        persistence={
            "default_backend": "postgresql",
            "postgres_base_dsn": "postgresql://postgres:postgres@127.0.0.1:6432",
        }
    )
    pool = SharedCheckpointerPool.get_or_create_pool(cfg)
    assert pool is not None
    assert not SharedCheckpointerPool.is_shared_pool(object())
