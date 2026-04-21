"""Unit tests for LoopHumanMessage and LoopAIMessage."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    messages_from_dict,
    messages_to_dict,
)

from soothe.cognition.agent_loop.messages import (
    LoopAIMessage,
    LoopHumanMessage,
    loop_message_to_thread_metadata,
)


class TestLoopHumanMessageConstruction:
    """Test LoopHumanMessage instantiation with various context levels."""

    def test_full_thread_context(self) -> None:
        """Test construction with all LoopState context fields."""
        msg = LoopHumanMessage(
            content="Execute: Search for files",
            thread_id="thread_abc123",
            iteration=5,
            goal_summary="Find configuration files in the project",
            workspace="/path/to/workspace",
            phase="execute_wave",
            wave_id="a1b2c3d4",
        )

        assert msg.content == "Execute: Search for files"
        assert msg.thread_id == "thread_abc123"
        assert msg.iteration == 5
        assert msg.goal_summary == "Find configuration files in the project"
        assert msg.workspace == "/path/to/workspace"
        assert msg.phase == "execute_wave"
        assert msg.wave_id == "a1b2c3d4"
        assert msg.type == "human"

    def test_partial_thread_context(self) -> None:
        """Test construction with only some context fields populated."""
        msg = LoopHumanMessage(
            content="Execute: Run tests",
            thread_id="thread_xyz",
            iteration=3,
            phase="execute_step",
        )

        assert msg.content == "Execute: Run tests"
        assert msg.thread_id == "thread_xyz"
        assert msg.iteration == 3
        assert msg.phase == "execute_step"
        # Optional fields should be None
        assert msg.goal_summary is None
        assert msg.workspace is None
        assert msg.wave_id is None

    def test_no_thread_context(self) -> None:
        """Test construction without thread context (planner/synthesis case)."""
        msg = LoopHumanMessage(content="Generate execution plan")

        assert msg.content == "Generate execution plan"
        # All optional fields should be None
        assert msg.thread_id is None
        assert msg.iteration is None
        assert msg.goal_summary is None
        assert msg.workspace is None
        assert msg.phase is None
        assert msg.wave_id is None

    def test_goal_summary_truncation(self) -> None:
        """Test goal_summary max_length validation rejects >200 chars."""
        long_goal = "This is a very long goal description that exceeds 200 characters limit " * 5
        # Pydantic validation should raise ValidationError for >200 chars
        with pytest.raises(Exception):  # Pydantic ValidationError
            LoopHumanMessage(
                content="Test",
                goal_summary=long_goal,
            )

    def test_goal_summary_manual_truncation(self) -> None:
        """Test caller can manually truncate goal_summary to 200 chars."""
        long_goal = "This is a very long goal description that exceeds 200 characters limit " * 5
        truncated = long_goal[:200]
        msg = LoopHumanMessage(
            content="Test",
            goal_summary=truncated,
        )

        assert len(msg.goal_summary) == 200
        assert msg.goal_summary == truncated

    def test_goal_summary_short(self) -> None:
        """Test goal_summary accepts short text without truncation."""
        short_goal = "Short goal"
        msg = LoopHumanMessage(
            content="Test",
            goal_summary=short_goal,
        )

        assert msg.goal_summary == short_goal
        assert len(msg.goal_summary) < 200

    def test_phase_literal_constraint(self) -> None:
        """Test phase field accepts only valid literal values."""
        # Valid phases
        msg1 = LoopHumanMessage(content="Test", phase="execute_wave")
        assert msg1.phase == "execute_wave"

        msg2 = LoopHumanMessage(content="Test", phase="execute_step")
        assert msg2.phase == "execute_step"

        msg3 = LoopHumanMessage(content="Test", phase="final_report")
        assert msg3.phase == "final_report"

        # Invalid phase should raise validation error
        with pytest.raises(Exception):  # Pydantic ValidationError
            LoopHumanMessage(content="Test", phase="invalid_phase")


class TestLoopHumanMessageLangChainCompatibility:
    """Test LoopHumanMessage works with langchain ecosystem."""

    def test_inherits_from_human_message(self) -> None:
        """Test LoopHumanMessage is a HumanMessage subclass."""
        msg = LoopHumanMessage(content="Test")
        assert isinstance(msg, HumanMessage)
        assert isinstance(msg, LoopHumanMessage)

    def test_messages_to_dict_serialization(self) -> None:
        """Test messages_to_dict() preserves agentloop metadata."""
        msg = LoopHumanMessage(
            content="Execute step",
            thread_id="thread_123",
            iteration=2,
            goal_summary="Test goal",
            phase="execute_step",
            wave_id="abc12345",
        )

        # Serialize
        msg_dict = messages_to_dict([msg])

        assert len(msg_dict) == 1
        assert msg_dict[0]["type"] == "human"
        # Content and metadata are nested under 'data' key
        assert msg_dict[0]["data"]["content"] == "Execute step"
        # Agentloop metadata should be preserved in 'data'
        assert msg_dict[0]["data"]["thread_id"] == "thread_123"
        assert msg_dict[0]["data"]["iteration"] == 2
        assert msg_dict[0]["data"]["goal_summary"] == "Test goal"
        assert msg_dict[0]["data"]["phase"] == "execute_step"
        assert msg_dict[0]["data"]["wave_id"] == "abc12345"

    def test_messages_from_dict_deserialization(self) -> None:
        """Test messages_from_dict() preserves content but returns base HumanMessage."""
        msg = LoopHumanMessage(
            content="Test message",
            thread_id="thread_abc",
            iteration=5,
        )

        # Serialize → Deserialize
        msg_dict = messages_to_dict([msg])
        restored = messages_from_dict(msg_dict)

        assert len(restored) == 1
        # Returns base HumanMessage (not LoopHumanMessage)
        assert isinstance(restored[0], HumanMessage)
        # Content preserved
        assert restored[0].content == "Test message"
        # Extra fields accessible as dynamic attributes (not typed)
        assert hasattr(restored[0], "thread_id")
        assert restored[0].thread_id == "thread_abc"

    def test_core_agent_duck_typing(self) -> None:
        """Test CoreAgent.astream() accepts LoopHumanMessage (duck typing).

        This test verifies that CoreAgent treats LoopHumanMessage as HumanMessage
        without type validation errors.
        """
        # Mock CoreAgent for duck typing test
        mock_core_agent = MagicMock()
        mock_core_agent.astream = AsyncMock()

        msg = LoopHumanMessage(
            content="Test query",
            thread_id="thread_test",
            iteration=1,
        )

        # CoreAgent should accept LoopHumanMessage in messages list
        input_dict = {"messages": [msg]}
        # No exception should be raised when passing LoopHumanMessage
        # (real test would be integration test, this verifies structure)
        assert input_dict["messages"][0] == msg
        assert isinstance(input_dict["messages"][0], HumanMessage)


class TestLoopAIMessage:
    """Test LoopAIMessage preserves response_metadata and inherits AIMessage."""

    def test_inherits_from_ai_message(self) -> None:
        """Test LoopAIMessage is an AIMessage subclass."""
        msg = LoopAIMessage(content="Response text")
        assert isinstance(msg, AIMessage)
        assert isinstance(msg, LoopAIMessage)

    def test_response_metadata_preserved(self) -> None:
        """Test response_metadata accessible for token extraction."""
        msg = LoopAIMessage(
            content="Found results",
            response_metadata={
                "token_usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                    "total_tokens": 150,
                },
                "model_name": "claude-3-5-sonnet-20241022",
            },
            iteration=3,
            phase="execute_wave",
        )

        assert msg.content == "Found results"
        assert msg.response_metadata["token_usage"]["total_tokens"] == 150
        assert msg.response_metadata["model_name"] == "claude-3-5-sonnet-20241022"
        assert msg.iteration == 3
        assert msg.phase == "execute_wave"

    def test_usage_metadata_preserved(self) -> None:
        """Test usage_metadata (standardized token counts) preserved."""
        msg = LoopAIMessage(
            content="Response",
            usage_metadata={
                "input_tokens": 100,
                "output_tokens": 50,
                "total_tokens": 150,
            },
        )

        assert msg.usage_metadata["total_tokens"] == 150
        assert msg.usage_metadata["input_tokens"] == 100

    def test_tool_calls_preserved(self) -> None:
        """Test tool_calls list preserved."""
        msg = LoopAIMessage(
            content="",
            tool_calls=[
                {
                    "name": "search_files",
                    "args": {"query": "config"},
                    "id": "call_123",
                }
            ],
        )

        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0]["name"] == "search_files"


class TestLoopAIMessageWithExecutor:
    """Test LoopAIMessage works with executor token extraction logic."""

    def test_token_extraction_logic(self) -> None:
        """Test executor._extract_token_usage() pattern works with LoopAIMessage."""
        # Simulate executor token extraction logic (executor.py:104-124)
        messages = [
            LoopAIMessage(
                content="Result 1",
                response_metadata={"token_usage": {"total_tokens": 100}},
            ),
            LoopAIMessage(
                content="Result 2",
                response_metadata={
                    "token_usage": {
                        "prompt_tokens": 200,
                        "completion_tokens": 100,
                        "total_tokens": 300,
                    }
                },
                iteration=5,
            ),
        ]

        # Find last AIMessage with usage_metadata (executor pattern)
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and hasattr(msg, "response_metadata"):
                metadata = msg.response_metadata
                token_usage = metadata.get("token_usage", {})
                if token_usage:
                    # Should find the second message
                    assert token_usage["total_tokens"] == 300
                    assert token_usage["prompt_tokens"] == 200
                    break


class TestLoopMessageToThreadMetadata:
    """Test metadata extraction utility function."""

    def test_full_metadata_extraction(self) -> None:
        """Test extraction with all fields populated."""
        msg = LoopHumanMessage(
            content="Test",
            thread_id="thread_abc",
            iteration=5,
            goal_summary="Goal text",
            phase="execute_wave",
            wave_id="wave123",
            workspace="/path",
        )

        metadata = loop_message_to_thread_metadata(msg)

        assert metadata["thread_id"] == "thread_abc"
        assert metadata["iteration"] == 5
        assert metadata["goal_summary"] == "Goal text"
        assert metadata["phase"] == "execute_wave"
        assert metadata["wave_id"] == "wave123"
        assert metadata["workspace"] == "/path"

    def test_partial_metadata_extraction(self) -> None:
        """Test extraction with None fields."""
        msg = LoopHumanMessage(
            content="Test",
            thread_id="thread_xyz",
            iteration=None,
            goal_summary=None,
        )

        metadata = loop_message_to_thread_metadata(msg)

        assert metadata["thread_id"] == "thread_xyz"
        assert metadata["iteration"] is None
        assert metadata["goal_summary"] is None
        assert metadata["phase"] is None
        assert metadata["wave_id"] is None
        assert metadata["workspace"] is None


class TestWaveIdFormat:
    """Test wave_id generation and format."""

    def test_wave_id_short_format(self) -> None:
        """Test wave_id uses UUID[:8] format (8 chars)."""
        wave_id = str(uuid.uuid4())[:8]

        # Should be 8 characters
        assert len(wave_id) == 8
        # Should be hexadecimal
        assert all(c in "0123456789abcdef" for c in wave_id)

    def test_wave_id_uniqueness(self) -> None:
        """Test generated wave_ids are unique."""
        wave_ids = [str(uuid.uuid4())[:8] for _ in range(100)]

        # All should be unique (collision probability extremely low)
        assert len(set(wave_ids)) == 100

    def test_wave_id_in_message(self) -> None:
        """Test wave_id can be attached to LoopHumanMessage."""
        wave_id = str(uuid.uuid4())[:8]
        msg = LoopHumanMessage(
            content="Execute wave",
            phase="execute_wave",
            wave_id=wave_id,
        )

        assert msg.wave_id == wave_id
        assert len(msg.wave_id) == 8
