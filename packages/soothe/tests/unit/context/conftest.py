"""Shared test fixtures for Context Engine tests."""

from __future__ import annotations

from pathlib import Path

from soothe.context.store_sqlite import SqliteContextPersistence


def make_test_persistence(loop_id: str = "test-loop") -> SqliteContextPersistence:
    """Create an in-memory SQLite persistence backend for tests."""
    return SqliteContextPersistence(loop_id=loop_id, db_path=Path(":memory:"))
