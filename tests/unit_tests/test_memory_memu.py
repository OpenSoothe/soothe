"""Tests for MemU memory backend integration."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe.backends.memory.memu import MemUMemory, _compute_importance
from soothe.protocols.memory import MemoryItem


@pytest.fixture
def mock_memory_service():
    """Create a mock MemU MemoryService."""
    service = AsyncMock()

    # Mock create_memory_item
    service.create_memory_item.return_value = {
        "memory_item": {
            "id": "test-memory-id-123",
            "summary": "Test memory content",
            "created_at": datetime.now(UTC),
            "user_id": "thread-1",
            "extra": {},
        }
    }

    # Mock retrieve
    service.retrieve.return_value = {
        "items": [
            {
                "id": "memory-1",
                "summary": "First memory",
                "created_at": datetime.now(UTC),
                "user_id": "thread-1",
                "extra": {"reinforcement_count": 3},
            },
            {
                "id": "memory-2",
                "summary": "Second memory",
                "created_at": datetime.now(UTC),
                "user_id": "thread-2",
                "extra": {"reinforcement_count": 1},
            },
        ]
    }

    # Mock list_memory_items
    service.list_memory_items.return_value = {
        "items": [
            {
                "id": "memory-3",
                "summary": "Tagged memory",
                "created_at": datetime.now(UTC),
                "user_id": "thread-1",
                "extra": {"reinforcement_count": 5},
            },
        ]
    }

    # Mock delete_memory_item
    service.delete_memory_item.return_value = None

    # Mock update_memory_item
    service.update_memory_item.return_value = {
        "memory_item": {
            "id": "memory-1",
            "summary": "Updated content",
            "created_at": datetime.now(UTC),
            "user_id": "thread-1",
            "extra": {},
        }
    }

    return service


@pytest.fixture
def memu_memory(mock_memory_service):
    """Create a MemUMemory instance with mocked service."""
    with patch("soothe.backends.memory.memu.MemoryService", return_value=mock_memory_service):
        from memu.app.settings import (
            DatabaseConfig,
            LLMConfig,
            LLMProfilesConfig,
            MemorizeConfig,
            RetrieveConfig,
            UserConfig,
        )

        llm_config = LLMConfig(model="gpt-4o-mini", api_key="test-key")
        embedding_config = LLMConfig(model="text-embedding-3-small", api_key="test-key")
        llm_profiles = LLMProfilesConfig(default=llm_config, embedding=embedding_config)

        memory = MemUMemory(
            llm_profiles=llm_profiles,
            database_config=DatabaseConfig(provider="inmemory"),
            memorize_config=MemorizeConfig(),
            retrieve_config=RetrieveConfig(),
            user_config=UserConfig(),
        )
        memory._service = mock_memory_service
        return memory


class TestMemUMemoryInit:
    """Test MemUMemory initialization."""

    def test_init_without_memu_raises_import_error(self):
        """Test that initialization fails gracefully when MemU is not installed."""
        with patch("soothe.backends.memory.memu.MEMU_AVAILABLE", new=False):
            with pytest.raises(ImportError, match="MemU is not installed"):
                MemUMemory()

    def test_init_success(self, mock_memory_service):
        """Test successful initialization."""
        with patch("soothe.backends.memory.memu.MemoryService", return_value=mock_memory_service):
            memory = MemUMemory()
            assert memory._service is not None


class TestMemUMemoryRemember:
    """Test remember operation."""

    @pytest.mark.asyncio
    async def test_remember_basic(self, memu_memory, mock_memory_service):
        """Test basic memory storage."""
        item = MemoryItem(
            content="Test memory content",
            source_thread="thread-1",
            tags=["knowledge"],
        )

        memory_id = await memu_memory.remember(item)

        assert memory_id == "test-memory-id-123"
        mock_memory_service.create_memory_item.assert_called_once_with(
            memory_type="knowledge",
            memory_content="Test memory content",
            memory_categories=["knowledge"],
            user={"user_id": "thread-1"},
            propagate=True,
        )

    @pytest.mark.asyncio
    async def test_remember_with_profile_tag(self, memu_memory, mock_memory_service):
        """Test memory with profile tag maps to profile memory type."""
        item = MemoryItem(
            content="User name is Alice",
            source_thread="thread-1",
            tags=["profile", "personal"],
        )

        await memu_memory.remember(item)

        mock_memory_service.create_memory_item.assert_called_once()
        call_kwargs = mock_memory_service.create_memory_item.call_args[1]
        assert call_kwargs["memory_type"] == "profile"

    @pytest.mark.asyncio
    async def test_remember_with_event_tag(self, memu_memory, mock_memory_service):
        """Test memory with event tag maps to event memory type."""
        item = MemoryItem(
            content="Meeting at 3pm",
            source_thread="thread-1",
            tags=["event", "schedule"],
        )

        await memu_memory.remember(item)

        mock_memory_service.create_memory_item.assert_called_once()
        call_kwargs = mock_memory_service.create_memory_item.call_args[1]
        assert call_kwargs["memory_type"] == "event"

    @pytest.mark.asyncio
    async def test_remember_without_source_thread(self, memu_memory, mock_memory_service):
        """Test memory without source thread has no user scope."""
        item = MemoryItem(
            content="General knowledge",
            tags=["knowledge"],
        )

        await memu_memory.remember(item)

        mock_memory_service.create_memory_item.assert_called_once()
        call_kwargs = mock_memory_service.create_memory_item.call_args[1]
        assert call_kwargs["user"] is None


class TestMemUMemoryRecall:
    """Test recall operation."""

    @pytest.mark.asyncio
    async def test_recall_basic(self, memu_memory, mock_memory_service):
        """Test basic semantic search."""
        results = await memu_memory.recall("test query", limit=5)

        assert len(results) == 2
        assert results[0].id == "memory-1"
        assert results[0].content == "First memory"
        assert results[1].id == "memory-2"
        assert results[1].content == "Second memory"

        mock_memory_service.retrieve.assert_called_once_with(
            queries=[{"query": "test query"}],
            where=None,
        )

    @pytest.mark.asyncio
    async def test_recall_respects_limit(self, memu_memory, mock_memory_service):
        """Test that recall respects the limit parameter."""
        results = await memu_memory.recall("query", limit=1)

        assert len(results) == 1
        assert results[0].id == "memory-1"

    @pytest.mark.asyncio
    async def test_recall_importance_computation(self, memu_memory, mock_memory_service):
        """Test that importance is computed from reinforcement count."""
        results = await memu_memory.recall("query")

        # First item has reinforcement_count=3, importance=log(4)/log(10)
        expected_importance_1 = min(1.0, math.log(4) / math.log(10))
        assert abs(results[0].importance - expected_importance_1) < 0.01

        # Second item has reinforcement_count=1, importance=log(2)/log(10)
        expected_importance_2 = min(1.0, math.log(2) / math.log(10))
        assert abs(results[1].importance - expected_importance_2) < 0.01


class TestMemUMemoryRecallByTags:
    """Test recall_by_tags operation."""

    @pytest.mark.asyncio
    async def test_recall_by_tags_basic(self, memu_memory, mock_memory_service):
        """Test tag-based retrieval."""
        results = await memu_memory.recall_by_tags(["knowledge", "programming"], limit=10)

        assert len(results) == 1
        assert results[0].id == "memory-3"
        assert results[0].tags == ["knowledge", "programming"]

        mock_memory_service.list_memory_items.assert_called_once_with(
            where={"categories__has": ["knowledge", "programming"]}
        )

    @pytest.mark.asyncio
    async def test_recall_by_tags_sorting(self, memu_memory, mock_memory_service):
        """Test that results are sorted by importance."""
        # Add multiple items with different reinforcement counts
        mock_memory_service.list_memory_items.return_value = {
            "items": [
                {
                    "id": "memory-low",
                    "summary": "Low importance",
                    "created_at": datetime.now(UTC),
                    "extra": {"reinforcement_count": 1},
                },
                {
                    "id": "memory-high",
                    "summary": "High importance",
                    "created_at": datetime.now(UTC),
                    "extra": {"reinforcement_count": 9},
                },
                {
                    "id": "memory-mid",
                    "summary": "Medium importance",
                    "created_at": datetime.now(UTC),
                    "extra": {"reinforcement_count": 4},
                },
            ]
        }

        results = await memu_memory.recall_by_tags(["test"])

        # Should be sorted by importance (descending)
        assert results[0].id == "memory-high"
        assert results[1].id == "memory-mid"
        assert results[2].id == "memory-low"


class TestMemUMemoryForget:
    """Test forget operation."""

    @pytest.mark.asyncio
    async def test_forget_success(self, memu_memory, mock_memory_service):
        """Test successful memory deletion."""
        result = await memu_memory.forget("memory-1")

        assert result is True
        mock_memory_service.delete_memory_item.assert_called_once_with(
            memory_id="memory-1",
            user=None,
            propagate=True,
        )

    @pytest.mark.asyncio
    async def test_forget_failure(self, memu_memory, mock_memory_service):
        """Test failed memory deletion returns False."""
        mock_memory_service.delete_memory_item.side_effect = Exception("Not found")

        result = await memu_memory.forget("invalid-id")

        assert result is False


class TestMemUMemoryUpdate:
    """Test update operation."""

    @pytest.mark.asyncio
    async def test_update_success(self, memu_memory, mock_memory_service):
        """Test successful memory update."""
        await memu_memory.update("memory-1", "Updated content")

        mock_memory_service.update_memory_item.assert_called_once_with(
            memory_id="memory-1",
            memory_content="Updated content",
            propagate=True,
        )

    @pytest.mark.asyncio
    async def test_update_not_found_raises_keyerror(self, memu_memory, mock_memory_service):
        """Test update raises KeyError when memory not found."""
        mock_memory_service.update_memory_item.return_value = {"memory_item": None}

        with pytest.raises(KeyError, match="Memory item 'invalid-id' not found"):
            await memu_memory.update("invalid-id", "New content")


class TestComputeImportance:
    """Test importance score computation."""

    def test_zero_reinforcements(self):
        """Test importance with zero reinforcements."""
        memu_item = {"extra": {"reinforcement_count": 0}}
        importance = _compute_importance(memu_item)
        assert importance == 0.0

    def test_one_reinforcement(self):
        """Test importance with one reinforcement."""
        memu_item = {"extra": {"reinforcement_count": 1}}
        importance = _compute_importance(memu_item)
        expected = math.log(2) / math.log(10)
        assert abs(importance - expected) < 0.01

    def test_nine_reinforcements(self):
        """Test importance with nine reinforcements (maps to 1.0)."""
        memu_item = {"extra": {"reinforcement_count": 9}}
        importance = _compute_importance(memu_item)
        assert abs(importance - 1.0) < 0.01

    def test_excessive_reinforcements_capped(self):
        """Test importance is capped at 1.0."""
        memu_item = {"extra": {"reinforcement_count": 100}}
        importance = _compute_importance(memu_item)
        assert importance == 1.0

    def test_missing_extra_dict(self):
        """Test importance with missing extra dict."""
        memu_item = {}
        importance = _compute_importance(memu_item)
        assert importance == 0.0

    def test_missing_reinforcement_count(self):
        """Test importance with missing reinforcement count."""
        memu_item = {"extra": {}}
        importance = _compute_importance(memu_item)
        assert importance == 0.0


class TestIntegration:
    """Integration tests for MemU memory backend."""

    @pytest.mark.asyncio
    async def test_full_lifecycle(self, memu_memory, mock_memory_service):
        """Test complete CRUD lifecycle."""
        # Create
        item = MemoryItem(content="Test", tags=["knowledge"])
        memory_id = await memu_memory.remember(item)
        assert memory_id == "test-memory-id-123"

        # Read
        results = await memu_memory.recall("Test")
        assert len(results) > 0

        # Update
        await memu_memory.update(memory_id, "Updated test")

        # Delete
        result = await memu_memory.forget(memory_id)
        assert result is True
