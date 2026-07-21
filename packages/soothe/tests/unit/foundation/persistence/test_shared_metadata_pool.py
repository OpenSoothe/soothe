"""Unit tests for shared metadata PostgreSQL pool."""

from __future__ import annotations

from soothe.config import SootheConfig
from soothe.config.models import PersistenceConfig
from soothe.foundation.persistence.shared_metadata_pool import SharedMetadataPool


def test_get_or_create_pool_returns_none_for_sqlite() -> None:
    cfg = SootheConfig(persistence=PersistenceConfig(default_backend="sqlite"))
    assert SharedMetadataPool.get_or_create_pool(cfg) is None


def test_get_or_create_pool_uses_metadata_pool_size(monkeypatch) -> None:
    cfg = SootheConfig(
        persistence=PersistenceConfig(
            default_backend="postgresql",
            postgres_base_dsn="postgresql://postgres:postgres@localhost:5432",
            metadata_pool_size=40,
        ),
        agent={
            "protocols": {"durability": {"backend": "postgresql", "checkpointer": "postgresql"}}
        },
    )

    captured: dict[str, int] = {}

    class FakePool:
        closed = False

        def __init__(self, dsn: str, **kwargs: object) -> None:
            captured["max_size"] = int(kwargs["max_size"])  # type: ignore[arg-type]

    monkeypatch.setattr(
        "psycopg_pool.AsyncConnectionPool",
        FakePool,
    )
    monkeypatch.setattr(
        "soothe_nano.persistence.postgres_provisioning.ensure_postgres_databases",
        lambda _config: None,
    )
    monkeypatch.setattr(SharedMetadataPool, "_shared_metadata_pool", None, raising=False)

    pool = SharedMetadataPool.get_or_create_pool(cfg)
    assert pool is not None
    assert captured["max_size"] == 40
