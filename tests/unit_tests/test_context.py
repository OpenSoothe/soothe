"""Tests for context implementations (KeywordContext and VectorContext)."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from soothe.context.keyword import KeywordContext
from soothe.protocols.context import ContextEntry, ContextProjection


class TestKeywordContext:
    """Unit tests for KeywordContext."""

    def test_initialization_without_persistence(self):
        """Test that KeywordContext initializes without persistence."""
        context = KeywordContext(persist_dir=None)

        assert context.entries == []
        assert context._store is None

    def test_initialization_with_json_persistence(self, tmp_path: Path):
        """Test that KeywordContext initializes with JSON persistence."""
        context = KeywordContext(persist_dir=str(tmp_path), persist_backend="json")

        assert context.entries == []
        assert context._store is not None

    def test_entries_property_returns_copy(self):
        """Test that entries property returns a copy of the list."""
        context = KeywordContext()
        entry = ContextEntry(source="test", content="content")

        context._entries.append(entry)
        entries = context.entries

        assert len(entries) == 1
        assert entries[0] == entry

        # Modify returned list should not affect internal state
        entries.clear()
        assert len(context.entries) == 1

    @pytest.mark.asyncio
    async def test_ingest_adds_entry(self):
        """Test that ingest adds an entry to the ledger."""
        context = KeywordContext()
        entry = ContextEntry(source="test", content="test content")

        await context.ingest(entry)

        assert len(context.entries) == 1
        assert context.entries[0] == entry

    @pytest.mark.asyncio
    async def test_project_empty_ledger(self):
        """Test projection on empty ledger returns empty projection."""
        context = KeywordContext()

        projection = await context.project("test query", token_budget=1000)

        assert projection.entries == []
        assert projection.total_entries == 0
        assert projection.token_count == 0
        assert projection.summary is None

    @pytest.mark.asyncio
    async def test_project_with_entries(self):
        """Test projection with entries returns relevant entries."""
        context = KeywordContext()

        # Add entries with different relevance
        entry1 = ContextEntry(source="test", content="python programming language")
        entry2 = ContextEntry(source="test", content="java programming language")
        entry3 = ContextEntry(source="test", content="cooking recipes")

        await context.ingest(entry1)
        await context.ingest(entry2)
        await context.ingest(entry3)

        projection = await context.project("python programming", token_budget=1000)

        assert len(projection.entries) > 0
        assert projection.total_entries == 3
        assert projection.token_count > 0

        # Python entry should be ranked higher than cooking
        assert any("python" in e.content for e in projection.entries)

    @pytest.mark.asyncio
    async def test_project_respects_token_budget(self):
        """Test that projection respects token budget."""
        context = KeywordContext()

        # Add entries with different sizes
        for i in range(10):
            content = " ".join(["word"] * 100)  # ~25 tokens each
            entry = ContextEntry(source="test", content=content)
            await context.ingest(entry)

        # Small budget should limit entries
        projection = await context.project("word", token_budget=50)

        # Should not include all entries due to budget
        assert len(projection.entries) < 10
        assert projection.token_count <= 50

    @pytest.mark.asyncio
    async def test_project_for_subagent(self):
        """Test project_for_subagent delegates to project."""
        context = KeywordContext()
        entry = ContextEntry(source="test", content="test content")

        await context.ingest(entry)

        projection = await context.project_for_subagent("goal", token_budget=1000)

        assert isinstance(projection, ContextProjection)
        assert projection.total_entries == 1

    @pytest.mark.asyncio
    async def test_summarize_empty_ledger(self):
        """Test summarize on empty ledger."""
        context = KeywordContext()

        summary = await context.summarize()

        assert "No context entries" in summary

    @pytest.mark.asyncio
    async def test_summarize_with_entries(self):
        """Test summarize with entries."""
        context = KeywordContext()

        for i in range(5):
            entry = ContextEntry(source=f"source_{i}", content=f"content {i}")
            await context.ingest(entry)

        summary = await context.summarize()

        assert "5 entries" in summary
        assert "source_" in summary

    @pytest.mark.asyncio
    async def test_summarize_with_scope_filter(self):
        """Test summarize filters by scope."""
        context = KeywordContext()

        entry1 = ContextEntry(source="test_a", content="content a", tags=["tag_a"])
        entry2 = ContextEntry(source="test_b", content="content b", tags=["tag_b"])

        await context.ingest(entry1)
        await context.ingest(entry2)

        summary = await context.summarize(scope="tag_a")

        # Should only include entries matching scope
        assert "tag_a" in summary or "test_a" in summary

    @pytest.mark.asyncio
    async def test_persist_without_store(self):
        """Test persist does nothing without store."""
        context = KeywordContext(persist_dir=None)

        # Should not raise an error
        await context.persist("thread_123")

    @pytest.mark.asyncio
    async def test_persist_and_restore(self, tmp_path: Path):
        """Test persist and restore with JSON backend."""
        context = KeywordContext(persist_dir=str(tmp_path), persist_backend="json")

        entry = ContextEntry(source="test", content="persisted content")
        await context.ingest(entry)

        await context.persist("thread_123")

        # Create new context and restore
        context2 = KeywordContext(persist_dir=str(tmp_path), persist_backend="json")
        restored = await context2.restore("thread_123")

        assert restored is True
        assert len(context2.entries) == 1
        assert context2.entries[0].content == "persisted content"

    @pytest.mark.asyncio
    async def test_restore_nonexistent_thread(self, tmp_path: Path):
        """Test restore returns False for nonexistent thread."""
        context = KeywordContext(persist_dir=str(tmp_path), persist_backend="json")

        restored = await context.restore("nonexistent")

        assert restored is False

    @pytest.mark.asyncio
    async def test_restore_handles_corrupted_data(self, tmp_path: Path):
        """Test restore handles corrupted data gracefully."""
        context = KeywordContext(persist_dir=str(tmp_path), persist_backend="json")

        # Write invalid data

        data_file = tmp_path / "context_thread_123.json"
        data_file.write_text("invalid json {{{")

        restored = await context.restore("thread_123")

        assert restored is False

    def test_score_entries_keyword_overlap(self):
        """Test that scoring gives higher scores to keyword matches."""
        context = KeywordContext()

        entry1 = ContextEntry(source="test", content="python programming")
        entry2 = ContextEntry(source="test", content="cooking recipes")

        context._entries = [entry1, entry2]

        scored = context._score_entries("python")

        # First entry should have higher score
        assert scored[0][0] > scored[1][0]
        assert "python" in scored[0][1].content

    def test_score_entries_recency_boost(self):
        """Test that scoring includes recency boost."""
        context = KeywordContext()

        # Add multiple entries with same keywords
        for i in range(3):
            entry = ContextEntry(source="test", content="programming language")
            context._entries.append(entry)

        scored = context._score_entries("programming")

        # More recent entries should have higher scores
        assert scored[-1][0] < scored[0][0]

    def test_score_entries_importance_weight(self):
        """Test that scoring includes importance weight."""
        context = KeywordContext()

        entry1 = ContextEntry(source="test", content="programming", importance=0.1)
        entry2 = ContextEntry(source="test", content="programming", importance=0.9)

        context._entries = [entry1, entry2]

        scored = context._score_entries("programming")

        # Higher importance should have higher score
        assert scored[0][1].importance > scored[1][1].importance

    def test_select_within_budget(self):
        """Test selection within token budget."""
        context = KeywordContext()

        entries = [
            ContextEntry(source="test", content=" ".join(["word"] * 10)),  # ~2 tokens
            ContextEntry(source="test", content=" ".join(["word"] * 20)),  # ~5 tokens
            ContextEntry(source="test", content=" ".join(["word"] * 40)),  # ~10 tokens
        ]

        scored = [(1.0, entries[0]), (0.9, entries[1]), (0.8, entries[2])]

        selected, token_count = context._select_within_budget(scored, token_budget=10)

        # Should select entries that fit in budget
        assert token_count <= 10


class TestVectorContext:
    """Unit tests for VectorContext."""

    @pytest.fixture
    def mock_vector_store(self):
        """Create a mock vector store."""
        store = AsyncMock()
        store.search = AsyncMock(return_value=[])
        store.insert = AsyncMock()
        store.list_records = AsyncMock(return_value=[])
        return store

    @pytest.fixture
    def mock_embeddings(self):
        """Create a mock embeddings model."""
        embeddings = AsyncMock()
        embeddings.aembed_documents = AsyncMock(return_value=[[0.1] * 768])
        embeddings.aembed_query = AsyncMock(return_value=[0.1] * 768)
        return embeddings

    def test_initialization(self, mock_vector_store, mock_embeddings):
        """Test VectorContext initialization."""
        from soothe.context.vector_context import VectorContext

        context = VectorContext(mock_vector_store, mock_embeddings)

        assert context.entries == []
        assert context._store == mock_vector_store
        assert context._embeddings == mock_embeddings

    @pytest.mark.asyncio
    async def test_ingest_embeds_and_stores(self, mock_vector_store, mock_embeddings):
        """Test that ingest embeds content and stores in vector store."""
        from soothe.context.vector_context import VectorContext

        context = VectorContext(mock_vector_store, mock_embeddings)

        entry = ContextEntry(source="test", content="test content")
        await context.ingest(entry)

        # Should embed the content
        mock_embeddings.aembed_documents.assert_called_once_with([entry.content])

        # Should insert into vector store
        mock_vector_store.insert.assert_called_once()

        # Should add to in-memory cache
        assert len(context.entries) == 1
        assert context.entries[0] == entry

    @pytest.mark.asyncio
    async def test_project_empty_ledger(self, mock_vector_store, mock_embeddings):
        """Test projection on empty ledger."""
        from soothe.context.vector_context import VectorContext

        context = VectorContext(mock_vector_store, mock_embeddings)

        projection = await context.project("test query", token_budget=1000)

        assert projection.entries == []
        assert projection.total_entries == 0
        assert projection.token_count == 0

    @pytest.mark.asyncio
    async def test_project_with_results(self, mock_vector_store, mock_embeddings):
        """Test projection with vector search results."""
        from soothe.context.vector_context import VectorContext
        from soothe.protocols.vector_store import VectorRecord

        # Mock search results
        entry1 = ContextEntry(source="test", content="python programming")
        entry2 = ContextEntry(source="test", content="java programming")

        mock_vector_store.search = AsyncMock(
            return_value=[
                VectorRecord(
                    id="1",
                    payload=entry1.model_dump(mode="json"),
                    score=0.9,
                ),
                VectorRecord(
                    id="2",
                    payload=entry2.model_dump(mode="json"),
                    score=0.8,
                ),
            ]
        )

        context = VectorContext(mock_vector_store, mock_embeddings)
        context._entries = [entry1, entry2]  # Pre-populate cache

        projection = await context.project("programming", token_budget=1000)

        assert len(projection.entries) > 0
        assert projection.total_entries == 2

        # Should have called search with embedded query
        mock_embeddings.aembed_query.assert_called_once_with("programming")

    @pytest.mark.asyncio
    async def test_project_respects_token_budget(self, mock_vector_store, mock_embeddings):
        """Test that projection respects token budget."""
        from soothe.context.vector_context import VectorContext
        from soothe.protocols.vector_store import VectorRecord

        # Create large entries
        entries = [ContextEntry(source="test", content=" ".join(["word"] * 100)) for _ in range(5)]

        mock_vector_store.search = AsyncMock(
            return_value=[
                VectorRecord(id=str(i), payload=e.model_dump(mode="json"), score=0.9) for i, e in enumerate(entries)
            ]
        )

        context = VectorContext(mock_vector_store, mock_embeddings)
        context._entries = entries

        projection = await context.project("query", token_budget=50)

        # Should limit entries due to budget
        assert projection.token_count <= 50

    @pytest.mark.asyncio
    async def test_project_handles_invalid_payload(self, mock_vector_store, mock_embeddings):
        """Test that projection handles invalid payloads gracefully."""
        from soothe.context.vector_context import VectorContext
        from soothe.protocols.vector_store import VectorRecord

        # Mock results with invalid payload
        mock_vector_store.search = AsyncMock(
            return_value=[
                VectorRecord(id="1", payload={"invalid": "data"}, score=0.9),
                VectorRecord(id="2", payload={}, score=0.8),
            ]
        )

        context = VectorContext(mock_vector_store, mock_embeddings)

        # Should not raise an error
        projection = await context.project("query", token_budget=1000)

        assert isinstance(projection, ContextProjection)

    @pytest.mark.asyncio
    async def test_project_for_subagent(self, mock_vector_store, mock_embeddings):
        """Test project_for_subagent delegates to project."""
        from soothe.context.vector_context import VectorContext

        context = VectorContext(mock_vector_store, mock_embeddings)

        projection = await context.project_for_subagent("goal", token_budget=1000)

        assert isinstance(projection, ContextProjection)

    @pytest.mark.asyncio
    async def test_summarize_empty_ledger(self, mock_vector_store, mock_embeddings):
        """Test summarize on empty ledger."""
        from soothe.context.vector_context import VectorContext

        context = VectorContext(mock_vector_store, mock_embeddings)

        summary = await context.summarize()

        assert "No context entries" in summary

    @pytest.mark.asyncio
    async def test_summarize_with_entries(self, mock_vector_store, mock_embeddings):
        """Test summarize with cached entries."""
        from soothe.context.vector_context import VectorContext

        context = VectorContext(mock_vector_store, mock_embeddings)

        for i in range(5):
            entry = ContextEntry(source=f"source_{i}", content=f"content {i}")
            context._entries.append(entry)

        summary = await context.summarize()

        assert "5 entries" in summary

    @pytest.mark.asyncio
    async def test_summarize_with_scope(self, mock_vector_store, mock_embeddings):
        """Test summarize with scope filter."""
        from soothe.context.vector_context import VectorContext

        context = VectorContext(mock_vector_store, mock_embeddings)

        entry1 = ContextEntry(source="test_a", content="content a", tags=["tag_a"])
        entry2 = ContextEntry(source="test_b", content="content b", tags=["tag_b"])

        context._entries = [entry1, entry2]

        summary = await context.summarize(scope="tag_a")

        # Should filter by scope
        assert "tag_a" in summary or "test_a" in summary

    @pytest.mark.asyncio
    async def test_persist_is_noop(self, mock_vector_store, mock_embeddings):
        """Test that persist is a no-op for vector context."""
        from soothe.context.vector_context import VectorContext

        context = VectorContext(mock_vector_store, mock_embeddings)

        # Should not raise an error
        await context.persist("thread_123")

    @pytest.mark.asyncio
    async def test_restore_from_vector_store(self, mock_vector_store, mock_embeddings):
        """Test restore loads entries from vector store."""
        from soothe.context.vector_context import VectorContext
        from soothe.protocols.vector_store import VectorRecord

        entry1 = ContextEntry(source="test", content="content 1")
        entry2 = ContextEntry(source="test", content="content 2")

        mock_vector_store.list_records = AsyncMock(
            return_value=[
                VectorRecord(id="1", payload=entry1.model_dump(mode="json")),
                VectorRecord(id="2", payload=entry2.model_dump(mode="json")),
            ]
        )

        context = VectorContext(mock_vector_store, mock_embeddings)

        restored = await context.restore("thread_123")

        assert restored is True
        assert len(context.entries) == 2

    @pytest.mark.asyncio
    async def test_restore_handles_errors(self, mock_vector_store, mock_embeddings):
        """Test restore handles errors gracefully."""
        from soothe.context.vector_context import VectorContext

        mock_vector_store.list_records = AsyncMock(side_effect=Exception("DB error"))

        context = VectorContext(mock_vector_store, mock_embeddings)

        restored = await context.restore("thread_123")

        assert restored is False
