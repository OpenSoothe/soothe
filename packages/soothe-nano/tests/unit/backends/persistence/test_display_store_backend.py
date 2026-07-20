"""Tests for display card store backend selection."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from soothe_sdk.display.card_ledger import CardMutation

from soothe_nano.backends.persistence.display_store import (
    DisplayCardStore,
    configure_display_card_store,
    get_display_card_store,
    reset_display_card_store_for_tests,
)
from soothe_nano.backends.persistence.display_store_postgres import PostgresDisplayCardStore
from soothe_nano.config.models import PersistenceConfig
from soothe_nano.config.settings import SootheConfig


def test_configure_display_card_store_sqlite(tmp_path: Path, monkeypatch) -> None:
    reset_display_card_store_for_tests()
    import soothe_sdk.paths as sdk_paths

    monkeypatch.setattr(sdk_paths, "SOOTHE_DATA_DIR", str(tmp_path))
    cfg = SootheConfig(persistence=PersistenceConfig(default_backend="sqlite"))
    store = configure_display_card_store(cfg)
    assert isinstance(store, DisplayCardStore)
    assert store.db_path == tmp_path / "display.db"
    reset_display_card_store_for_tests()


def test_configure_display_card_store_postgresql() -> None:
    reset_display_card_store_for_tests()
    cfg = SootheConfig(
        persistence=PersistenceConfig(
            default_backend="postgresql",
            postgres_base_dsn="postgresql://postgres:postgres@localhost:5432",
        )
    )
    store = configure_display_card_store(cfg)
    assert isinstance(store, PostgresDisplayCardStore)
    assert store.dsn.endswith("/soothe_metadata")
    reset_display_card_store_for_tests()


def test_get_display_card_store_db_path_forces_sqlite(tmp_path: Path) -> None:
    reset_display_card_store_for_tests()
    path = tmp_path / "isolated.db"
    store = get_display_card_store(db_path=path)
    assert isinstance(store, DisplayCardStore)
    assert store.db_path == path
    mutation = CardMutation(
        seq=0,
        ts="2026-01-01T00:00:00Z",
        op="create",
        card_id="header",
        kind="system",
        data={"role": "header"},
    )
    store.append_mutations("loop-1", [mutation])
    assert len(store.list_mutations("loop-1")) == 1
    reset_display_card_store_for_tests()


def test_postgres_store_uses_conflict_ignore_sql() -> None:
    """Smoke: Postgres store builds without opening a real connection."""
    store = PostgresDisplayCardStore(dsn="postgresql://postgres:postgres@localhost/soothe_metadata")
    assert store.db_path is None
    assert store.dsn.endswith("soothe_metadata")


def test_configure_replaces_previous_store(tmp_path: Path, monkeypatch) -> None:
    reset_display_card_store_for_tests()
    import soothe_sdk.paths as sdk_paths

    monkeypatch.setattr(sdk_paths, "SOOTHE_DATA_DIR", str(tmp_path))
    sqlite_cfg = SootheConfig(persistence=PersistenceConfig(default_backend="sqlite"))
    first = configure_display_card_store(sqlite_cfg)
    first.close = MagicMock(wraps=first.close)  # type: ignore[method-assign]
    pg_cfg = SootheConfig(
        persistence=PersistenceConfig(
            default_backend="postgresql",
            postgres_base_dsn="postgresql://postgres:postgres@localhost:5432",
        )
    )
    second = configure_display_card_store(pg_cfg)
    assert first.close.called  # type: ignore[attr-defined]
    assert isinstance(second, PostgresDisplayCardStore)
    reset_display_card_store_for_tests()
