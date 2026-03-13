"""Tests for memory store implementations (StoreBackedMemory and VectorMemory)."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from soothe.memory_store.store_backed import StoreBackedMemory
from soothe.protocols.memory import MemoryItem


class TestStoreBackedMemory:
    """Unit tests for StoreBackedMemory."""

    def test_initialization_without_persistence(self):
        """Test initialization without persistence."""
        memory = StoreBackedMemory(persist_path=None)

        assert memory._items == {}
        assert memory._store is None

    def test_initialization_with_json_persistence(self, tmp_path: Path):
        """Test initialization with JSON persistence."""
        memory = StoreBackedMemory(persist_path=str(tmp_path), persist_backend="json")

        assert memory._items == {}
        assert memory._store is not None

    @pytest.mark.asyncio
    async def test_remember_stores_item(self):
        """Test that remember stores a memory item."""
        memory = StoreBackedMemory()
        item = MemoryItem(content="test memory", tags=["test"])

        item_id = await memory.remember(item)

        assert item_id == item.id
        assert item.id in memory._items
        assert memory._items[item.id] == item

    @pytest.mark.asyncio
    async def test_remember_with_persistence(self, tmp_path: Path):
        """Test that remember persists item to storage."""
        memory = StoreBackedMemory(persist_path=str(tmp_path), persist_backend="json")
        item = MemoryItem(content="persisted memory", tags=["test"])

        await memory.remember(item)

        # Create new memory instance to test persistence
        memory2 = StoreBackedMemory(persist_path=str(tmp_path), persist_backend="json")

        assert item.id in memory2._items
        assert memory2._items[item.id].content == "persisted memory"

    @pytest.mark.asyncio
    async def test_recall_by_keyword_match(self):
        """Test recall finds items by keyword matching."""
        memory = StoreBackedMemory()

        item1 = MemoryItem(content="python programming language", importance=0.7)
        item2 = MemoryItem(content="java programming language", importance=0.7)
        item3 = MemoryItem(content="cooking recipes", importance=0.7)

        await memory.remember(item1)
        await memory.remember(item2)
        await memory.remember(item3)

        results = await memory.recall("python", limit=5)

        # Should find python item
        assert len(results) > 0
        assert any("python" in item.content for item in results)

    @pytest.mark.asyncio
    async def test_recall_respects_limit(self):
        """Test that recall respects the limit parameter."""
        memory = StoreBackedMemory()

        for i in range(10):
            item = MemoryItem(content=f"memory item {i}", tags=["test"])
            await memory.remember(item)

        results = await memory.recall("memory", limit=3)

        assert len(results) <= 3

    @pytest.mark.asyncio
    async def test_recall_includes_importance(self):
        """Test that recall considers importance in scoring."""
        memory = StoreBackedMemory()

        item1 = MemoryItem(content="important python", importance=0.9)
        item2 = MemoryItem(content="python basics", importance=0.1)

        await memory.remember(item1)
        await memory.remember(item2)

        results = await memory.recall("python", limit=2)

        # Higher importance should rank higher
        assert results[0].importance >= results[1].importance

    @pytest.mark.asyncio
    async def test_recall_by_tags(self):
        """Test recall_by_tags filters by tags."""
        memory = StoreBackedMemory()

        item1 = MemoryItem(content="item 1", tags=["python", "programming"])
        item2 = MemoryItem(content="item 2", tags=["java", "programming"])
        item3 = MemoryItem(content="item 3", tags=["python", "tutorial"])

        await memory.remember(item1)
        await memory.remember(item2)
        await memory.remember(item3)

        # Find items with both python AND programming tags
        results = await memory.recall_by_tags(["python", "programming"], limit=10)

        assert len(results) == 1
        assert "python" in results[0].tags
        assert "programming" in results[0].tags

    @pytest.mark.asyncio
    async def test_recall_by_tags_respects_limit(self):
        """Test recall_by_tags respects limit."""
        memory = StoreBackedMemory()

        for i in range(10):
            item = MemoryItem(content=f"item {i}", tags=["test", "shared"])
            await memory.remember(item)

        results = await memory.recall_by_tags(["test"], limit=5)

        assert len(results) <= 5

    @pytest.mark.asyncio
    async def test_forget_removes_item(self):
        """Test that forget removes an item."""
        memory = StoreBackedMemory()
        item = MemoryItem(content="to be forgotten")

        await memory.remember(item)
        assert item.id in memory._items

        result = await memory.forget(item.id)

        assert result is True
        assert item.id not in memory._items

    @pytest.mark.asyncio
    async def test_forget_nonexistent_returns_false(self):
        """Test that forget returns False for nonexistent item."""
        memory = StoreBackedMemory()

        result = await memory.forget("nonexistent_id")

        assert result is False

    @pytest.mark.asyncio
    async def test_forget_with_persistence(self, tmp_path: Path):
        """Test that forget removes item from persistence."""
        memory = StoreBackedMemory(persist_path=str(tmp_path), persist_backend="json")
        item = MemoryItem(content="to be forgotten")

        await memory.remember(item)

        result = await memory.forget(item.id)

        assert result is True

        # Create new memory instance to verify deletion
        memory2 = StoreBackedMemory(persist_path=str(tmp_path), persist_backend="json")

        assert item.id not in memory2._items

    @pytest.mark.asyncio
    async def test_update_existing_item(self):
        """Test updating an existing item's content."""
        memory = StoreBackedMemory()
        item = MemoryItem(content="original content")

        await memory.remember(item)
        await memory.update(item.id, "updated content")

        assert memory._items[item.id].content == "updated content"

    @pytest.mark.asyncio
    async def test_update_nonexistent_raises_keyerror(self):
        """Test that update raises KeyError for nonexistent item."""
        memory = StoreBackedMemory()

        with pytest.raises(KeyError, match="not found"):
            await memory.update("nonexistent_id", "new content")

    @pytest.mark.asyncio
    async def test_update_with_persistence(self, tmp_path: Path):
        """Test that update persists changes."""
        memory = StoreBackedMemory(persist_path=str(tmp_path), persist_backend="json")
        item = MemoryItem(content="original")

        await memory.remember(item)
        await memory.update(item.id, "updated")

        # Create new memory instance to verify update persisted
        memory2 = StoreBackedMemory(persist_path=str(tmp_path), persist_backend="json")

        assert memory2._items[item.id].content == "updated"

    @pytest.mark.asyncio
    async def test_recall_by_tags_orders_by_importance(self):
        """Test that recall_by_tags orders results by importance."""
        memory = StoreBackedMemory()

        item1 = MemoryItem(content="item 1", tags=["test"], importance=0.3)
        item2 = MemoryItem(content="item 2", tags=["test"], importance=0.9)
        item3 = MemoryItem(content="item 3", tags=["test"], importance=0.6)

        await memory.remember(item1)
        await memory.remember(item2)
        await memory.remember(item3)

        results = await memory.recall_by_tags(["test"], limit=10)

        # Should be ordered by importance descending
        importances = [item.importance for item in results]
        assert importances == sorted(importances, reverse=True)


