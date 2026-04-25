"""Unit tests for SQLitePersistStore backend (IG-258 Phase 2: async methods)."""

import asyncio
import os
import tempfile


class TestSQLitePersistStoreUnit:
    """Unit tests for SQLitePersistStore focusing on interface compliance."""

    def _make_store(self, namespace: str = "default"):
        from soothe.backends.persistence.sqlite_store import SQLitePersistStore

        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        return SQLitePersistStore(db_path=tmp.name, namespace=namespace)

    def test_class_can_be_imported(self) -> None:
        """Test that SQLitePersistStore class can be imported."""
        from soothe.backends.persistence.sqlite_store import SQLitePersistStore

        assert SQLitePersistStore is not None

    def test_factory_returns_instance(self) -> None:
        """Test factory creates SQLite instance."""
        from soothe.backends.persistence import create_persist_store

        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        store = create_persist_store(backend="sqlite", db_path=tmp.name, namespace="test")
        assert store is not None
        assert store.__class__.__name__ == "SQLitePersistStore"
        os.unlink(tmp.name)

    def test_save_and_load(self) -> None:
        """Test basic save and load operations (async, IG-258 Phase 2)."""

        async def _async_test():
            store = self._make_store()
            try:
                await store.save("key1", {"data": "value1"})
                result = await store.load("key1")
                assert result == {"data": "value1"}
            finally:
                await store.close()

        asyncio.run(_async_test())

    def test_load_nonexistent(self) -> None:
        """Test load returns None for missing key (async, IG-258 Phase 2)."""

        async def _async_test():
            store = self._make_store()
            try:
                # Initialize table with a dummy save first (async table creation)
                await store.save("_init", None)
                await store.delete("_init")  # Clean up initialization key
                result = await store.load("nonexistent")
                assert result is None
            finally:
                await store.close()

        asyncio.run(_async_test())

    def test_delete(self) -> None:
        """Test delete removes key (async, IG-258 Phase 2)."""

        async def _async_test():
            store = self._make_store()
            try:
                await store.save("key1", "value")
                await store.delete("key1")
                result = await store.load("key1")
                assert result is None
            finally:
                await store.close()

        asyncio.run(_async_test())

    def test_namespace_isolation(self) -> None:
        """Test that namespaces isolate keys (async, IG-258 Phase 2)."""
        from soothe.backends.persistence.sqlite_store import SQLitePersistStore

        async def _async_test():
            tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
            tmp.close()
            store_a = SQLitePersistStore(db_path=tmp.name, namespace="ns_a")
            store_b = SQLitePersistStore(db_path=tmp.name, namespace="ns_b")
            try:
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
                os.unlink(tmp.name)

        asyncio.run(_async_test())

    def test_upsert_semantics(self) -> None:
        """Test save overwrites existing key (async, IG-258 Phase 2)."""

        async def _async_test():
            store = self._make_store()
            try:
                await store.save("key1", "first")
                await store.save("key1", "second")
                result = await store.load("key1")
                assert result == "second"
            finally:
                await store.close()

        asyncio.run(_async_test())

    def test_list_keys(self) -> None:
        """Test listing keys in namespace (async, IG-258 Phase 2)."""

        async def _async_test():
            store = self._make_store()
            try:
                await store.save("a", 1)
                await store.save("b", 2)
                keys = await store.list_keys()
                assert set(keys) == {"a", "b"}
            finally:
                await store.close()

        asyncio.run(_async_test())

    def test_complex_data_serialization(self) -> None:
        """Test complex data structures serialization (async, IG-258 Phase 2)."""

        async def _async_test():
            store = self._make_store()
            complex_data = {
                "list": [1, 2, 3],
                "nested": {"key": "value"},
                "number": 42,
                "bool": True,
                "null": None,
            }
            try:
                await store.save("complex", complex_data)
                result = await store.load("complex")
                assert result == complex_data
            finally:
                await store.close()

        asyncio.run(_async_test())

    def test_close_is_idempotent(self) -> None:
        """Test close can be called multiple times safely (async, IG-258 Phase 2)."""

        async def _async_test():
            store = self._make_store()
            await store.close()
            await store.close()  # Should not raise

        asyncio.run(_async_test())
