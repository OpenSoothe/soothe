"""Tests for persistence layer (JsonPersistStore and RocksDBPersistStore)."""

from pathlib import Path

import pytest

from soothe.persistence import PersistStore, create_persist_store
from soothe.backends.persistence.json_store import JsonPersistStore


class TestJsonPersistStore:
    """Unit tests for JsonPersistStore."""

    def test_initialization_creates_directory(self, tmp_path: Path):
        """Test that initialization creates the persist directory."""
        persist_dir = tmp_path / "test_persist"
        assert not persist_dir.exists()

        store = JsonPersistStore(str(persist_dir))

        assert persist_dir.exists()
        assert persist_dir.is_dir()

    def test_save_and_load_simple_data(self, tmp_path: Path):
        """Test saving and loading simple data types."""
        store = JsonPersistStore(str(tmp_path))

        # Test with dict
        data = {"key": "value", "number": 42}
        store.save("test_key", data)
        loaded = store.load("test_key")

        assert loaded == data

    def test_save_and_load_complex_data(self, tmp_path: Path):
        """Test saving and loading complex nested data."""
        store = JsonPersistStore(str(tmp_path))

        data = {
            "nested": {"list": [1, 2, 3], "dict": {"a": "b"}},
            "mixed": [None, True, False, "string", 123],
        }
        store.save("complex_key", data)
        loaded = store.load("complex_key")

        assert loaded == data

    def test_load_nonexistent_key_returns_none(self, tmp_path: Path):
        """Test that loading a nonexistent key returns None."""
        store = JsonPersistStore(str(tmp_path))

        result = store.load("nonexistent")

        assert result is None

    def test_delete_existing_key(self, tmp_path: Path):
        """Test deleting an existing key."""
        store = JsonPersistStore(str(tmp_path))

        store.save("to_delete", {"data": "value"})
        assert store.load("to_delete") is not None

        store.delete("to_delete")

        assert store.load("to_delete") is None

    def test_delete_nonexistent_key_no_error(self, tmp_path: Path):
        """Test that deleting a nonexistent key doesn't raise an error."""
        store = JsonPersistStore(str(tmp_path))

        # Should not raise an error
        store.delete("nonexistent")

    def test_key_sanitization(self, tmp_path: Path):
        """Test that keys with special characters are sanitized."""
        store = JsonPersistStore(str(tmp_path))

        # Keys with slashes and colons should be sanitized
        store.save("test/key:name", {"data": "value"})

        loaded = store.load("test/key:name")
        assert loaded == {"data": "value"}

        # Check that file was created with sanitized name
        expected_file = tmp_path / "test_key_name.json"
        assert expected_file.exists()

    def test_overwrite_existing_key(self, tmp_path: Path):
        """Test that saving with an existing key overwrites the data."""
        store = JsonPersistStore(str(tmp_path))

        store.save("key", {"version": 1})
        store.save("key", {"version": 2})

        loaded = store.load("key")
        assert loaded == {"version": 2}

    def test_close_is_noop(self, tmp_path: Path):
        """Test that close() is a no-op for JSON backend."""
        store = JsonPersistStore(str(tmp_path))

        # Should not raise an error
        store.close()

    def test_handles_invalid_json_gracefully(self, tmp_path: Path):
        """Test that loading corrupted JSON returns None."""
        store = JsonPersistStore(str(tmp_path))

        # Write invalid JSON directly to file
        key = "corrupted"
        safe_key = key.replace("/", "_").replace(":", "_")
        path = tmp_path / f"{safe_key}.json"
        path.write_text("not valid json {{{")

        loaded = store.load("corrupted")

        assert loaded is None

    def test_nested_directory_creation(self, tmp_path: Path):
        """Test that nested directories are created for storage."""
        nested_dir = tmp_path / "nested" / "deep" / "path"
        store = JsonPersistStore(str(nested_dir))

        store.save("test", {"data": "value"})

        assert nested_dir.exists()
        assert store.load("test") == {"data": "value"}


