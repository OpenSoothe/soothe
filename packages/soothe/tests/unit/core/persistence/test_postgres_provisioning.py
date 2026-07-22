"""Unit tests for PostgreSQL database auto-provisioning."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from soothe.config import SootheConfig
from soothe.persistence.postgres_provisioning import (
    ensure_postgres_databases,
    postgres_admin_dsn,
    postgres_target_dsn,
    required_postgres_database_keys,
    reset_provision_cache_for_tests,
    uses_postgresql_persistence,
    validate_database_name,
)


@pytest.fixture(autouse=True)
def _clear_provision_cache() -> None:
    reset_provision_cache_for_tests()


def test_validate_database_name_rejects_invalid() -> None:
    with pytest.raises(ValueError, match="Invalid PostgreSQL database name"):
        validate_database_name("bad-name")


def test_postgres_admin_dsn_replaces_path() -> None:
    assert (
        postgres_admin_dsn("postgresql://user:pass@localhost:5432")
        == "postgresql://user:pass@localhost:5432/postgres"
    )


def test_postgres_target_dsn_builds_database_path() -> None:
    assert (
        postgres_target_dsn("postgresql://user:pass@localhost:5432", "soothe_checkpoints")
        == "postgresql://user:pass@localhost:5432/soothe_checkpoints"
    )


def test_required_keys_empty_without_base_dsn() -> None:
    cfg = SootheConfig()
    cfg.persistence.postgres_base_dsn = None
    cfg.persistence.default_backend = "postgresql"
    assert required_postgres_database_keys(cfg) == frozenset()


def test_required_keys_all_when_postgres_in_use() -> None:
    cfg = SootheConfig()
    cfg.persistence.postgres_base_dsn = "postgresql://postgres:postgres@127.0.0.1:6432"
    cfg.persistence.default_backend = "postgresql"
    assert required_postgres_database_keys(cfg) == frozenset(
        {"checkpoints", "metadata", "vectors", "memory"}
    )


def test_uses_postgresql_when_pgvector_configured() -> None:
    cfg = SootheConfig()
    cfg.persistence.default_backend = "sqlite"
    cfg.vector_stores[0].provider_type = "pgvector"
    assert uses_postgresql_persistence(cfg) is True


@patch("soothe_nano.persistence.postgres_provisioning._initialize_postgres_schemas")
@patch("psycopg.connect")
def test_ensure_postgres_databases_creates_missing(
    mock_connect: MagicMock, mock_init_schemas: MagicMock
) -> None:
    pytest.importorskip("psycopg")

    cfg = SootheConfig()
    cfg.persistence.postgres_base_dsn = "postgresql://postgres:postgres@127.0.0.1:6432"
    cfg.persistence.default_backend = "postgresql"

    conn = MagicMock()
    cur = MagicMock()
    conn.__enter__.return_value = conn
    conn.cursor.return_value.__enter__.return_value = cur
    mock_connect.return_value = conn

    fetch_results = {
        "soothe_checkpoints": object(),
        "soothe_metadata": None,
        "soothe_vectors": None,
        "soothe_memory": object(),
    }

    def _fetchone_side_effect() -> object | None:
        sql_args = cur.execute.call_args[0]
        query = sql_args[0]
        if "pg_database" in query:
            db_name = sql_args[1][0]
            return fetch_results[db_name]
        return None

    cur.fetchone.side_effect = _fetchone_side_effect

    created = ensure_postgres_databases(cfg)

    assert created == ["soothe_metadata", "soothe_vectors"]
    select_calls = [
        call
        for call in cur.execute.call_args_list
        if call.args and isinstance(call.args[0], str) and "pg_database" in call.args[0]
    ]
    assert len(select_calls) == 4
    assert cur.execute.call_count == 6
    mock_init_schemas.assert_called_once()


@patch("soothe_nano.persistence.postgres_provisioning._initialize_postgres_schemas")
@patch("psycopg.connect")
def test_ensure_postgres_databases_is_idempotent_per_process(
    mock_connect: MagicMock,
    mock_init_schemas: MagicMock,
) -> None:
    pytest.importorskip("psycopg")

    cfg = SootheConfig()
    cfg.persistence.postgres_base_dsn = "postgresql://postgres:postgres@127.0.0.1:6432"
    cfg.persistence.default_backend = "postgresql"

    conn = MagicMock()
    cur = MagicMock()
    conn.__enter__.return_value = conn
    conn.cursor.return_value.__enter__.return_value = cur
    mock_connect.return_value = conn
    cur.fetchone.return_value = object()

    assert ensure_postgres_databases(cfg) == []
    assert ensure_postgres_databases(cfg) == []
    mock_connect.assert_called_once()
    mock_init_schemas.assert_called_once()
