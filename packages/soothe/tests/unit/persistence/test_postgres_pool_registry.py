"""Unit tests for PostgresPoolRegistry."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe.config import SootheConfig


def _postgres_config(**overrides: object) -> SootheConfig:
    base = {
        "persistence": {
            "default_backend": "postgresql",
            "postgres_base_dsn": "postgresql://postgres:postgres@127.0.0.1:6432",
            "checkpoints_pool_size": 32,
            "metadata_pool_size": 16,
            "vectors_pool_size": 16,
        },
        "vector_stores": [
            {"name": "pgvector_dev", "provider_type": "pgvector"},
        ],
        "vector_store_router": {"default": "pgvector_dev:soothe_default"},
    }
    if overrides:
        base.update(overrides)
    return SootheConfig(**base)


class TestPostgresPoolRegistry:
    def test_resolve_pool_sizes(self) -> None:
        cfg = _postgres_config()
        from soothe.persistence.postgres_pool_registry import PostgresPoolRegistry

        assert PostgresPoolRegistry.resolve_checkpoints_pool_size(cfg) == 32
        assert PostgresPoolRegistry.resolve_metadata_pool_size(cfg) == 16
        assert PostgresPoolRegistry.resolve_vectors_pool_size(cfg) == 16

    def test_validate_budget_warns_when_high(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        cfg = _postgres_config(
            persistence={
                "default_backend": "postgresql",
                "postgres_base_dsn": "postgresql://postgres:postgres@127.0.0.1:6432",
                "checkpoints_pool_size": 80,
                "metadata_pool_size": 40,
                "vectors_pool_size": 40,
                "postgres_connection_budget_warn": 100,
            }
        )
        from soothe.persistence.postgres_pool_registry import PostgresPoolRegistry

        with caplog.at_level(logging.WARNING):
            PostgresPoolRegistry.validate_budget(cfg)
        assert any("pool budget high" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_open_all_binds_three_pools(self) -> None:
        from soothe.persistence.postgres_pool_registry import PostgresPoolRegistry

        PostgresPoolRegistry.reset_instance()
        cfg = _postgres_config()

        mock_pool = MagicMock()
        mock_pool.closed = False
        mock_pool.get_stats.return_value = {
            "pool_size": 1,
            "pool_available": 1,
            "requests_waiting": 0,
        }

        with (
            patch(
                "soothe.persistence.postgres_provisioning.ensure_postgres_databases_async",
                new_callable=AsyncMock,
            ),
            patch("psycopg_pool.AsyncConnectionPool", return_value=mock_pool) as mock_cls,
            patch.object(mock_pool, "open", new_callable=AsyncMock),
            patch(
                "soothe.sloop.checkpoints.postgres_schema.initialize_agentloop_postgres_schema",
                new_callable=AsyncMock,
            ),
            patch(
                "soothe.persistence.db_init.initialize_database",
                new_callable=AsyncMock,
            ),
        ):
            registry = PostgresPoolRegistry.get_instance(cfg)
            await registry.open_all()

            assert mock_cls.call_count == 3
            assert registry.try_get_pool("checkpoints") is mock_pool
            assert registry.try_get_pool("metadata") is mock_pool
            assert registry.try_get_pool("vectors") is mock_pool

            await registry.close_all()

        assert PostgresPoolRegistry.try_get_instance() is None
