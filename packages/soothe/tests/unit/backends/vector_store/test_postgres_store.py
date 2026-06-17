"""Unit tests for PostgreSQLPersistStore retry and pool recovery."""

import asyncio
import importlib.util
from pathlib import Path


def _load_postgres_store_class():
    """Load PostgreSQLPersistStore directly from source file.

    Importing through ``soothe.backends.persistence`` can pull optional modules
    that are currently under active refactor in this workspace.
    """
    package_root = Path(__file__).resolve().parents[4]
    module_path = package_root / "src" / "soothe" / "backends" / "persistence" / "postgres_store.py"
    spec = importlib.util.spec_from_file_location("test_postgres_store_module", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load module spec for {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PostgreSQLPersistStore


class _AdminShutdownError(Exception):
    """Test-only error class representing recoverable connection shutdown."""


class TestPostgreSQLPersistStoreUnit:
    """Unit tests for internal retry behavior without live PostgreSQL."""

    def test_run_with_pool_recovery_retries_once_on_recoverable_error(self) -> None:
        """Recoverable connection failures should reset pool and retry once."""
        postgres_persist_store_cls = _load_postgres_store_class()

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
        postgres_persist_store_cls = _load_postgres_store_class()

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