class TestVectorMemory:
    """Unit tests for VectorMemory."""

    @pytest.fixture
    def mock_vector_store(self):
        """Create a mock vector store."""
        store = AsyncMock()
        store.search = AsyncMock(return_value=[])
        store.insert = AsyncMock()
        store.list_records = AsyncMock(return_value=[])
        store.get = AsyncMock(return_value=None)
        store.delete = AsyncMock()
        store.update = AsyncMock()
        return store

    @pytest.fixture
    def mock_embeddings(self):
        """Create a mock embeddings model."""
        embeddings = AsyncMock()
        embeddings.aembed_documents = AsyncMock(return_value=[[0.1] * 768])
        embeddings.aembed_query = AsyncMock(return_value=[0.1] * 768)
        return embeddings

    def test_initialization(self, mock_vector_store, mock_embeddings):
        """Test VectorMemory initialization."""
        from soothe.memory_store.vector_memory import VectorMemory

        memory = VectorMemory(mock_vector_store, mock_embeddings)

        assert memory._store == mock_vector_store
        assert memory._embeddings == mock_embeddings

    @pytest.mark.asyncio
    async def test_remember_embeds_and_stores(self, mock_vector_store, mock_embeddings):
        """Test that remember embeds content and stores in vector store."""
        from soothe.memory_store.vector_memory import VectorMemory

        memory = VectorMemory(mock_vector_store, mock_embeddings)
        item = MemoryItem(content="test memory")

        item_id = await memory.remember(item)

        assert item_id == item.id

        # Should embed the content
        mock_embeddings.aembed_documents.assert_called_once_with([item.content])

        # Should insert into vector store
        mock_vector_store.insert.assert_called_once()

    @pytest.mark.asyncio
    async def test_recall_by_semantic_search(self, mock_vector_store, mock_embeddings):
        """Test recall uses semantic search."""
        from soothe.memory_store.vector_memory import VectorMemory
        from soothe.protocols.vector_store import VectorRecord

        # Mock search results
        item1 = MemoryItem(id="1", content="python programming")
        item2 = MemoryItem(id="2", content="java programming")

        mock_vector_store.search = AsyncMock(
            return_value=[
                VectorRecord(id="1", payload=item1.model_dump(mode="json"), score=0.9),
                VectorRecord(id="2", payload=item2.model_dump(mode="json"), score=0.8),
            ]
        )

        memory = VectorMemory(mock_vector_store, mock_embeddings)

        results = await memory.recall("programming languages", limit=5)

        assert len(results) == 2

        # Should embed the query
        mock_embeddings.aembed_query.assert_called_once()

        # Should search with embedded query
        mock_vector_store.search.assert_called_once()

    @pytest.mark.asyncio
    async def test_recall_handles_invalid_payloads(self, mock_vector_store, mock_embeddings):
        """Test recall handles invalid payloads gracefully."""
        from soothe.memory_store.vector_memory import VectorMemory
        from soothe.protocols.vector_store import VectorRecord

        # Mock results with invalid payload
        mock_vector_store.search = AsyncMock(
            return_value=[
                VectorRecord(id="1", payload={"invalid": "data"}, score=0.9),
                VectorRecord(id="2", payload={}, score=0.8),
            ]
        )

        memory = VectorMemory(mock_vector_store, mock_embeddings)

        results = await memory.recall("query", limit=5)

        # Should return empty list since no valid items
        assert results == []

    @pytest.mark.asyncio
    async def test_recall_by_tags(self, mock_vector_store, mock_embeddings):
        """Test recall_by_tags filters by tags."""
        from soothe.memory_store.vector_memory import VectorMemory
        from soothe.protocols.vector_store import VectorRecord

        item1 = MemoryItem(id="1", content="item 1", tags=["python", "programming"])
        item2 = MemoryItem(id="2", content="item 2", tags=["java", "programming"])
        item3 = MemoryItem(id="3", content="item 3", tags=["python", "tutorial"])

        mock_vector_store.list_records = AsyncMock(
            return_value=[
                VectorRecord(id="1", payload=item1.model_dump(mode="json")),
                VectorRecord(id="2", payload=item2.model_dump(mode="json")),
                VectorRecord(id="3", payload=item3.model_dump(mode="json")),
            ]
        )

        memory = VectorMemory(mock_vector_store, mock_embeddings)

        results = await memory.recall_by_tags(["python"], limit=10)

        # Should only return items with python tag
        assert len(results) == 2
        assert all("python" in item.tags for item in results)

    @pytest.mark.asyncio
    async def test_recall_by_tags_respects_limit(self, mock_vector_store, mock_embeddings):
        """Test recall_by_tags respects limit."""
        from soothe.memory_store.vector_memory import VectorMemory
        from soothe.protocols.vector_store import VectorRecord

        items = [MemoryItem(id=str(i), content=f"item {i}", tags=["test"]) for i in range(10)]

        mock_vector_store.list_records = AsyncMock(
            return_value=[VectorRecord(id=item.id, payload=item.model_dump(mode="json")) for item in items]
        )

        memory = VectorMemory(mock_vector_store, mock_embeddings)

        results = await memory.recall_by_tags(["test"], limit=5)

        assert len(results) <= 5

    @pytest.mark.asyncio
    async def test_forget_deletes_from_store(self, mock_vector_store, mock_embeddings):
        """Test that forget deletes item from vector store."""
        from soothe.memory_store.vector_memory import VectorMemory

        memory = VectorMemory(mock_vector_store, mock_embeddings)

        result = await memory.forget("test_id")

        assert result is True
        mock_vector_store.delete.assert_called_once_with("test_id")

    @pytest.mark.asyncio
    async def test_forget_handles_errors(self, mock_vector_store, mock_embeddings):
        """Test that forget returns False on error."""
        from soothe.memory_store.vector_memory import VectorMemory

        mock_vector_store.delete = AsyncMock(side_effect=Exception("DB error"))

        memory = VectorMemory(mock_vector_store, mock_embeddings)

        result = await memory.forget("test_id")

        assert result is False

    @pytest.mark.asyncio
    async def test_update_existing_item(self, mock_vector_store, mock_embeddings):
        """Test updating an existing item."""
        from soothe.memory_store.vector_memory import VectorMemory
        from soothe.protocols.vector_store import VectorRecord

        existing_item = MemoryItem(id="test_id", content="original content")

        mock_vector_store.get = AsyncMock(
            return_value=VectorRecord(
                id="test_id",
                payload=existing_item.model_dump(mode="json"),
            )
        )

        memory = VectorMemory(mock_vector_store, mock_embeddings)

        await memory.update("test_id", "updated content")

        # Should get existing item
        mock_vector_store.get.assert_called_once_with("test_id")

        # Should embed new content
        mock_embeddings.aembed_documents.assert_called_once_with(["updated content"])

        # Should update in store
        mock_vector_store.update.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_nonexistent_raises_keyerror(self, mock_vector_store, mock_embeddings):
        """Test that update raises KeyError for nonexistent item."""
        from soothe.memory_store.vector_memory import VectorMemory

        mock_vector_store.get = AsyncMock(return_value=None)

        memory = VectorMemory(mock_vector_store, mock_embeddings)

        with pytest.raises(KeyError, match="not found"):
            await memory.update("nonexistent_id", "new content")

    @pytest.mark.asyncio
    async def test_update_handles_corrupt_data(self, mock_vector_store, mock_embeddings):
        """Test that update raises KeyError for corrupt data."""
        from soothe.memory_store.vector_memory import VectorMemory
        from soothe.protocols.vector_store import VectorRecord

        mock_vector_store.get = AsyncMock(return_value=VectorRecord(id="test_id", payload={"invalid": "data"}))

        memory = VectorMemory(mock_vector_store, mock_embeddings)

        with pytest.raises(KeyError, match="Corrupt memory record"):
            await memory.update("test_id", "new content")
