"""Unit tests for idempotent PostgreSQL database init scripts and migrations."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.foundation.persistence.db_init.runner import (
    database_sql_root,
    discover_versioned_scripts,
    initialize_database,
    load_init_script,
    run_database_init,
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


def test_checkpoints_init_script_contains_core_tables() -> None:
    """IG-678 PR-3: checkpoints init is host-owned; load from the host sql root."""
    from soothe.foundation.persistence.postgres_schema import _HOST_SQL_ROOT

    sql = load_init_script("soothe_checkpoints", sql_root=_HOST_SQL_ROOT)
    assert sql is not None
    statements = split_sql_statements(sql)
    assert len(statements) >= 10
    assert any(
        stmt.startswith("CREATE TABLE IF NOT EXISTS agentloop_checkpoints") for stmt in statements
    )
    assert any(stmt.startswith("CREATE TABLE IF NOT EXISTS ce_dag") for stmt in statements)
    assert any(stmt.startswith("CREATE TABLE IF NOT EXISTS ce_ledger") for stmt in statements)
    assert any(
        stmt.startswith("CREATE TABLE IF NOT EXISTS soothe_schema_migrations")
        for stmt in statements
    )


def test_metadata_init_script_contains_persistence_table() -> None:
    sql = load_init_script("soothe_metadata")
    assert sql is not None
    assert "soothe_persistence" in sql
    assert "soothe_schema_migrations" in sql


def test_vectors_init_script_installs_extension() -> None:
    sql = load_init_script("soothe_vectors")
    assert sql is not None
    assert "CREATE EXTENSION IF NOT EXISTS vector" in sql


def test_load_init_script_missing_returns_none(tmp_path: Path) -> None:
    assert load_init_script("soothe_missing", sql_root=tmp_path) is None


def test_load_init_script_rejects_empty_file(tmp_path: Path) -> None:
    db_dir = tmp_path / "soothe_empty"
    db_dir.mkdir()
    (db_dir / "init.sql").write_text("   \n", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        load_init_script("soothe_empty", sql_root=tmp_path)


def test_discover_versioned_scripts_excludes_init_sql(tmp_path: Path) -> None:
    db_dir = tmp_path / "soothe_demo"
    db_dir.mkdir()
    (db_dir / "init.sql").write_text("SELECT 1", encoding="utf-8")
    (db_dir / "001_first.sql").write_text("SELECT 2", encoding="utf-8")
    (db_dir / "010_second.sql").write_text("SELECT 3", encoding="utf-8")

    scripts = discover_versioned_scripts("soothe_demo", sql_root=tmp_path)
    assert [s.version for s in scripts] == ["001", "010"]


def test_discover_rejects_invalid_filename(tmp_path: Path) -> None:
    db_dir = tmp_path / "soothe_demo"
    db_dir.mkdir()
    (db_dir / "bad.sql").write_text("SELECT 1", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid migration filename"):
        discover_versioned_scripts("soothe_demo", sql_root=tmp_path)


@pytest.mark.asyncio
async def test_run_database_init_executes_statements(tmp_path: Path) -> None:
    pytest.importorskip("psycopg_pool")

    db_dir = tmp_path / "soothe_demo"
    db_dir.mkdir()
    (db_dir / "init.sql").write_text(
        """
        CREATE TABLE demo (id INT);
        CREATE INDEX idx_demo ON demo(id);
        """,
        encoding="utf-8",
    )

    cur = AsyncMock()
    conn = MagicMock()
    conn.cursor.return_value.__aenter__ = AsyncMock(return_value=cur)
    conn.cursor.return_value.__aexit__ = AsyncMock(return_value=None)

    pool = MagicMock()

    applied = await run_database_init(pool, "soothe_demo", sql_root=tmp_path, conn=conn)

    assert applied is True
    execute_sql = [call.args[0] for call in cur.execute.call_args_list]
    assert any("CREATE TABLE demo" in stmt for stmt in execute_sql)
    assert any("CREATE INDEX idx_demo" in stmt for stmt in execute_sql)


@pytest.mark.asyncio
async def test_run_database_migrations_applies_pending_scripts(tmp_path: Path) -> None:
    pytest.importorskip("psycopg_pool")

    db_dir = tmp_path / "soothe_demo"
    db_dir.mkdir()
    (db_dir / "init.sql").write_text(
        "CREATE TABLE soothe_schema_migrations (version TEXT PRIMARY KEY, name TEXT);",
        encoding="utf-8",
    )
    (db_dir / "000_init.sql").write_text("CREATE TABLE demo (id INT);", encoding="utf-8")

    cur = AsyncMock()
    conn = MagicMock()
    conn.set_autocommit = AsyncMock()
    conn.transaction.return_value.__aenter__ = AsyncMock()
    conn.transaction.return_value.__aexit__ = AsyncMock(return_value=None)
    conn.cursor.return_value.__aenter__ = AsyncMock(return_value=cur)
    conn.cursor.return_value.__aexit__ = AsyncMock(return_value=None)

    cur.fetchall = AsyncMock(side_effect=[[], []])

    pool = MagicMock()

    applied = await run_database_migrations(pool, "soothe_demo", sql_root=tmp_path, conn=conn)

    assert applied == ["000"]
    execute_sql = [call.args[0] for call in cur.execute.call_args_list]
    assert any("CREATE TABLE demo" in stmt for stmt in execute_sql)
    insert_stmts = [s for s in execute_sql if "INSERT INTO soothe_schema_migrations" in s]
    assert len(insert_stmts) == 1


@pytest.mark.asyncio
async def test_initialize_database_runs_init_then_migrations(tmp_path: Path) -> None:
    pytest.importorskip("psycopg_pool")

    db_dir = tmp_path / "soothe_demo"
    db_dir.mkdir()
    (db_dir / "init.sql").write_text("CREATE TABLE base (id INT);", encoding="utf-8")
    (db_dir / "001_delta.sql").write_text("CREATE TABLE delta (id INT);", encoding="utf-8")

    cur = AsyncMock()
    conn = MagicMock()
    conn.set_autocommit = AsyncMock()
    conn.transaction.return_value.__aenter__ = AsyncMock()
    conn.transaction.return_value.__aexit__ = AsyncMock(return_value=None)
    conn.cursor.return_value.__aenter__ = AsyncMock(return_value=cur)
    conn.cursor.return_value.__aexit__ = AsyncMock(return_value=None)

    cur.fetchall = AsyncMock(return_value=[])

    pool = MagicMock()
    pool.connection.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.connection.return_value.__aexit__ = AsyncMock(return_value=None)

    result = await initialize_database(pool, "soothe_demo", sql_root=tmp_path)

    assert result.init_applied is True
    assert result.migrations_applied == ["001"]


def test_checkpoints_init_lives_in_host_sql_root() -> None:
    """IG-678 PR-3: the StrangeLoop/CE checkpoints schema is host-owned.

    Nano no longer ships ``soothe_checkpoints/init.sql``; the host pins
    ``sql_root`` to its own ``foundation/persistence/sql`` dir in
    ``postgres_schema.py``.
    """
    from soothe.foundation.persistence.postgres_schema import _HOST_SQL_ROOT

    assert (_HOST_SQL_ROOT / "soothe_checkpoints" / "init.sql").is_file()
    # Nano's shared database_sql_root() must NOT carry the checkpoints init.
    assert not (database_sql_root() / "soothe_checkpoints" / "init.sql").is_file()
