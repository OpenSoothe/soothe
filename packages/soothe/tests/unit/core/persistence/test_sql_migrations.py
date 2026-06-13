"""Unit tests for versioned PostgreSQL SQL migrations."""

from __future__ import annotations

from pathlib import Path

import pytest

from soothe.foundation.persistence.sql_migrations.runner import (
    discover_migration_scripts,
    migration_sql_root,
    run_database_migrations,
    split_sql_statements,
)


def test_split_sql_statements_splits_multiline_ddl() -> None:
    sql = """
    -- bootstrap
    CREATE TABLE foo (id INT);
    CREATE INDEX idx_foo ON foo(id);
    """
    statements = split_sql_statements(sql)
    assert len(statements) == 2
    assert statements[0].startswith("CREATE TABLE foo")
    assert statements[1].startswith("CREATE INDEX idx_foo")


def test_split_sql_statements_sloop_migration_file() -> None:
    scripts = discover_migration_scripts("soothe_checkpoints", sql_root=migration_sql_root())
    sloop_script = next(s for s in scripts if s.name == "sloop_tables")
    statements = split_sql_statements(sloop_script.sql)
    assert len(statements) >= 10
    assert any(
        stmt.startswith("CREATE TABLE IF NOT EXISTS sloop_checkpoints") for stmt in statements
    )


def test_migration_sql_root_contains_checkpoints_scripts() -> None:
    root = migration_sql_root()
    scripts = discover_migration_scripts("soothe_checkpoints", sql_root=root)
    versions = [s.version for s in scripts]
    assert versions == ["000", "001"]
    assert scripts[0].name == "migration_tracking"
    assert scripts[1].name == "sloop_tables"
    assert "soothe_schema_migrations" in scripts[0].sql
    assert "sloop_checkpoints" in scripts[1].sql
    assert "client_workspace TEXT" in scripts[1].sql


def test_discover_rejects_invalid_filename(tmp_path: Path) -> None:
    db_dir = tmp_path / "soothe_checkpoints"
    db_dir.mkdir()
    (db_dir / "bad.sql").write_text("SELECT 1", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid migration filename"):
        discover_migration_scripts("soothe_checkpoints", sql_root=tmp_path)


def test_discover_sorts_by_version_prefix(tmp_path: Path) -> None:
    db_dir = tmp_path / "soothe_checkpoints"
    db_dir.mkdir()
    (db_dir / "010_second.sql").write_text("SELECT 2", encoding="utf-8")
    (db_dir / "002_first.sql").write_text("SELECT 1", encoding="utf-8")
    scripts = discover_migration_scripts("soothe_checkpoints", sql_root=tmp_path)
    assert [s.version for s in scripts] == ["002", "010"]


@pytest.mark.asyncio
async def test_run_database_migrations_applies_pending_scripts(tmp_path: Path) -> None:
    pytest.importorskip("psycopg_pool")
    from unittest.mock import AsyncMock, MagicMock

    db_dir = tmp_path / "soothe_checkpoints"
    db_dir.mkdir()
    (db_dir / "000_track.sql").write_text(
        "CREATE TABLE soothe_schema_migrations (version TEXT PRIMARY KEY)",
        encoding="utf-8",
    )
    (db_dir / "001_data.sql").write_text("CREATE TABLE demo (id INT)", encoding="utf-8")

    cur = AsyncMock()
    conn = MagicMock()
    conn.set_autocommit = AsyncMock()
    conn.transaction.return_value.__aenter__ = AsyncMock()
    conn.transaction.return_value.__aexit__ = AsyncMock(return_value=None)
    conn.cursor.return_value.__aenter__ = AsyncMock(return_value=cur)
    conn.cursor.return_value.__aexit__ = AsyncMock(return_value=None)

    pool = MagicMock()
    pool.connection.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.connection.return_value.__aexit__ = AsyncMock(return_value=None)

    fetch_error = Exception('relation "soothe_schema_migrations" does not exist')
    cur.fetchone = AsyncMock(side_effect=[fetch_error, None])
    cur.fetchall = AsyncMock(return_value=[])

    applied = await run_database_migrations(pool, "soothe_checkpoints", sql_root=tmp_path)

    assert applied == ["000", "001"]
    execute_sql = [call.args[0] for call in cur.execute.call_args_list]
    assert any("CREATE TABLE soothe_schema_migrations" in stmt for stmt in execute_sql)
    assert any("CREATE TABLE demo" in stmt for stmt in execute_sql)
    insert_stmts = [s for s in execute_sql if "INSERT INTO soothe_schema_migrations" in s]
    assert len(insert_stmts) == 2