class TestRocksDBPersistStore:
    """Unit tests for RocksDBPersistStore."""

    @pytest.fixture
    def rocksdb_available(self):
        """Check if rocksdict is available."""
        try:
            import rocksdict  # noqa: F401

            return True
        except ImportError:
            return False

    def test_import_error_without_rocksdict(self, tmp_path: Path, monkeypatch):
        """Test that ImportError is raised if rocksdict is not installed."""
        # Mock the import to raise ImportError
        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "rocksdict" or name.startswith("rocksdict."):
                raise ImportError("No module named 'rocksdict'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)

        with pytest.raises(ImportError, match="rocksdict is required"):
            from soothe.backends.persistence.rocksdb_store import RocksDBPersistStore

            RocksDBPersistStore(str(tmp_path))

    @pytest.mark.skipif(
        not pytest.importorskip("rocksdict", reason="rocksdict not installed"),
        reason="rocksdict not installed",
    )
    def test_save_and_load_data(self, tmp_path: Path):
        """Test saving and loading data with RocksDB."""
        from soothe.backends.persistence.rocksdb_store import RocksDBPersistStore

        store = RocksDBPersistStore(str(tmp_path))

        data = {"key": "value", "number": 42}
        store.save("test_key", data)
        loaded = store.load("test_key")

        assert loaded == data

        store.close()

    @pytest.mark.skipif(
        not pytest.importorskip("rocksdict", reason="rocksdict not installed"),
        reason="rocksdict not installed",
    )
    def test_load_nonexistent_key_returns_none(self, tmp_path: Path):
        """Test that loading a nonexistent key returns None."""
        from soothe.backends.persistence.rocksdb_store import RocksDBPersistStore

        store = RocksDBPersistStore(str(tmp_path))

        result = store.load("nonexistent")

        assert result is None

        store.close()

    @pytest.mark.skipif(
        not pytest.importorskip("rocksdict", reason="rocksdict not installed"),
        reason="rocksdict not installed",
    )
    def test_delete_key(self, tmp_path: Path):
        """Test deleting a key from RocksDB."""
        from soothe.backends.persistence.rocksdb_store import RocksDBPersistStore

        store = RocksDBPersistStore(str(tmp_path))

        store.save("to_delete", {"data": "value"})
        assert store.load("to_delete") is not None

        store.delete("to_delete")

        assert store.load("to_delete") is None

        store.close()

    @pytest.mark.skipif(
        not pytest.importorskip("rocksdict", reason="rocksdict not installed"),
        reason="rocksdict not installed",
    )
    def test_delete_nonexistent_key_no_error(self, tmp_path: Path):
        """Test that deleting a nonexistent key doesn't raise an error."""
        from soothe.backends.persistence.rocksdb_store import RocksDBPersistStore

        store = RocksDBPersistStore(str(tmp_path))

        # Should not raise an error
        store.delete("nonexistent")

        store.close()

    @pytest.mark.skipif(
        not pytest.importorskip("rocksdict", reason="rocksdict not installed"),
        reason="rocksdict not installed",
    )
    def test_overwrite_existing_key(self, tmp_path: Path):
        """Test that saving with an existing key overwrites the data."""
        from soothe.backends.persistence.rocksdb_store import RocksDBPersistStore

        store = RocksDBPersistStore(str(tmp_path))

        store.save("key", {"version": 1})
        store.save("key", {"version": 2})

        loaded = store.load("key")
        assert loaded == {"version": 2}

        store.close()


class TestCreatePersistStore:
    """Tests for create_persist_store factory function."""

    def test_returns_none_if_no_persist_dir(self):
        """Test that None is returned if persist_dir is None."""
        result = create_persist_store(None, "json")

        assert result is None

    def test_creates_json_store_by_default(self, tmp_path: Path):
        """Test that JSON store is created by default."""
        store = create_persist_store(str(tmp_path))

        assert isinstance(store, JsonPersistStore)

    def test_creates_json_store_explicitly(self, tmp_path: Path):
        """Test that JSON store is created when backend='json'."""
        store = create_persist_store(str(tmp_path), "json")

        assert isinstance(store, JsonPersistStore)

    @pytest.mark.skipif(
        not pytest.importorskip("rocksdict", reason="rocksdict not installed"),
        reason="rocksdict not installed",
    )
    def test_creates_rocksdb_store(self, tmp_path: Path):
        """Test that RocksDB store is created when backend='rocksdb'."""
        from soothe.backends.persistence.rocksdb_store import RocksDBPersistStore

        store = create_persist_store(str(tmp_path), "rocksdb")

        assert isinstance(store, RocksDBPersistStore)

        store.close()

    def test_protocol_compliance(self, tmp_path: Path):
        """Test that created stores implement PersistStore protocol."""
        store = create_persist_store(str(tmp_path), "json")

        assert isinstance(store, PersistStore)
