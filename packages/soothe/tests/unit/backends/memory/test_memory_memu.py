"""Tests for MemU memory backend integration."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe.backends.memory.memu.models import MemoryItem as MemuMemoryItem
from soothe.backends.memory.memu_adapter import MemUMemory
from soothe.protocols.memory import MemoryItem


@pytest.fixture
def mock_config():
    """Create a mock SootheConfig."""
    config = MagicMock()

    # Mock chat model
    chat_model = MagicMock()
    config.create_chat_model.return_value = chat_model

    # Mock embedding model
    embedding_model = MagicMock()
    config.create_embedding_model.return_value = embedding_model

    # Mock config values
    config.assistant_name = "test_agent"

    # Mock nested config structure
    config.protocols.memory.llm_chat_role = "default"
    config.protocols.memory.persist_dir = "/tmp/test_memory"

    return config


@pytest.fixture
def mock_memory_store():
    """Create a mock MemuMemoryStore."""
    store = AsyncMock()

    # Mock add operation
    store.add.return_value = "test-memory-id-123"

    # Mock search operation
    memu_item = MemuMemoryItem(
        id="memory-1",
        content="Test memory content",
        memory_type="knowledge",
        user_id="thread-1",
        importance=0.7,
        tags=["knowledge"],
        created_at=datetime.now(UTC),
    )
    from soothe.backends.memory.memu.models import SearchResult

    search_result = SearchResult(
        memory_item=memu_item,
        relevance_score=0.9,
    )
    store.search.return_value = [search_result]

    # Mock get_all operation
    store.get_all.return_value = [memu_item]

    # Mock delete operation
    store.delete.return_value = True

    # Mock update operation
    store.update.return_value = True

    return store


class TestMemUMemoryInit:
    """Test MemUMemory initialization."""

    def test_init_success(self, mock_config):
        """Test successful initialization."""
        with patch("soothe.backends.memory.memu_adapter.MemuMemoryStore") as mock_store_class:
            memory = MemUMemory(config=mock_config)
            assert memory._store is not None
            mock_store_class.assert_called_once()

    def test_init_with_custom_dir(self, mock_config):
        """Test initialization with custom memory directory."""
        mock_config.protocols.memory.persist_dir = "/custom/memory/dir"

        with patch("soothe.backends.memory.memu_adapter.MemuMemoryStore"):
            memory = MemUMemory(config=mock_config)
            assert memory._store is not None


class TestMemUMemoryRemember:
    """Test remember operation."""

    @pytest.mark.asyncio
    async def test_remember_basic(self, mock_config, mock_memory_store):
        """Test basic memory storage."""
        with patch("soothe.backends.memory.memu_adapter.MemuMemoryStore", return_value=mock_memory_store):
            memory = MemUMemory(config=mock_config)

            item = MemoryItem(
                content="Test memory content",
                source_thread="thread-1",
                tags=["knowledge"],
            )

            memory_id = await memory.remember(item)

            assert memory_id == "test-memory-id-123"
            mock_memory_store.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_remember_with_metadata(self, mock_config, mock_memory_store):
        """Test memory with metadata."""
        with patch("soothe.backends.memory.memu_adapter.MemuMemoryStore", return_value=mock_memory_store):
            memory = MemUMemory(config=mock_config)

            item = MemoryItem(
                content="User name is Alice",
                source_thread="thread-1",
                tags=["profile", "personal"],
                metadata={"importance": 0.9},
            )

            memory_id = await memory.remember(item)
            assert memory_id == "test-memory-id-123"


class TestMemUMemoryRecall:
    """Test recall operation."""

    @pytest.mark.asyncio
    async def test_recall_basic(self, mock_config, mock_memory_store):
        """Test basic semantic search."""
        with patch("soothe.backends.memory.memu_adapter.MemuMemoryStore", return_value=mock_memory_store):
            memory = MemUMemory(config=mock_config)

            results = await memory.recall("test query", limit=5)

            assert len(results) == 1
            assert results[0].id == "memory-1"
            assert results[0].content == "Test memory content"

            mock_memory_store.search.assert_called_once_with(query="test query", limit=5)

    @pytest.mark.asyncio
    async def test_recall_respects_limit(self, mock_config, mock_memory_store):
        """Test that recall respects the limit parameter."""
        with patch("soothe.backends.memory.memu_adapter.MemuMemoryStore", return_value=mock_memory_store):
            memory = MemUMemory(config=mock_config)

            results = await memory.recall("query", limit=1)

            assert len(results) == 1


class TestMemUMemoryRecallByTags:
    """Test recall_by_tags operation."""

    @pytest.mark.asyncio
    async def test_recall_by_tags_basic(self, mock_config, mock_memory_store):
        """Test tag-based retrieval."""
        with patch("soothe.backends.memory.memu_adapter.MemuMemoryStore", return_value=mock_memory_store):
            memory = MemUMemory(config=mock_config)

            results = await memory.recall_by_tags(["knowledge"], limit=10)

            assert len(results) == 1
            assert results[0].tags == ["knowledge"]

            mock_memory_store.get_all.assert_called_once()


class TestMemUMemoryForget:
    """Test forget operation."""

    @pytest.mark.asyncio
    async def test_forget_success(self, mock_config, mock_memory_store):
        """Test successful memory deletion."""
        with patch("soothe.backends.memory.memu_adapter.MemuMemoryStore", return_value=mock_memory_store):
            memory = MemUMemory(config=mock_config)

            result = await memory.forget("memory-1")

            assert result is True
            mock_memory_store.delete.assert_called_once_with("memory-1")

    @pytest.mark.asyncio
    async def test_forget_failure(self, mock_config, mock_memory_store):
        """Test failed memory deletion returns False."""
        mock_memory_store.delete.return_value = False

        with patch("soothe.backends.memory.memu_adapter.MemuMemoryStore", return_value=mock_memory_store):
            memory = MemUMemory(config=mock_config)

            result = await memory.forget("invalid-id")

            assert result is False


class TestMemUMemoryUpdate:
    """Test update operation."""

    @pytest.mark.asyncio
    async def test_update_success(self, mock_config, mock_memory_store):
        """Test successful memory update."""
        with patch("soothe.backends.memory.memu_adapter.MemuMemoryStore", return_value=mock_memory_store):
            memory = MemUMemory(config=mock_config)

            await memory.update("memory-1", "Updated content")

            mock_memory_store.update.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_not_found_raises_keyerror(self, mock_config, mock_memory_store):
        """Test update raises KeyError when memory not found."""
        mock_memory_store.update.return_value = False

        with patch("soothe.backends.memory.memu_adapter.MemuMemoryStore", return_value=mock_memory_store):
            memory = MemUMemory(config=mock_config)

            with pytest.raises(KeyError, match="Memory item 'invalid-id' not found"):
                await memory.update("invalid-id", "New content")


class TestIntegration:
    """Integration tests for MemU memory backend."""

    @pytest.mark.asyncio
    async def test_full_lifecycle(self, mock_config, mock_memory_store):
        """Test complete CRUD lifecycle."""
        with patch("soothe.backends.memory.memu_adapter.MemuMemoryStore", return_value=mock_memory_store):
            memory = MemUMemory(config=mock_config)

            # Create
            item = MemoryItem(content="Test", tags=["knowledge"])
            memory_id = await memory.remember(item)
            assert memory_id == "test-memory-id-123"

            # Read
            results = await memory.recall("Test")
            assert len(results) > 0

            # Update
            await memory.update(memory_id, "Updated test")

            # Delete
            result = await memory.forget(memory_id)
            assert result is True
