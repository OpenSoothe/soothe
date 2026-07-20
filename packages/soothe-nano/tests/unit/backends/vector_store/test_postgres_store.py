"""Unit tests for PostgreSQLPersistStore retry and pool recovery."""

import asyncio

import pytest

from soothe_nano.backends.persistence.postgres_store import PostgreSQLPersistStore


class _AdminShutdownError(Exception):
    """Test-only error class representing recoverable connection shutdown."""


class TestPostgreSQLPersistStoreUnit:
    """Unit tests for internal retry behavior without live PostgreSQL."""

    def test_run_with_pool_recovery_retries_once_on_recoverable_error(self) -> None:
        """Recoverable connection failures should reset pool and retry once."""
        postgres_persist_store_cls = PostgreSQLPersistStore

        async def _async_test() -> None:
            store = postgres_persist_store_cls(dsn="postgresql://unused/test")
            ensure_pool_calls = 0
            reset_pool_calls = 0
            op_calls = 0

            async def _fake_ensure_pool():
                nonlocal ensure_pool_calls
                ensure_pool_calls += 1
                return object()

            async def _fake_reset_pool() -> None:
                nonlocal reset_pool_calls
                reset_pool_calls += 1

            async def _flaky_op(_pool):
                nonlocal op_calls
                op_calls += 1
                if op_calls == 1:
                    raise _AdminShutdownError("terminating connection due to administrator command")
                return "ok"

            store._ensure_pool = _fake_ensure_pool  # type: ignore[method-assign]
            store._reset_pool = _fake_reset_pool  # type: ignore[method-assign]
            store._is_recoverable_connection_error = (  # type: ignore[method-assign]
                lambda exc: isinstance(exc, _AdminShutdownError)
            )

            result = await store._run_with_pool_recovery("save", _flaky_op)
            assert result == "ok"
            assert op_calls == 2
            assert ensure_pool_calls == 2
            assert reset_pool_calls == 1

        asyncio.run(_async_test())

    def test_run_with_pool_recovery_does_not_retry_nonrecoverable_error(self) -> None:
        """Nonrecoverable errors should bubble immediately without pool reset."""
        postgres_persist_store_cls = PostgreSQLPersistStore

        async def _async_test() -> None:
            store = postgres_persist_store_cls(dsn="postgresql://unused/test")
            reset_pool_calls = 0
            op_calls = 0

            async def _fake_ensure_pool():
                return object()

            async def _fake_reset_pool() -> None:
                nonlocal reset_pool_calls
                reset_pool_calls += 1

            async def _failing_op(_pool):
                nonlocal op_calls
                op_calls += 1
                raise ValueError("boom")

            store._ensure_pool = _fake_ensure_pool  # type: ignore[method-assign]
            store._reset_pool = _fake_reset_pool  # type: ignore[method-assign]
            store._is_recoverable_connection_error = lambda _exc: False  # type: ignore[method-assign]

            try:
                await store._run_with_pool_recovery("save", _failing_op)
            except ValueError as exc:
                assert str(exc) == "boom"
            else:
                raise AssertionError("Expected ValueError for nonrecoverable failure")

            assert op_calls == 1
            assert reset_pool_calls == 0

        asyncio.run(_async_test())

    def test_load_and_list_keys_use_dict_row_column_names(self) -> None:
        """Rows from dict_row pools must be accessed by column name, not index."""
        postgres_persist_store_cls = PostgreSQLPersistStore

        async def _async_return(value: object) -> object:
            return value

        async def _async_test() -> None:
            store = postgres_persist_store_cls(dsn="postgresql://unused/test")

            class _FakeCursor:
                def __init__(self, rows: list[dict[str, object]]) -> None:
                    self._rows = rows

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *_args: object) -> None:
                    return None

                async def execute(self, *_args: object, **_kwargs: object) -> None:
                    return None

                async def fetchone(self) -> dict[str, object] | None:
                    return self._rows[0] if self._rows else None

                async def fetchall(self) -> list[dict[str, object]]:
                    return list(self._rows)

            class _FakeConnection:
                def __init__(self, cursor: _FakeCursor) -> None:
                    self._cursor = cursor

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *_args: object) -> None:
                    return None

                def cursor(self) -> _FakeCursor:
                    return self._cursor

                async def commit(self) -> None:
                    return None

            class _FakePool:
                def __init__(self, cursor: _FakeCursor) -> None:
                    self._cursor = cursor

                def connection(self) -> _FakeConnection:
                    return _FakeConnection(self._cursor)

            load_cursor = _FakeCursor([{"data": {"thread": "info"}}])
            store._ensure_pool = lambda: _async_return(_FakePool(load_cursor))  # type: ignore[method-assign,return-value]
            loaded = await store.load("thread:abc")
            assert loaded == {"thread": "info"}

            list_cursor = _FakeCursor([{"key": "a"}, {"key": "b"}])
            store._ensure_pool = lambda: _async_return(_FakePool(list_cursor))  # type: ignore[method-assign,return-value]
            keys = await store.list_keys()
            assert keys == ["a", "b"]

        asyncio.run(_async_test())

    def test_reset_pool_does_not_close_shared_pool(self) -> None:
        """Shared-pool wrappers must rebind, not close the registry-owned pool."""
        postgres_persist_store_cls = PostgreSQLPersistStore

        async def _async_test() -> None:
            class _PoolWithClose:
                def __init__(self) -> None:
                    self.close_calls = 0

                async def close(self) -> None:
                    self.close_calls += 1

            shared = _PoolWithClose()
            store = postgres_persist_store_cls(
                dsn="postgresql://unused/test",
                pool_size=0,
                shared_pool=shared,
            )
            store._pool = None
            await store._reset_pool()
            assert store._pool is shared
            assert shared.close_calls == 0

        asyncio.run(_async_test())

    def test_ensure_pool_rebinds_shared_pool_when_local_ref_cleared(self) -> None:
        """Late durability touches recover when a prior reset cleared ``_pool``."""
        postgres_persist_store_cls = PostgreSQLPersistStore

        async def _async_test() -> None:
            shared = object()
            store = postgres_persist_store_cls(
                dsn="postgresql://unused/test",
                pool_size=0,
                shared_pool=shared,
            )
            store._pool = None
            store._schema_initialized = True
            pool = await store._ensure_pool()
            assert pool is shared

        asyncio.run(_async_test())

    def test_ensure_pool_opens_lazy_shared_pool(self) -> None:
        """Shared pools created with ``open=False`` must open on first use."""
        postgres_persist_store_cls = PostgreSQLPersistStore

        async def _async_test() -> None:
            open_calls = 0

            class _LazyPool:
                closed = False

                async def open(self) -> None:
                    nonlocal open_calls
                    open_calls += 1

            shared = _LazyPool()
            store = postgres_persist_store_cls(
                dsn="postgresql://unused/test",
                pool_size=0,
                shared_pool=shared,
            )
            store._schema_initialized = True
            pool = await store._ensure_pool()
            assert pool is shared
            assert open_calls == 1

        asyncio.run(_async_test())

    def test_run_with_pool_recovery_retries_pool_closed(self) -> None:
        """``PoolClosed`` from an unopened pool should reopen and retry once."""
        postgres_persist_store_cls = PostgreSQLPersistStore

        async def _async_test() -> None:
            try:
                from psycopg_pool import PoolClosed
            except ImportError:
                pytest.skip("psycopg_pool not installed")

            open_calls = 0

            class _LazyPool:
                closed = False

                async def open(self) -> None:
                    nonlocal open_calls
                    open_calls += 1

                def connection(self):
                    raise AssertionError("connection should not be called on first attempt")

            store = postgres_persist_store_cls(
                dsn="postgresql://unused/test",
                pool_size=0,
                shared_pool=_LazyPool(),
            )
            store._schema_initialized = True
            op_calls = 0

            async def _flaky_op(pool):
                nonlocal op_calls
                op_calls += 1
                if op_calls == 1:
                    raise PoolClosed("the pool 'pool-2' is not open yet")
                return "ok"

            result = await store._run_with_pool_recovery("load", _flaky_op)
            assert result == "ok"
            assert op_calls == 2
            assert open_calls >= 1

        asyncio.run(_async_test())
