"""Tests for the workspace state store factory (unified persistence branch)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from soothe.config.models import PersistenceConfig
from soothe.config.settings import SootheConfig
from soothe.workspace.state.factory import create_workspace_state_store
from soothe.workspace.state.postgres import PostgresWorkspaceStateStore
from soothe.workspace.state.sqlite import SqliteWorkspaceStateStore


def test_create_workspace_state_store_sqlite(tmp_path: Path) -> None:
    cfg = SootheConfig(persistence=PersistenceConfig(default_backend="sqlite"))
    store = create_workspace_state_store(cfg, loop_id="loop-001", workspace_dir=tmp_path)
    assert isinstance(store, SqliteWorkspaceStateStore)


def test_create_workspace_state_store_postgresql() -> None:
    cfg = SootheConfig(
        persistence=PersistenceConfig(
            default_backend="postgresql",
            postgres_base_dsn="postgresql://postgres:postgres@localhost:5432",
        )
    )
    store = create_workspace_state_store(cfg, loop_id="loop-001")
    assert isinstance(store, PostgresWorkspaceStateStore)
    assert store.dsn.endswith("/soothe_metadata")
    assert store.loop_id == "loop-001"


def test_create_workspace_state_store_sqlite_requires_workspace_dir() -> None:
    cfg = SootheConfig(persistence=PersistenceConfig(default_backend="sqlite"))
    with pytest.raises(ValueError, match="workspace_dir is required"):
        create_workspace_state_store(cfg, loop_id="loop-001")


def test_create_workspace_state_store_unknown_backend() -> None:
    cfg = MagicMock()
    cfg.persistence.default_backend = "redis"
    with pytest.raises(ValueError, match="Unknown persistence backend"):
        create_workspace_state_store(cfg, loop_id="loop-001")
