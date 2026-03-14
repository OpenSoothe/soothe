"""Unit tests for vector store implementations (PGVectorStore and WeaviateVectorStore)."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest


class TestPGVectorStoreUnit:
    """Unit tests for PGVectorStore focusing on interface compliance."""

    def test_class_can_be_imported(self):
        """Test that PGVectorStore class can be imported."""
        try:
            from soothe.backends.vector_store.pgvector import PGVectorStore

            assert PGVectorStore is not None
        except ImportError:
            pytest.skip("pgvector dependencies not installed")

    def test_initialization_signature(self):
        """Test that __init__ has expected signature."""
        try:
            import inspect

            from soothe.backends.vector_store.pgvector import PGVectorStore

            init_sig = inspect.signature(PGVectorStore.__init__)
            params = list(init_sig.parameters.keys())

            # Should have these parameters
            assert "self" in params
            assert "collection" in params

            # Check defaults
            assert init_sig.parameters["collection"].default == "soothe_vectors"
            assert init_sig.parameters["dsn"].default == "postgresql://localhost/soothe"
            assert init_sig.parameters["pool_size"].default == 5
            assert init_sig.parameters["index_type"].default == "hnsw"

        except ImportError:
            pytest.skip("pgvector dependencies not installed")

    def test_required_methods_exist(self):
        """Test that all required methods exist on the class."""
        try:
            from soothe.backends.vector_store.pgvector import PGVectorStore

            required_methods = [
                "create_collection",
                "insert",
                "search",
                "delete",
                "update",
                "get",
                "list_records",
                "delete_collection",
                "reset",
            ]

            for method_name in required_methods:
                assert hasattr(PGVectorStore, method_name), f"Missing method: {method_name}"
                assert callable(getattr(PGVectorStore, method_name)), f"Method not callable: {method_name}"

        except ImportError:
            pytest.skip("pgvector dependencies not installed")

    @pytest.mark.asyncio
    async def test_can_instantiate_without_connection(self):
        """Test that class can be instantiated without immediate connection."""
        try:
            from soothe.backends.vector_store.pgvector import PGVectorStore

            store = PGVectorStore(
                collection="test_collection",
                dsn="postgresql://localhost/test",
                pool_size=5,
                index_type="hnsw",
            )

            assert store._collection == "test_collection"
            assert store._dsn == "postgresql://localhost/test"
            assert store._pool_size == 5
            assert store._index_type == "hnsw"
            assert store._pool is None  # Lazy connection

        except ImportError:
            pytest.skip("pgvector dependencies not installed")

    @pytest.mark.asyncio
    async def test_create_collection_creates_table(self):
        """Test create_collection creates the table and index."""
        try:
            from soothe.backends.vector_store.pgvector import PGVectorStore

            store = PGVectorStore(collection="test_vectors")

            # Mock the connection pool properly
            mock_pool = AsyncMock()
            mock_conn = AsyncMock()

            # Set up the async context manager properly
            mock_conn.execute = AsyncMock()
            mock_pool.connection = MagicMock()
            mock_pool.connection.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_pool.connection.return_value.__aexit__ = AsyncMock(return_value=None)

            store._pool = mock_pool

            await store.create_collection(vector_size=768, distance="cosine")

            # Should execute CREATE TABLE and CREATE INDEX
            assert mock_conn.execute.call_count >= 2

        except ImportError:
            pytest.skip("pgvector dependencies not installed")

    @pytest.mark.asyncio
    async def test_insert_vectors(self):
        """Test inserting vectors with payloads."""
        try:
            from soothe.backends.vector_store.pgvector import PGVectorStore

            store = PGVectorStore(collection="test_vectors")

            # Mock the connection pool properly
            mock_pool = AsyncMock()
            mock_conn = AsyncMock()
            mock_conn.execute = AsyncMock()
            mock_pool.connection = MagicMock()
            mock_pool.connection.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_pool.connection.return_value.__aexit__ = AsyncMock(return_value=None)

            store._pool = mock_pool

            vectors = [[0.1, 0.2, 0.3] * 256]
            payloads = [{"data": "test"}]
            ids = ["test_id_1"]

            await store.insert(vectors=vectors, payloads=payloads, ids=ids)

            # Should execute INSERT
            mock_conn.execute.assert_called()

        except ImportError:
            pytest.skip("pgvector dependencies not installed")

    @pytest.mark.asyncio
    async def test_search_vectors(self):
        """Test searching for vectors."""
        try:
            from soothe.backends.vector_store.pgvector import PGVectorStore

            store = PGVectorStore(collection="test_vectors")

            # Mock the connection pool properly
            mock_pool = AsyncMock()
            mock_conn = AsyncMock()
            mock_rows = AsyncMock()
            mock_rows.fetchall = AsyncMock(
                return_value=[
                    ("id1", {"data": "test1"}, 0.95),
                    ("id2", {"data": "test2"}, 0.85),
                ]
            )
            mock_conn.execute = AsyncMock(return_value=mock_rows)
            mock_pool.connection = MagicMock()
            mock_pool.connection.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_pool.connection.return_value.__aexit__ = AsyncMock(return_value=None)

            store._pool = mock_pool

            query_vector = [0.1, 0.2, 0.3] * 256
            results = await store.search(query="test query", vector=query_vector, limit=5)

            assert len(results) == 2
            assert results[0].id == "id1"
            assert results[0].score == 0.95

        except ImportError:
            pytest.skip("pgvector dependencies not installed")

    @pytest.mark.asyncio
    async def test_delete_record(self):
        """Test deleting a record."""
        try:
            from soothe.backends.vector_store.pgvector import PGVectorStore

            store = PGVectorStore(collection="test_vectors")

            # Mock the connection pool properly
            mock_pool = AsyncMock()
            mock_conn = AsyncMock()
            mock_conn.execute = AsyncMock()
            mock_pool.connection = MagicMock()
            mock_pool.connection.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_pool.connection.return_value.__aexit__ = AsyncMock(return_value=None)

            store._pool = mock_pool

            await store.delete("test_id")

            mock_conn.execute.assert_called_once()

        except ImportError:
            pytest.skip("pgvector dependencies not installed")

    @pytest.mark.asyncio
    async def test_update_record(self):
        """Test updating a record."""
        try:
            from soothe.backends.vector_store.pgvector import PGVectorStore

            store = PGVectorStore(collection="test_vectors")

            # Mock the connection pool properly
            mock_pool = AsyncMock()
            mock_conn = AsyncMock()
            mock_conn.execute = AsyncMock()
            mock_pool.connection = MagicMock()
            mock_pool.connection.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_pool.connection.return_value.__aexit__ = AsyncMock(return_value=None)

            store._pool = mock_pool

            await store.update(
                record_id="test_id",
                vector=[0.1, 0.2, 0.3] * 256,
                payload={"updated": True},
            )

            mock_conn.execute.assert_called_once()

        except ImportError:
            pytest.skip("pgvector dependencies not installed")

    @pytest.mark.asyncio
    async def test_get_record(self):
        """Test retrieving a record by ID."""
        try:
            from soothe.backends.vector_store.pgvector import PGVectorStore

            store = PGVectorStore(collection="test_vectors")

            # Mock the connection pool properly
            mock_pool = AsyncMock()
            mock_conn = AsyncMock()
            mock_row = AsyncMock()
            mock_row.fetchone = AsyncMock(return_value=("test_id", {"data": "test"}))
            mock_conn.execute = AsyncMock(return_value=mock_row)
            mock_pool.connection = MagicMock()
            mock_pool.connection.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_pool.connection.return_value.__aexit__ = AsyncMock(return_value=None)

            store._pool = mock_pool

            result = await store.get("test_id")

            assert result is not None
            assert result.id == "test_id"
            assert result.payload == {"data": "test"}

        except ImportError:
            pytest.skip("pgvector dependencies not installed")

    @pytest.mark.asyncio
    async def test_get_nonexistent_record(self):
        """Test retrieving a nonexistent record returns None."""
        try:
            from soothe.backends.vector_store.pgvector import PGVectorStore

            store = PGVectorStore(collection="test_vectors")

            # Mock the connection pool properly
            mock_pool = AsyncMock()
            mock_conn = AsyncMock()
            mock_row = AsyncMock()
            mock_row.fetchone = AsyncMock(return_value=None)
            mock_conn.execute = AsyncMock(return_value=mock_row)
            mock_pool.connection = MagicMock()
            mock_pool.connection.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_pool.connection.return_value.__aexit__ = AsyncMock(return_value=None)

            store._pool = mock_pool

            result = await store.get("nonexistent_id")

            assert result is None

        except ImportError:
            pytest.skip("pgvector dependencies not installed")


class TestWeaviateVectorStoreUnit:
    """Unit tests for WeaviateVectorStore focusing on interface compliance."""

    def test_class_can_be_imported(self):
        """Test that WeaviateVectorStore class can be imported."""
        try:
            from soothe.backends.vector_store.weaviate import WeaviateVectorStore

            assert WeaviateVectorStore is not None
        except ImportError:
            pytest.skip("weaviate dependencies not installed")

    def test_initialization_signature(self):
        """Test that __init__ has expected signature."""
        try:
            import inspect

            from soothe.backends.vector_store.weaviate import WeaviateVectorStore

            init_sig = inspect.signature(WeaviateVectorStore.__init__)
            params = list(init_sig.parameters.keys())

            # Should have these parameters
            assert "self" in params
            assert "collection" in params

            # Check defaults
            assert init_sig.parameters["collection"].default == "SootheVectors"
            assert init_sig.parameters["url"].default == "http://localhost:8080"
            assert init_sig.parameters["api_key"].default is None
            assert init_sig.parameters["grpc_port"].default == 50051

        except ImportError:
            pytest.skip("weaviate dependencies not installed")

    def test_required_methods_exist(self):
        """Test that all required methods exist on the class."""
        try:
            from soothe.backends.vector_store.weaviate import WeaviateVectorStore

            required_methods = [
                "create_collection",
                "insert",
                "search",
                "delete",
                "update",
                "get",
                "list_records",
                "delete_collection",
                "reset",
            ]

            for method_name in required_methods:
                assert hasattr(WeaviateVectorStore, method_name), f"Missing method: {method_name}"
                assert callable(getattr(WeaviateVectorStore, method_name)), f"Method not callable: {method_name}"

        except ImportError:
            pytest.skip("weaviate dependencies not installed")

    def test_can_instantiate_without_connection(self):
        """Test that class can be instantiated without immediate connection."""
        try:
            from soothe.backends.vector_store.weaviate import WeaviateVectorStore

            store = WeaviateVectorStore(
                collection="test_collection",
                url="http://localhost:8080",
                api_key="test_key",
                grpc_port=50051,
            )

            assert store._collection_name == "test_collection"
            assert store._url == "http://localhost:8080"
            assert store._api_key == "test_key"
            assert store._grpc_port == 50051
            assert store._client is None  # Lazy connection

        except ImportError:
            pytest.skip("weaviate dependencies not installed")

    def test_weaviate_uuid_generation(self):
        """Test deterministic UUID generation."""
        try:
            from soothe.backends.vector_store.weaviate import weaviate_uuid_from_str

            uuid1 = weaviate_uuid_from_str("test_string")
            uuid2 = weaviate_uuid_from_str("test_string")

            # Same input should produce same UUID
            assert uuid1 == uuid2

            # Different inputs should produce different UUIDs
            uuid3 = weaviate_uuid_from_str("different_string")
            assert uuid1 != uuid3

            # Should be valid UUID format
            uuid.UUID(uuid1)

        except ImportError:
            pytest.skip("weaviate dependencies not installed")


class TestVectorStoreFactory:
    """Tests for create_vector_store factory function."""

    def test_creates_pgvector_store(self):
        """Test that factory creates PGVectorStore."""
        try:
            from soothe.vector_store import create_vector_store
            from soothe.backends.vector_store.pgvector import PGVectorStore

            store = create_vector_store(
                provider="pgvector",
                collection="test_collection",
                config={"dsn": "postgresql://localhost/test"},
            )

            assert isinstance(store, PGVectorStore)

        except ImportError:
            pytest.skip("pgvector dependencies not installed")

    def test_creates_weaviate_store(self):
        """Test that factory creates WeaviateVectorStore."""
        try:
            from soothe.vector_store import create_vector_store
            from soothe.backends.vector_store.weaviate import WeaviateVectorStore

            store = create_vector_store(
                provider="weaviate",
                collection="test_collection",
                config={"url": "http://localhost:8080"},
            )

            assert isinstance(store, WeaviateVectorStore)

        except ImportError:
            pytest.skip("weaviate dependencies not installed")

    def test_raises_error_for_unknown_provider(self):
        """Test that factory raises error for unknown provider."""
        from soothe.vector_store import create_vector_store

        with pytest.raises(ValueError, match="Unknown vector store provider"):
            create_vector_store(
                provider="unknown",
                collection="test_collection",
            )

    def test_creates_with_defaults(self):
        """Test that factory creates store with default config."""
        try:
            from soothe.vector_store import create_vector_store
            from soothe.backends.vector_store.pgvector import PGVectorStore

            store = create_vector_store(
                provider="pgvector",
                collection="test_collection",
            )

            assert isinstance(store, PGVectorStore)
            assert store._collection == "test_collection"

        except ImportError:
            pytest.skip("pgvector dependencies not installed")
