"""Unit tests for StrangeLoop PostgreSQL schema initialization."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("psycopg_pool")

from soothe.foundation.loop.state.persistence.postgres_schema import (
    SLOOP_POSTGRES_DATABASE,
    initialize_sloop_postgres_schema,
)


@pytest.mark.asyncio
async def test_initialize_schema_runs_checkpoints_migrations() -> None:
    """Pool open delegates to versioned SQL migrations for soothe_checkpoints."""
    pool = object()
    with patch(
        "soothe.foundation.loop.state.persistence.postgres_schema.run_database_migrations",
        new_callable=AsyncMock,
        return_value=["001"],
    ) as run_migrations:
        await initialize_sloop_postgres_schema(pool)  # type: ignore[arg-type]

    run_migrations.assert_awaited_once_with(pool, SLOOP_POSTGRES_DATABASE)
