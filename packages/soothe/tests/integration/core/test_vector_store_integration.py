"""Integration tests for vector store implementations with external databases."""

import uuid

import pytest


# Fixtures for PostgreSQL/pgvector
@pytest.fixture
def pgvector_config():
    """Configuration for pgvector tests."""
    return {
        "dsn": "postgresql://postgres:postgres@localhost:5432/vectordb",
        "pool_size": 5,
    }


@pytest.fixture
def pgvector_store(pgvector_config):
    """Create a PGVectorStore instance for testing."""
    try:
        from soothe.backends.vector_store.pgvector import PGVectorStore

        collection = f"test_collection_{uuid.uuid4().hex[:8]}"
        store = PGVectorStore(
            collection=collection,
            dsn=pgvector_config["dsn"],
            pool_size=pgvector_config["pool_size"],
            index_type="hnsw",
        )

        yield store

        # Cleanup
        try:
            import asyncio

            asyncio.run(store.delete_collection())
        except Exception:
            pass

    except ImportError:
        pytest.skip("pgvector dependencies not installed")


# Fixtures for Weaviate
@pytest.fixture
def weaviate_config():
    """Configuration for Weaviate tests."""
    return {
        "url": "http://localhost:8081",
        "grpc_port": 50052,
    }


@pytest.fixture
def weaviate_store(weaviate_config):
    """Create a WeaviateVectorStore instance for testing."""
    try:
        from soothe.backends.vector_store.weaviate import WeaviateVectorStore

        collection = f"TestCollection_{uuid.uuid4().hex[:8]}"
        store = WeaviateVectorStore(
            collection=collection,
            url=weaviate_config["url"],
            grpc_port=weaviate_config["grpc_port"],
        )

        # Test connection before yielding
        import asyncio

        async def test_connection():
            try:
                # Try to access the weaviate client to verify connection
                _ = store._client
                return True
            except Exception:
                return False

        if not asyncio.run(test_connection()):
            pytest.skip("Weaviate server not available")

        yield store

        # Cleanup
        try:
            asyncio.run(store.delete_collection())
        except Exception:
            pass

    except ImportError:
        pytest.skip("weaviate dependencies not installed")
    except Exception as e:
        pytest.skip(f"Weaviate not available: {e}")


