"""Unit tests for SQLitePersistStore backend."""

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
        """Test basic save and load operations."""
        store = self._make_store()
        try:
            store.save("key1", {"data": "value1"})
            result = store.load("key1")
            assert result == {"data": "value1"}
        finally:
            store.close()

    def test_load_nonexistent(self) -> None:
        """Test load returns None for missing key."""
        store = self._make_store()
        try:
            assert store.load("nonexistent") is None
        finally:
            store.close()

    def test_delete(self) -> None:
        """Test delete removes key."""
        store = self._make_store()
        try:
            store.save("key1", "value")
            store.delete("key1")
            assert store.load("key1") is None
        finally:
            store.close()

    def test_namespace_isolation(self) -> None:
        """Test that namespaces isolate keys."""
        from soothe.backends.persistence.sqlite_store import SQLitePersistStore

        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        store_a = SQLitePersistStore(db_path=tmp.name, namespace="ns_a")
        store_b = SQLitePersistStore(db_path=tmp.name, namespace="ns_b")
        try:
            store_a.save("shared_key", "value_a")
            store_b.save("shared_key", "value_b")
            assert store_a.load("shared_key") == "value_a"
            assert store_b.load("shared_key") == "value_b"
            store_a.delete("shared_key")
            assert store_a.load("shared_key") is None
            assert store_b.load("shared_key") == "value_b"
        finally:
            store_a.close()
            store_b.close()
            os.unlink(tmp.name)

    def test_upsert_semantics(self) -> None:
        """Test save overwrites existing key."""
        store = self._make_store()
        try:
            store.save("key1", "first")
            store.save("key1", "second")
            assert store.load("key1") == "second"
        finally:
            store.close()

    def test_list_keys(self) -> None:
        """Test listing keys in namespace."""
        store = self._make_store()
        try:
            store.save("a", 1)
            store.save("b", 2)
            keys = store.list_keys()
            assert set(keys) == {"a", "b"}
        finally:
            store.close()

    def test_complex_data_serialization(self) -> None:
        """Test complex data types serialize correctly."""
        store = self._make_store()
        try:
            data = {
                "list": [1, 2, 3],
                "nested": {"key": "value"},
                "number": 42,
                "bool": True,
                "null": None,
            }
            store.save("complex", data)
            result = store.load("complex")
            assert result == data
        finally:
            store.close()

    def test_close_is_idempotent(self) -> None:
        """Test close can be called multiple times safely."""
        store = self._make_store()
        store.close()
        store.close()  # Should not raise
