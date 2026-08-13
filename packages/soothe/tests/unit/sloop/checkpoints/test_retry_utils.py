"""Retry helpers for PostgreSQL connection, schema races, and SQLite transient errors."""

from __future__ import annotations

import sqlite3

import pytest

from soothe.sloop.checkpoints.retry_utils import (
    is_duplicate_schema_error,
    is_recoverable_connection_error,
    is_recoverable_sqlite_error,
)


def test_is_duplicate_schema_error_detects_unique_violation_message() -> None:
    exc = Exception(
        'duplicate key value violates unique constraint "pg_type_typname_nsp_index"\n'
        "DETAIL:  Key (typname, typnamespace)=(checkpoint_migrations, 2200) already exists."
    )
    assert is_duplicate_schema_error(exc) is True


def test_is_duplicate_schema_error_false_for_unrelated_errors() -> None:
    assert is_duplicate_schema_error(ValueError("bad value")) is False


def test_is_duplicate_schema_error_detects_psycopg_unique_violation() -> None:
    psycopg = pytest.importorskip("psycopg")
    from psycopg import errors as pg_errors

    assert is_duplicate_schema_error(pg_errors.UniqueViolation("dup")) is True
    assert is_recoverable_connection_error(psycopg.OperationalError("down")) is True


def test_is_recoverable_connection_error_detects_pool_timeout() -> None:
    pytest.importorskip("psycopg_pool")
    from psycopg_pool import PoolTimeout

    assert is_recoverable_connection_error(PoolTimeout("couldn't get a connection")) is True


def test_is_recoverable_sqlite_error_detects_open_failure() -> None:
    """The exact error from the production traceback should be recoverable."""
    exc = sqlite3.OperationalError("unable to open database file")
    assert is_recoverable_sqlite_error(exc) is True


def test_is_recoverable_sqlite_error_detects_lock_contention() -> None:
    assert is_recoverable_sqlite_error(sqlite3.OperationalError("database is locked")) is True
    assert is_recoverable_sqlite_error(sqlite3.OperationalError("database table is locked")) is True


def test_is_recoverable_sqlite_error_detects_disk_io_error() -> None:
    assert is_recoverable_sqlite_error(sqlite3.OperationalError("disk I/O error")) is True


def test_is_recoverable_sqlite_error_false_for_unrelated_errors() -> None:
    assert is_recoverable_sqlite_error(ValueError("bad value")) is False
    assert is_recoverable_sqlite_error(sqlite3.OperationalError("no such table: foo")) is False


def test_is_recoverable_sqlite_error_false_for_non_sqlite_exceptions() -> None:
    assert is_recoverable_sqlite_error(RuntimeError("database is locked")) is False
    assert is_recoverable_sqlite_error(KeyError("disk I/O error")) is False