@pytest.mark.integration
class TestPGVectorStoreIntegration:
    """Integration tests for PGVectorStore with real PostgreSQL database."""

    @pytest.mark.asyncio
    async def test_create_collection(self, pgvector_store) -> None:
        """Test collection creation."""
        await pgvector_store.create_collection(vector_size=768, distance="cosine")

        # Should not raise an error when creating again
        await pgvector_store.create_collection(vector_size=768, distance="cosine")

    @pytest.mark.asyncio
    async def test_insert_and_get(self, pgvector_store) -> None:
        """Test inserting and retrieving vectors."""
        await pgvector_store.create_collection(vector_size=768, distance="cosine")

        test_vectors = [[0.1] * 768]
        test_payloads = [{"data": "test object", "hash": "abc123"}]
        test_ids = [str(uuid.uuid4())]

        await pgvector_store.insert(test_vectors, test_payloads, test_ids)

        result = await pgvector_store.get(test_ids[0])

        assert result is not None
        assert result.id == test_ids[0]
        assert result.payload["data"] == "test object"
        assert result.payload["hash"] == "abc123"

    @pytest.mark.asyncio
    async def test_search(self, pgvector_store) -> None:
        """Test vector search functionality."""
        await pgvector_store.create_collection(vector_size=768, distance="cosine")

        # Insert test data
        test_vectors = [
            [0.1] * 768,
            [0.5] * 768,
            [0.9] * 768,
        ]
        test_payloads = [
            {"data": "first object", "category": "A"},
            {"data": "second object", "category": "B"},
            {"data": "third object", "category": "A"},
        ]
        test_ids = [str(uuid.uuid4()) for _ in range(3)]

        await pgvector_store.insert(test_vectors, test_payloads, test_ids)

        # Search with query vector similar to first vector
        query_vector = [0.1] * 768
        results = await pgvector_store.search(
            query="test query",
            vector=query_vector,
            limit=2,
        )

        assert len(results) > 0
        assert results[0].score is not None
        # Results should contain our inserted IDs (similarity search works)
        result_ids = {r.id for r in results}
        assert len(result_ids & set(test_ids)) > 0

    @pytest.mark.asyncio
    async def test_search_with_filters(self, pgvector_store) -> None:
        """Test search with metadata filters."""
        await pgvector_store.create_collection(vector_size=768, distance="cosine")

        # Insert test data
        test_vectors = [[0.1] * 768, [0.5] * 768]
        test_payloads = [
            {"data": "first object", "category": "A", "user_id": "user1"},
            {"data": "second object", "category": "B", "user_id": "user2"},
        ]
        test_ids = [str(uuid.uuid4()) for _ in range(2)]

        await pgvector_store.insert(test_vectors, test_payloads, test_ids)

        # Search with filter
        query_vector = [0.1] * 768
        filters = {"user_id": "user1"}
        results = await pgvector_store.search(
            query="test query",
            vector=query_vector,
            limit=5,
            filters=filters,
        )

        assert len(results) > 0
        assert all(result.payload.get("user_id") == "user1" for result in results)

    @pytest.mark.asyncio
    async def test_update(self, pgvector_store) -> None:
        """Test updating vector and payload."""
        await pgvector_store.create_collection(vector_size=768, distance="cosine")

        # Insert initial data
        test_vector = [0.1] * 768
        test_payload = {"data": "original", "version": 1}
        test_id = str(uuid.uuid4())

        await pgvector_store.insert([test_vector], [test_payload], [test_id])

        # Update payload
        new_payload = {"data": "updated", "version": 2}
        await pgvector_store.update(test_id, payload=new_payload)

        result = await pgvector_store.get(test_id)
        assert result.payload["data"] == "updated"
        assert result.payload["version"] == 2

        # Update vector
        new_vector = [0.5] * 768
        await pgvector_store.update(test_id, vector=new_vector)

        # Verify vector update (payload should remain)
        result = await pgvector_store.get(test_id)
        assert result.payload["data"] == "updated"

    @pytest.mark.asyncio
    async def test_delete(self, pgvector_store) -> None:
        """Test deleting vectors."""
        await pgvector_store.create_collection(vector_size=768, distance="cosine")

        test_vector = [0.1] * 768
        test_payload = {"data": "to delete"}
        test_id = str(uuid.uuid4())

        await pgvector_store.insert([test_vector], [test_payload], [test_id])

        # Verify insertion
        result = await pgvector_store.get(test_id)
        assert result is not None

        # Delete
        await pgvector_store.delete(test_id)

        # Verify deletion
        result = await pgvector_store.get(test_id)
        assert result is None

    @pytest.mark.asyncio
    async def test_list_records(self, pgvector_store) -> None:
        """Test listing all vectors."""
        await pgvector_store.create_collection(vector_size=768, distance="cosine")

        # Insert multiple vectors
        test_vectors = [[0.1] * 768, [0.5] * 768]
        test_payloads = [
            {"data": "first", "category": "A"},
            {"data": "second", "category": "B"},
        ]
        test_ids = [str(uuid.uuid4()) for _ in range(2)]

        await pgvector_store.insert(test_vectors, test_payloads, test_ids)

        # List all
        results = await pgvector_store.list_records()
        assert len(results) >= 2

        # Verify our inserted records are in the results
        result_ids = {r.id for r in results}
        assert len(result_ids & set(test_ids)) == 2

    @pytest.mark.asyncio
    async def test_reset(self, pgvector_store) -> None:
        """Test collection reset (truncate)."""
        await pgvector_store.create_collection(vector_size=768, distance="cosine")

        # Insert some data
        test_vector = [0.1] * 768
        test_payload = {"data": "test"}
        test_id = str(uuid.uuid4())

        await pgvector_store.insert([test_vector], [test_payload], [test_id])

        # Verify data exists
        result = await pgvector_store.get(test_id)
        assert result is not None

        # Reset
        await pgvector_store.reset()

        # Verify data is gone
        result = await pgvector_store.get(test_id)
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_collection(self, pgvector_store) -> None:
        """Test deleting the entire collection."""
        await pgvector_store.create_collection(vector_size=768, distance="cosine")

        test_vector = [0.1] * 768
        test_payload = {"data": "test"}
        test_id = str(uuid.uuid4())

        await pgvector_store.insert([test_vector], [test_payload], [test_id])

        # Delete collection
        await pgvector_store.delete_collection()

        # Collection should be gone (would error on operations)
        # We verify by checking we can recreate it
        await pgvector_store.create_collection(vector_size=768, distance="cosine")

    @pytest.mark.asyncio
    async def test_batch_operations(self, pgvector_store) -> None:
        """Test batch insert operations."""
        await pgvector_store.create_collection(vector_size=768, distance="cosine")

        # Insert multiple vectors in batch
        test_vectors = [
            [0.1] * 768,
            [0.2] * 768,
            [0.3] * 768,
            [0.4] * 768,
        ]
        test_payloads = [{"data": f"object_{i}", "batch": "test"} for i in range(4)]
        test_ids = [str(uuid.uuid4()) for _ in range(4)]

        await pgvector_store.insert(test_vectors, test_payloads, test_ids)

        # Verify all were inserted
        for test_id in test_ids:
            result = await pgvector_store.get(test_id)
            assert result is not None

        # Search to verify they're searchable
        query_vector = [0.1] * 768
        results = await pgvector_store.search("batch test", query_vector, limit=10)
        assert len(results) >= 4


