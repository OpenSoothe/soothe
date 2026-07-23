"""Unit tests for StrangeLoop PostgreSQL schema initialization."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("psycopg_pool")

from soothe.persistence.db_init import DatabaseSchemaResult
from soothe.sloop.checkpoints.postgres_schema import (
    AGENTLOOP_POSTGRES_DATABASE,
    initialize_agentloop_postgres_schema,
)


@pytest.mark.asyncio
async def test_initialize_schema_runs_checkpoints_init_and_migrations() -> None:
    """Pool open delegates to soothe_checkpoints init + versioned migrations.

    IG-635 PR-3: the host pins ``sql_root`` to its own sql dir so the
    StrangeLoop/CE schema no longer lives in ``soothe_nano``.
    """
    from soothe.sloop.checkpoints.postgres_schema import _HOST_SQL_ROOT

    pool = object()
    with patch(
        "soothe.sloop.checkpoints.postgres_schema.initialize_database",
        new_callable=AsyncMock,
        return_value=DatabaseSchemaResult(init_applied=True, migrations_applied=["001"]),
    ) as run_init:
        await initialize_agentloop_postgres_schema(pool)  # type: ignore[arg-type]

    run_init.assert_awaited_once_with(pool, AGENTLOOP_POSTGRES_DATABASE, sql_root=_HOST_SQL_ROOT)
