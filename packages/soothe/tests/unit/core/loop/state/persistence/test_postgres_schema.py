"""Unit tests for StrangeLoop PostgreSQL schema initialization."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("psycopg_pool")

from soothe.foundation.persistence.db_init import DatabaseSchemaResult
from soothe.foundation.sloop.state.persistence.postgres_schema import (
    AGENTLOOP_POSTGRES_DATABASE,
    initialize_agentloop_postgres_schema,
)


@pytest.mark.asyncio
async def test_initialize_schema_runs_checkpoints_init_and_migrations() -> None:
    """Pool open delegates to soothe_checkpoints init + versioned migrations."""
    pool = object()
    with patch(
        "soothe.foundation.sloop.state.persistence.postgres_schema.initialize_database",
        new_callable=AsyncMock,
        return_value=DatabaseSchemaResult(init_applied=True, migrations_applied=["001"]),
    ) as run_init:
        await initialize_agentloop_postgres_schema(pool)  # type: ignore[arg-type]

    run_init.assert_awaited_once_with(pool, AGENTLOOP_POSTGRES_DATABASE)
