"""Tests for ref-counted shared SQLite StrangeLoop persistence backend."""

from __future__ import annotations

import pytest

import soothe.foundation.sloop.state.persistence.shared_pool as shared_pool
from soothe.foundation.sloop.state.persistence.manager import (
    StrangeLoopCheckpointPersistenceManager,
)
from soothe.foundation.sloop.state.persistence.sqlite_backend import SQLitePersistenceBackend


@pytest.fixture(autouse=True)
def _reset_shared_sqlite_backend() -> None:
    shared_pool._shared_sqlite_backend = None
    shared_pool._shared_sqlite_refcount = 0
    yield
    shared_pool._shared_sqlite_backend = None
    shared_pool._shared_sqlite_refcount = 0


@pytest.mark.asyncio
async def test_shared_sqlite_backend_reused_across_managers(tmp_path, monkeypatch) -> None:
    import soothe_sdk.client.config as sdk_config

    import soothe.config as config

    monkeypatch.setattr(config, "SOOTHE_HOME", str(tmp_path))
    monkeypatch.setattr(sdk_config, "SOOTHE_DATA_DIR", str(tmp_path / "data"))

    manager_a = StrangeLoopCheckpointPersistenceManager(None)
    manager_b = StrangeLoopCheckpointPersistenceManager(None)

    assert manager_a._backend is manager_b._backend
    assert isinstance(manager_a._backend, SQLitePersistenceBackend)
    assert shared_pool._shared_sqlite_refcount == 2

    await manager_a.close()
    assert shared_pool._shared_sqlite_refcount == 1
    assert shared_pool._shared_sqlite_backend is not None

    await manager_b.close()
    assert shared_pool._shared_sqlite_refcount == 0
    assert shared_pool._shared_sqlite_backend is None


@pytest.mark.asyncio
async def test_acquire_sync_creates_data_directory(tmp_path, monkeypatch) -> None:
    import soothe_sdk.client.config as sdk_config

    import soothe.config as config

    monkeypatch.setattr(config, "SOOTHE_HOME", str(tmp_path))
    data_dir = tmp_path / "data"
    monkeypatch.setattr(sdk_config, "SOOTHE_DATA_DIR", str(data_dir))

    backend = shared_pool.acquire_shared_sqlite_backend_sync()
    assert data_dir.exists()
    assert (data_dir / "soothe_checkpoints.db").exists()
    await backend.close()
    shared_pool._shared_sqlite_backend = None
    shared_pool._shared_sqlite_refcount = 0
