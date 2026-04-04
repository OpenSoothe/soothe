"""Unit tests for SQLiteVecStore backend."""

import asyncio
import os
import tempfile


def _run(coro):
    """Run async coroutine with a fresh event loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestSQLiteVecStoreUnit:
    """Unit tests for SQLiteVecStore focusing on interface compliance."""

    def _make_store(self, collection: str = "test_vec", vector_size: int = 4):
        from soothe.backends.vector_store.sqlite_vec import SQLiteVecStore

        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        return SQLiteVecStore(collection=collection, db_path=tmp.name, vector_size=vector_size)

    def test_class_can_be_imported(self) -> None:
        """Test that SQLiteVecStore class can be imported."""
        from soothe.backends.vector_store.sqlite_vec import SQLiteVecStore

        assert SQLiteVecStore is not None

    def test_factory_returns_instance(self) -> None:
        """Test factory creates sqlite_vec instance."""
        from soothe.backends.vector_store import create_vector_store

        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        try:
            store = create_vector_store(
                provider="sqlite_vec",
                collection="test",
                config={"db_path": tmp.name},
            )
            assert store is not None
            assert store.__class__.__name__ == "SQLiteVecStore"
        finally:
            os.unlink(tmp.name)

    def test_create_collection(self) -> None:
        """Test collection creation."""
        store = self._make_store()
        tmp_path = store._db_path
        try:
            _run(store.create_collection(vector_size=4))
        finally:
            _run(store.close())
            os.unlink(tmp_path)

    def test_insert_and_search(self) -> None:
        """Test insert and search operations."""
        store = self._make_store()
        tmp_path = store._db_path
        try:
            _run(store.create_collection(vector_size=4))
            _run(
                store.insert(
                    vectors=[[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]],
                    payloads=[{"label": "a"}, {"label": "b"}],
                    ids=["v1", "v2"],
                )
            )
            results = _run(
                store.search(
                    query="",
                    vector=[1.0, 0.0, 0.0, 0.0],
                    limit=2,
                )
            )
            assert len(results) == 2
            assert results[0].id == "v1"
            assert results[0].score is not None
        finally:
            _run(store.close())
            os.unlink(tmp_path)

    def test_get_record(self) -> None:
        """Test retrieving a single record."""
        store = self._make_store()
        tmp_path = store._db_path
        try:
            _run(store.create_collection(vector_size=4))
            _run(
                store.insert(
                    vectors=[[1.0, 2.0, 3.0, 4.0]],
                    payloads=[{"key": "value"}],
                    ids=["r1"],
                )
            )
            record = _run(store.get("r1"))
            assert record is not None
            assert record.id == "r1"
            assert record.payload == {"key": "value"}
        finally:
            _run(store.close())
            os.unlink(tmp_path)

    def test_delete_record(self) -> None:
        """Test deleting a record."""
        store = self._make_store()
        tmp_path = store._db_path
        try:
            _run(store.create_collection(vector_size=4))
            _run(
                store.insert(
                    vectors=[[1.0, 0.0, 0.0, 0.0]],
                    ids=["del_me"],
                )
            )
            _run(store.delete("del_me"))
            record = _run(store.get("del_me"))
            assert record is None
        finally:
            _run(store.close())
            os.unlink(tmp_path)

    def test_list_records(self) -> None:
        """Test listing records."""
        store = self._make_store()
        tmp_path = store._db_path
        try:
            _run(store.create_collection(vector_size=4))
            _run(
                store.insert(
                    vectors=[[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]],
                    ids=["a", "b"],
                )
            )
            records = _run(store.list_records())
            assert len(records) == 2
        finally:
            _run(store.close())
            os.unlink(tmp_path)

    def test_delete_collection(self) -> None:
        """Test deleting entire collection."""
        store = self._make_store()
        tmp_path = store._db_path
        try:
            _run(store.create_collection(vector_size=4))
            _run(store.insert(vectors=[[1.0, 0.0, 0.0, 0.0]]))
            _run(store.delete_collection())
            records = _run(store.list_records())
            assert len(records) == 0
        finally:
            _run(store.close())
            os.unlink(tmp_path)

    def test_reset_collection(self) -> None:
        """Test resetting collection (clear data, keep table)."""
        store = self._make_store()
        tmp_path = store._db_path
        try:
            _run(store.create_collection(vector_size=4))
            _run(store.insert(vectors=[[1.0, 0.0, 0.0, 0.0]]))
            _run(store.reset())
            records = _run(store.list_records())
            assert len(records) == 0
        finally:
            _run(store.close())
            os.unlink(tmp_path)

    def test_vector_protocols_runtime_checkable(self) -> None:
        """Test SQLiteVecStore is a VectorStoreProtocol at runtime."""
        from soothe.protocols.vector_store import VectorStoreProtocol

        store = self._make_store()
        tmp_path = store._db_path
        try:
            _run(store.create_collection(vector_size=4))
            assert isinstance(store, VectorStoreProtocol)
        finally:
            _run(store.close())
            os.unlink(tmp_path)
