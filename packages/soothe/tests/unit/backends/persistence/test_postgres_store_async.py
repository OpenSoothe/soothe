"""Unit tests for PostgreSQLPersistStore async operations (IG-258 Phase 2)."""

import asyncio
import os

import pytest


class TestPostgreSQLPersistStoreAsync:
    """Unit tests for PostgreSQLPersistStore async interface."""

    @pytest.fixture
    async def postgres_store(self):
        """Create PostgreSQL store instance for testing."""
        # Skip if psycopg_pool not installed
        pytest.importorskip("psycopg_pool")

        from soothe.backends.persistence.postgres_store import PostgreSQLPersistStore

        # Use test database DSN from environment or default
        dsn = os.getenv(
            "SOOTHE_TEST_POSTGRES_DSN",
            "postgresql://postgres:postgres@localhost:5432/soothe_test",
        )

        # Create store with timeout parameter in DSN
        # Add connect_timeout=2 to fail fast if database unavailable
        timeout_dsn = dsn if "connect_timeout" in dsn else f"{dsn}?connect_timeout=2"

        store = PostgreSQLPersistStore(dsn=timeout_dsn, namespace="test_async")

        # Try to initialize connection pool to verify database is available
        try:
            # Trigger pool initialization with a simple operation
            await asyncio.wait_for(store.save("_connection_test", "test"), timeout=5.0)
            await asyncio.wait_for(store.delete("_connection_test"), timeout=5.0)
            yield store
        except (TimeoutError, Exception) as e:
            # Skip test if database connection fails or times out
            await store.close()
            pytest.skip(f"PostgreSQL database not available: {e}")
        finally:
            try:
                await store.close()
            except Exception:
                pass  # Already closed in timeout case

    def test_class_can_be_imported(self) -> None:
        """Test that PostgreSQLPersistStore class can be imported."""
        from soothe.backends.persistence.postgres_store import PostgreSQLPersistStore

        assert PostgreSQLPersistStore is not None

    @pytest.mark.asyncio
    async def test_save_and_load(self, postgres_store) -> None:
        """Test basic async save and load operations."""
        await postgres_store.save("key1", {"data": "value1"})
        result = await postgres_store.load("key1")
        assert result == {"data": "value1"}

    @pytest.mark.asyncio
    async def test_load_nonexistent(self, postgres_store) -> None:
        """Test async load returns None for missing key."""
        result = await postgres_store.load("nonexistent_key")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete(self, postgres_store) -> None:
        """Test async delete removes key."""
        await postgres_store.save("key1", "value")
        await postgres_store.delete("key1")
        result = await postgres_store.load("key1")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_keys(self, postgres_store) -> None:
        """Test async list_keys functionality."""
        await postgres_store.save("a", 1)
        await postgres_store.save("b", 2)
        await postgres_store.save("c", 3)

        keys = await postgres_store.list_keys()
        assert isinstance(keys, list)
        assert set(keys) == {"a", "b", "c"}

    @pytest.mark.asyncio
    async def test_upsert_semantics(self, postgres_store) -> None:
        """Test async save overwrites existing key."""
        await postgres_store.save("key1", "first")
        await postgres_store.save("key1", "second")
        result = await postgres_store.load("key1")
        assert result == "second"

    @pytest.mark.asyncio
    async def test_complex_data_serialization(self, postgres_store) -> None:
        """Test async save/load of complex data structures."""
        complex_data = {
            "list": [1, 2, 3],
            "nested": {"key": "value"},
            "number": 42,
            "bool": True,
            "null": None,
        }
        await postgres_store.save("complex", complex_data)
        result = await postgres_store.load("complex")
        assert result == complex_data

    @pytest.mark.asyncio
    async def test_concurrent_saves(self, postgres_store) -> None:
        """Test concurrent async save operations (IG-258 Phase 2 validation)."""

        async def save_key(key_id: int) -> None:
            await postgres_store.save(f"concurrent_key_{key_id}", {"value": key_id})

        # 20 concurrent save operations
        tasks = [save_key(i) for i in range(20)]
        await asyncio.gather(*tasks)

        # Verify all keys saved successfully
        for i in range(20):
            result = await postgres_store.load(f"concurrent_key_{i}")
            assert result == {"value": i}

    @pytest.mark.asyncio
    async def test_concurrent_loads(self, postgres_store) -> None:
        """Test concurrent async load operations."""

        # Setup: save keys first
        for i in range(20):
            await postgres_store.save(f"load_test_{i}", {"data": i})

        async def load_key(key_id: int) -> dict:
            return await postgres_store.load(f"load_test_{key_id}")

        # 20 concurrent load operations
        tasks = [load_key(i) for i in range(20)]
        results = await asyncio.gather(*tasks)

        # Verify all loads successful
        for i, result in enumerate(results):
            assert result == {"data": i}

    @pytest.mark.asyncio
    async def test_concurrent_mixed_operations(self, postgres_store) -> None:
        """Test concurrent async save/load/delete operations."""

        async def mixed_op(op_id: int) -> None:
            if op_id % 3 == 0:
                # Save operation
                await postgres_store.save(f"mixed_{op_id}", {"op": "save"})
            elif op_id % 3 == 1:
                # Load operation (key may not exist yet)
                await postgres_store.load(f"mixed_{op_id}")
            else:
                # Delete operation
                await postgres_store.save(f"mixed_{op_id}", {"op": "delete"})
                await postgres_store.delete(f"mixed_{op_id}")

        # 30 concurrent mixed operations
        tasks = [mixed_op(i) for i in range(30)]
        await asyncio.gather(*tasks)

    @pytest.mark.asyncio
    async def test_namespace_isolation(self) -> None:
        """Test that namespaces isolate keys."""
        pytest.importorskip("psycopg_pool")

        from soothe.backends.persistence.postgres_store import PostgreSQLPersistStore

        dsn = os.getenv(
            "SOOTHE_TEST_POSTGRES_DSN",
            "postgresql://postgres:postgres@localhost:5432/soothe_test",
        )

        # Add timeout to DSN for faster failure detection
        timeout_dsn = dsn if "connect_timeout" in dsn else f"{dsn}?connect_timeout=2"

        store_a = PostgreSQLPersistStore(dsn=timeout_dsn, namespace="ns_a")
        store_b = PostgreSQLPersistStore(dsn=timeout_dsn, namespace="ns_b")

        try:
            # Test connection with timeout
            try:
                await asyncio.wait_for(store_a.save("_test_conn", "test"), timeout=5.0)
                await store_a.delete("_test_conn")
            except (TimeoutError, Exception) as e:
                pytest.skip(f"PostgreSQL database not available: {e}")

            await store_a.save("shared_key", "value_a")
            await store_b.save("shared_key", "value_b")

            result_a = await store_a.load("shared_key")
            result_b = await store_b.load("shared_key")

            assert result_a == "value_a"
            assert result_b == "value_b"

            await store_a.delete("shared_key")
            result_a = await store_a.load("shared_key")
            result_b = await store_b.load("shared_key")

            assert result_a is None
            assert result_b == "value_b"
        finally:
            await store_a.close()
            await store_b.close()

    @pytest.mark.asyncio
    async def test_close_is_idempotent(self, postgres_store) -> None:
        """Test async close can be called multiple times safely."""
        await postgres_store.close()
        await postgres_store.close()  # Should not raise

    @pytest.mark.asyncio
    async def test_connection_pool_initialization(self) -> None:
        """Test connection pool is initialized with correct size."""
        pytest.importorskip("psycopg_pool")

        from soothe.backends.persistence.postgres_store import PostgreSQLPersistStore

        dsn = os.getenv(
            "SOOTHE_TEST_POSTGRES_DSN",
            "postgresql://postgres:postgres@localhost:5432/soothe_test",
        )

        # Add timeout to DSN for faster failure detection
        timeout_dsn = dsn if "connect_timeout" in dsn else f"{dsn}?connect_timeout=2"

        # Custom pool size
        store = PostgreSQLPersistStore(dsn=timeout_dsn, namespace="test_pool", pool_size=5)

        try:
            # Pool should not be initialized yet (lazy)
            assert store._pool is None

            # Test connection with timeout
            try:
                await asyncio.wait_for(store.save("init_test", "data"), timeout=5.0)
            except (TimeoutError, Exception) as e:
                pytest.skip(f"PostgreSQL database not available: {e}")

            # Pool should now be initialized
            assert store._pool is not None
            assert store._pool_size == 5

        finally:
            await store.close()
