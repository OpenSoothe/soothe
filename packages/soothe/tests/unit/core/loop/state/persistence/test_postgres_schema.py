"""Unit tests for AgentLoop PostgreSQL schema initialization."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("psycopg_pool")

from soothe.core.loop.state.persistence.postgres_schema import (
    _AGENTLOOP_TABLES_DROP_ORDER,
    initialize_agentloop_postgres_schema,
)


@pytest.mark.asyncio
async def test_initialize_schema_drops_then_creates_with_client_workspace() -> None:
    """Clean-cut init drops legacy tables and creates the full checkpoint schema."""
    cur = AsyncMock()
    conn = MagicMock()
    conn.cursor.return_value.__aenter__ = AsyncMock(return_value=cur)
    conn.cursor.return_value.__aexit__ = AsyncMock(return_value=None)
    pool = MagicMock()
    pool.connection.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.connection.return_value.__aexit__ = AsyncMock(return_value=None)

    await initialize_agentloop_postgres_schema(pool)

    statements = [call.args[0] for call in cur.execute.call_args_list]
    drop_stmts = statements[: len(_AGENTLOOP_TABLES_DROP_ORDER)]
    assert all("DROP TABLE IF EXISTS" in stmt for stmt in drop_stmts)
    assert drop_stmts[0].endswith("goal_records CASCADE")
    assert drop_stmts[-1].endswith("agentloop_checkpoints CASCADE")

    create_checkpoint = next(
        stmt for stmt in statements if stmt.strip().startswith("CREATE TABLE agentloop_checkpoints")
    )
    assert "client_workspace TEXT" in create_checkpoint
    assert "detached_at TIMESTAMPTZ" in create_checkpoint
    assert "user_id TEXT" in create_checkpoint
