"""Unit tests for ContextWindowManager (RFC-224).

Tests cover:
- estimate_checkpoint_tokens: Token count estimation from checkpoint messages
- estimate_checkpoint_tokens_sync: Sync helper for pre-loaded checkpoints
- should_compact: Threshold comparison logic
- check_and_compact_if_needed: Full flow (estimate → check → compact)
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.core.loop.engine.context_window_manager import (
    ContextCompactionResult,
    ContextWindowManager,
)
from soothe.core.loop.state.schemas import LoopState


class MockCheckpoint:
    """Mock checkpoint for testing token estimation."""

    def __init__(self, messages: list) -> None:
        self.channel_values = {"messages": messages}


class MockMessage:
    """Mock message for testing token estimation."""

    def __init__(self, content: str) -> None:
        self.content = content


class MockConfig:
    """Mock SootheConfig for testing threshold settings."""

    def __init__(
        self,
        context_limit: int = 200_000,
        threshold_pct: float = 0.80,
        target_pct: float = 0.60,
    ) -> None:
        self.agent = MagicMock()
        self.agent.loop = MagicMock()
        self.agent.loop.context_window_limit = context_limit
        self.agent.loop.context_overflow_threshold_pct = threshold_pct
        self.agent.loop.context_compaction_target_pct = target_pct


class TestEstimateCheckpointTokensSync:
    """Tests for estimate_checkpoint_tokens_sync method."""

    def test_empty_checkpoint_returns_0(self) -> None:
        """Empty checkpoint → 0 tokens."""
        manager = ContextWindowManager(None, None)
        checkpoint = MockCheckpoint(messages=[])

        result = manager.estimate_checkpoint_tokens_sync(checkpoint)
        assert result == 0

    def test_no_channel_values_returns_0(self) -> None:
        """Checkpoint without channel_values → 0 tokens."""
        manager = ContextWindowManager(None, None)
        checkpoint = MagicMock()
        checkpoint.channel_values = None

        result = manager.estimate_checkpoint_tokens_sync(checkpoint)
        assert result == 0

    def test_string_content_counts_tokens(self) -> None:
        """String message content is counted."""
        manager = ContextWindowManager(None, None)
        messages = [MockMessage(content="Hello world")]
        checkpoint = MockCheckpoint(messages=messages)

        result = manager.estimate_checkpoint_tokens_sync(checkpoint)
        # "Hello world" → ~2-3 tokens depending on tokenizer
        assert result > 0
        assert result < 10  # Sanity check

    def test_list_content_counts_text_blocks(self) -> None:
        """List content with text blocks is counted."""
        manager = ContextWindowManager(None, None)

        class MockMessageWithList:
            content = [{"text": "First block"}, {"text": "Second block"}]

        checkpoint = MockCheckpoint(messages=[MockMessageWithList()])

        result = manager.estimate_checkpoint_tokens_sync(checkpoint)
        # Two short text blocks
        assert result > 0
        assert result < 10

    def test_multiple_messages_summed(self) -> None:
        """Multiple messages are summed."""
        manager = ContextWindowManager(None, None)
        messages = [
            MockMessage(content="First message"),
            MockMessage(content="Second message"),
        ]
        checkpoint = MockCheckpoint(messages=messages)

        result = manager.estimate_checkpoint_tokens_sync(checkpoint)
        # Two messages
        assert result > 0
        assert result >= 4  # At least 2 tokens per short message


class TestShouldCompact:
    """Tests for should_compact method."""

    def test_below_threshold_returns_false(self) -> None:
        """Below threshold → no compaction needed."""
        config = MockConfig(context_limit=200_000, threshold_pct=0.80)
        manager = ContextWindowManager(None, config)

        # 140k tokens < 160k threshold
        result = manager.should_compact(140_000)
        assert result is False

    def test_at_threshold_returns_true(self) -> None:
        """At threshold → compaction needed."""
        config = MockConfig(context_limit=200_000, threshold_pct=0.80)
        manager = ContextWindowManager(None, config)

        # 160k tokens >= 160k threshold (80%)
        result = manager.should_compact(160_000)
        assert result is True

    def test_above_threshold_returns_true(self) -> None:
        """Above threshold → compaction needed."""
        config = MockConfig(context_limit=200_000, threshold_pct=0.80)
        manager = ContextWindowManager(None, config)

        # 180k tokens > 160k threshold
        result = manager.should_compact(180_000)
        assert result is True

    def test_no_config_uses_defaults(self) -> None:
        """No config → use default threshold (80%)."""
        manager = ContextWindowManager(None, None)

        # Default: 200k limit, 80% threshold = 160k
        result = manager.should_compact(160_000)
        assert result is True

        result = manager.should_compact(140_000)
        assert result is False


class TestEstimateCheckpointTokensAsync:
    """Tests for async estimate_checkpoint_tokens method."""

    @pytest.mark.asyncio
    async def test_no_checkpointer_returns_0(self) -> None:
        """No checkpointer → 0 tokens."""
        manager = ContextWindowManager(None, None)

        result = await manager.estimate_checkpoint_tokens("thread1")
        assert result == 0

    @pytest.mark.asyncio
    async def test_no_checkpoint_tuple_returns_0(self) -> None:
        """No checkpoint for thread → 0 tokens."""
        mock_checkpointer = AsyncMock()
        mock_checkpointer.aget_tuple = AsyncMock(return_value=None)
        manager = ContextWindowManager(mock_checkpointer, None)

        result = await manager.estimate_checkpoint_tokens("thread1")
        assert result == 0

    @pytest.mark.asyncio
    async def test_returns_sync_estimation(self) -> None:
        """Async method delegates to sync helper."""
        mock_checkpointer = AsyncMock()
        messages = [MockMessage(content="Test message")]
        checkpoint = MockCheckpoint(messages=messages)
        checkpoint_tuple = MagicMock()
        checkpoint_tuple.checkpoint = checkpoint
        mock_checkpointer.aget_tuple = AsyncMock(return_value=checkpoint_tuple)
        manager = ContextWindowManager(mock_checkpointer, None)

        result = await manager.estimate_checkpoint_tokens("thread1")
        assert result > 0


class TestCheckAndCompactIfNeeded:
    """Tests for check_and_compact_if_needed method."""

    @pytest.mark.asyncio
    async def test_below_threshold_returns_none(self) -> None:
        """Below threshold → None (no compaction)."""
        config = MockConfig(context_limit=200_000, threshold_pct=0.80)
        mock_checkpointer = AsyncMock()
        messages = [MockMessage(content="Short message")]  # ~2 tokens
        checkpoint = MockCheckpoint(messages=messages)
        checkpoint_tuple = MagicMock()
        checkpoint_tuple.checkpoint = checkpoint
        mock_checkpointer.aget_tuple = AsyncMock(return_value=checkpoint_tuple)
        manager = ContextWindowManager(mock_checkpointer, config)
        state = LoopState(thread_id="thread1", goal="test goal")

        result = await manager.check_and_compact_if_needed("thread1", state)
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_checkpoint_returns_none(self) -> None:
        """Empty checkpoint → None."""
        manager = ContextWindowManager(None, None)
        state = LoopState(thread_id="thread1", goal="test goal")

        result = await manager.check_and_compact_if_needed("thread1", state)
        assert result is None

    @pytest.mark.asyncio
    async def test_compaction_pending_returns_none(self) -> None:
        """Compaction not implemented yet → logs warning, returns None.

        Note: Full compaction implementation pending SummarizationMiddleware
        API verification (RFC-224 Phase 3).
        """
        config = MockConfig(context_limit=100, threshold_pct=0.80)
        mock_checkpointer = AsyncMock()
        # Create large message to exceed threshold
        large_content = "x" * 500  # ~125 tokens
        messages = [MockMessage(content=large_content)]
        checkpoint = MockCheckpoint(messages=messages)
        checkpoint_tuple = MagicMock()
        checkpoint_tuple.checkpoint = checkpoint
        mock_checkpointer.aget_tuple = AsyncMock(return_value=checkpoint_tuple)
        manager = ContextWindowManager(mock_checkpointer, config)
        state = LoopState(thread_id="thread1", goal="test goal")

        result = await manager.check_and_compact_if_needed("thread1", state)
        # Compaction placeholder returns None
        assert result is None


class TestCompactCheckpointInplace:
    """Tests for compact_checkpoint_inplace method."""

    @pytest.mark.asyncio
    async def test_no_checkpointer_returns_none(self) -> None:
        """No checkpointer → None."""
        manager = ContextWindowManager(None, None)
        state = LoopState(thread_id="thread1", goal="test goal")

        result = await manager.compact_checkpoint_inplace("thread1", state)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_checkpoint_returns_none(self) -> None:
        """No checkpoint for thread → None."""
        mock_checkpointer = AsyncMock()
        mock_checkpointer.aget_tuple = AsyncMock(return_value=None)
        manager = ContextWindowManager(mock_checkpointer, None)
        state = LoopState(thread_id="thread1", goal="test goal")

        result = await manager.compact_checkpoint_inplace("thread1", state)
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_messages_returns_none(self) -> None:
        """Empty messages → None."""
        mock_checkpointer = AsyncMock()
        checkpoint = MockCheckpoint(messages=[])
        checkpoint_tuple = MagicMock()
        checkpoint_tuple.checkpoint = checkpoint
        mock_checkpointer.aget_tuple = AsyncMock(return_value=checkpoint_tuple)
        manager = ContextWindowManager(mock_checkpointer, None)
        state = LoopState(thread_id="thread1", goal="test goal")

        result = await manager.compact_checkpoint_inplace("thread1", state)
        assert result is None


class TestContextCompactionResult:
    """Tests for ContextCompactionResult dataclass."""

    def test_basic_result(self) -> None:
        """Basic result with required fields."""
        result = ContextCompactionResult(
            thread_id="thread1",
            tokens_before=180_000,
            tokens_after=120_000,
            messages_removed=50,
        )

        assert result.thread_id == "thread1"
        assert result.tokens_before == 180_000
        assert result.tokens_after == 120_000
        assert result.messages_removed == 50
        assert result.summary_preview is None

    def test_result_with_summary(self) -> None:
        """Result with summary preview."""
        result = ContextCompactionResult(
            thread_id="thread1",
            tokens_before=180_000,
            tokens_after=120_000,
            messages_removed=50,
            summary_preview="Compacted 50 messages...",
        )

        assert result.summary_preview == "Compacted 50 messages..."

    def test_frozen_dataclass(self) -> None:
        """Result is frozen (immutable)."""
        result = ContextCompactionResult(
            thread_id="thread1",
            tokens_before=180_000,
            tokens_after=120_000,
            messages_removed=50,
        )

        with pytest.raises(Exception):  # FrozenInstanceError
            result.tokens_after = 100_000  # type: ignore[misc]