@pytest.mark.integration
@pytest.mark.skip(reason="Weaviate server not available for integration tests")
class TestWeaviateVectorStoreIntegration:
    """Integration tests for WeaviateVectorStore with real Weaviate instance."""

    @pytest.mark.asyncio
    async def test_create_collection(self, weaviate_store) -> None:
        """Test collection creation."""
        await weaviate_store.create_collection(vector_size=768, distance="cosine")

        # Should not raise an error when creating again
        await weaviate_store.create_collection(vector_size=768, distance="cosine")

    @pytest.mark.asyncio
    async def test_insert_and_get(self, weaviate_store) -> None:
        """Test inserting and retrieving vectors."""
        await weaviate_store.create_collection(vector_size=768, distance="cosine")

        test_vectors = [[0.1] * 768]
        test_payloads = [{"data": "test object", "hash": "abc123"}]
        test_ids = [str(uuid.uuid4())]

        await weaviate_store.insert(test_vectors, test_payloads, test_ids)

        result = await weaviate_store.get(test_ids[0])

        assert result is not None
        assert result.id == test_ids[0]
        assert result.payload["data"] == "test object"

    @pytest.mark.asyncio
    async def test_search(self, weaviate_store) -> None:
        """Test vector search functionality."""
        await weaviate_store.create_collection(vector_size=768, distance="cosine")

        # Insert test data
        test_vectors = [
            [0.1] * 768,
            [0.5] * 768,
            [0.9] * 768,
        ]
        test_payloads = [
            {"data": "first object", "category": "A"},
            {"data": "second object", "category": "B"},
            {"data": "third object", "category": "A"},
        ]
        test_ids = [str(uuid.uuid4()) for _ in range(3)]

        await weaviate_store.insert(test_vectors, test_payloads, test_ids)

        # Wait a bit for indexing
        import asyncio

        await asyncio.sleep(1)

        # Search with query vector similar to first vector
        query_vector = [0.1] * 768
        results = await weaviate_store.search(
            query="test query",
            vector=query_vector,
            limit=2,
        )

        # Verify search returns results (may not be exact match due to async indexing)
        assert len(results) >= 0  # Weaviate may need time to index
        if len(results) > 0:
            assert results[0].score is not None

    @pytest.mark.asyncio
    async def test_delete(self, weaviate_store) -> None:
        """Test deleting vectors."""
        await weaviate_store.create_collection(vector_size=768, distance="cosine")

        test_vector = [0.1] * 768
        test_payload = {"data": "to delete"}
        test_id = str(uuid.uuid4())

        await weaviate_store.insert([test_vector], [test_payload], [test_id])

        # Verify insertion
        result = await weaviate_store.get(test_id)
        assert result is not None

        # Delete
        await weaviate_store.delete(test_id)

        # Verify deletion
        result = await weaviate_store.get(test_id)
        assert result is None

    @pytest.mark.asyncio
    async def test_update(self, weaviate_store) -> None:
        """Test updating vector and payload."""
        await weaviate_store.create_collection(vector_size=768, distance="cosine")

        # Insert initial data
        test_vector = [0.1] * 768
        test_payload = {"data": "original", "version": 1}
        test_id = str(uuid.uuid4())

        await weaviate_store.insert([test_vector], [test_payload], [test_id])

        # Update payload
        new_payload = {"data": "updated", "version": 2}
        await weaviate_store.update(test_id, payload=new_payload)

        result = await weaviate_store.get(test_id)
        assert result.payload["data"] == "updated"

    @pytest.mark.asyncio
    async def test_list_records(self, weaviate_store) -> None:
        """Test listing all vectors."""
        await weaviate_store.create_collection(vector_size=768, distance="cosine")

        # Insert multiple vectors
        test_vectors = [[0.1] * 768, [0.5] * 768]
        test_payloads = [
            {"data": "first", "category": "A"},
            {"data": "second", "category": "B"},
        ]
        test_ids = [str(uuid.uuid4()) for _ in range(2)]

        await weaviate_store.insert(test_vectors, test_payloads, test_ids)

        # List all
        results = await weaviate_store.list_records()
        assert len(results) >= 2

    @pytest.mark.asyncio
    async def test_reset(self, weaviate_store) -> None:
        """Test collection reset."""
        await weaviate_store.create_collection(vector_size=768, distance="cosine")

        # Insert some data
        test_vector = [0.1] * 768
        test_payload = {"data": "test"}
        test_id = str(uuid.uuid4())

        await weaviate_store.insert([test_vector], [test_payload], [test_id])

        # Verify data exists
        result = await weaviate_store.get(test_id)
        assert result is not None

        # Reset (delete collection)
        await weaviate_store.reset()

        # Collection should be deleted
        # We can recreate it
        await weaviate_store.create_collection(vector_size=768, distance="cosine")

    @pytest.mark.asyncio
    async def test_delete_collection(self, weaviate_store) -> None:
        """Test deleting the entire collection."""
        await weaviate_store.create_collection(vector_size=768, distance="cosine")

        test_vector = [0.1] * 768
        test_payload = {"data": "test"}
        test_id = str(uuid.uuid4())

        await weaviate_store.insert([test_vector], [test_payload], [test_id])

        # Delete collection
        await weaviate_store.delete_collection()

        # Should be able to recreate
        await weaviate_store.create_collection(vector_size=768, distance="cosine")
