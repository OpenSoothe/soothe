"""Unit tests for ClaudeCoreAgent."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from soothe.config import SootheConfig
from soothe.foundation.core.agent.claude_core_agent import ClaudeCoreAgent, _resolve_claude_cwd


@pytest.fixture
def config():
    """Create a test SootheConfig."""
    return SootheConfig()


@pytest.fixture
def claude_agent(config):
    """Create a ClaudeCoreAgent instance."""
    return ClaudeCoreAgent(
        config=config,
        model="sonnet",
        system_prompt="Test system prompt",
        permission_mode="bypassPermissions",
        max_turns=10,
        cwd="/tmp/test",
    )


class TestClaudeCoreAgentInit:
    """Test ClaudeCoreAgent initialization."""

    def test_init_with_defaults(self, config):
        """Test initialization with default values."""
        agent = ClaudeCoreAgent(config=config)
        assert agent.config == config
        assert agent._model is None
        assert agent._permission_mode == "bypassPermissions"
        assert agent._max_turns == 25

    def test_init_with_custom_values(self, config):
        """Test initialization with custom values."""
        agent = ClaudeCoreAgent(
            config=config,
            model="opus",
            system_prompt="Custom prompt",
            permission_mode="acceptEdits",
            max_turns=50,
            cwd="/custom/path",
        )
        assert agent._model == "opus"
        assert agent._system_prompt == "Custom prompt"
        assert agent._permission_mode == "acceptEdits"
        assert agent._max_turns == 50
        assert agent._cwd == "/custom/path"


class TestClaudeCoreAgentProperties:
    """Test ClaudeCoreAgent properties."""

    def test_graph_property_raises(self, claude_agent):
        """Test that graph property raises NotImplementedError."""
        with pytest.raises(NotImplementedError, match="ClaudeCoreAgent uses claude-agent-sdk"):
            _ = claude_agent.graph

    def test_config_property(self, claude_agent, config):
        """Test config property returns correct config."""
        assert claude_agent.config == config

    def test_memory_property(self, claude_agent):
        """Test memory property."""
        assert claude_agent.memory is None

    def test_planner_property(self, claude_agent):
        """Test planner property."""
        assert claude_agent.planner is None

    def test_policy_property(self, claude_agent):
        """Test policy property."""
        assert claude_agent.policy is None

    def test_subagents_property(self, claude_agent):
        """Test subagents property returns empty list."""
        assert claude_agent.subagents == []


class TestClaudeCoreAgentCreate:
    """Test ClaudeCoreAgent.create factory method."""

    def test_create_with_defaults(self, config):
        """Test create with default values."""
        agent = ClaudeCoreAgent.create(config)
        assert isinstance(agent, ClaudeCoreAgent)
        assert agent.config == config

    def test_create_with_kwargs(self, config):
        """Test create with kwargs."""
        agent = ClaudeCoreAgent.create(
            config,
            model="haiku",
            system_prompt="Factory prompt",
            permission_mode="plan",
            max_turns=30,
        )
        assert agent._model == "haiku"
        assert agent._system_prompt == "Factory prompt"
        assert agent._permission_mode == "plan"
        assert agent._max_turns == 30


class TestClaudeCoreAgentHelpers:
    """Test ClaudeCoreAgent helper methods."""

    def test_resolve_thread_id_none(self, claude_agent):
        """Test _resolve_thread_id with None config."""
        assert claude_agent._resolve_thread_id(None) is None

    def test_resolve_thread_id_empty(self, claude_agent):
        """Test _resolve_thread_id with empty config."""
        assert claude_agent._resolve_thread_id({}) is None

    def test_resolve_thread_id_present(self, claude_agent):
        """Test _resolve_thread_id with thread_id."""
        config = {"configurable": {"thread_id": "test-thread-123"}}
        assert claude_agent._resolve_thread_id(config) == "test-thread-123"

    def test_resolve_cwd_default(self, claude_agent):
        """Test _resolve_claude_cwd with no workspace."""
        result = _resolve_claude_cwd(None, claude_agent._cwd)
        assert result.endswith("test")

    def test_resolve_cwd_from_config(self, claude_agent):
        """Test _resolve_claude_cwd from config."""
        config = {"configurable": {"workspace": "/workspace/path"}}
        result = _resolve_claude_cwd(config, claude_agent._cwd)
        assert "workspace" in result or "path" in result

    def test_extract_user_text_string(self, claude_agent):
        """Test _extract_user_text with string input."""
        assert claude_agent._extract_user_text("Hello world") == "Hello world"

    def test_extract_user_text_dict_with_human_message(self, claude_agent):
        """Test _extract_user_text with dict containing HumanMessage."""
        messages = [HumanMessage(content="Test message")]
        result = claude_agent._extract_user_text({"messages": messages})
        assert result == "Test message"

    def test_extract_user_text_dict_empty(self, claude_agent):
        """Test _extract_user_text with empty dict."""
        assert claude_agent._extract_user_text({}) == ""

    def test_extract_user_text_dict_fallback(self, claude_agent):
        """Test _extract_user_text fallback to last message."""
        messages = [AIMessage(content="AI message")]
        result = claude_agent._extract_user_text({"messages": messages})
        assert result == "AI message"


class TestClaudeCoreAgentStreamConversion:
    """Test ClaudeCoreAgent stream conversion methods."""

    def test_emit_text_chunks_no_mode(self, claude_agent):
        """Test _emit_text_chunks with no stream_mode."""
        chunks = list(claude_agent._emit_text_chunks("text", None, "thread-1"))
        assert chunks == []

    def test_emit_text_chunks_messages_mode(self, claude_agent):
        """Test _emit_text_chunks with messages mode."""
        chunks = list(claude_agent._emit_text_chunks("text", ["messages"], "thread-1"))
        assert len(chunks) == 1
        metadata, chunk = chunks[0]
        assert metadata["langgraph_node"] == "agent"
        assert metadata["thread_id"] == "thread-1"
        assert chunk.content == "text"

    def test_emit_tool_use_chunks_no_mode(self, claude_agent):
        """Test _emit_tool_use_chunks with no stream_mode."""
        block = MagicMock()
        block.name = "test_tool"
        block.input = {"arg": "value"}
        chunks = list(claude_agent._emit_tool_use_chunks(block, None, "thread-1"))
        assert chunks == []

    def test_emit_tool_use_chunks_custom_mode(self, claude_agent):
        """Test _emit_tool_use_chunks with custom mode."""
        block = MagicMock()
        block.name = "test_tool"
        block.input = {"arg": "value"}
        chunks = list(claude_agent._emit_tool_use_chunks(block, ["custom"], "thread-1"))
        assert len(chunks) == 1
        assert chunks[0]["event"] == "tool_use"
        assert chunks[0]["tool"] == "test_tool"
        assert chunks[0]["input"] == {"arg": "value"}
        assert chunks[0]["thread_id"] == "thread-1"


class TestClaudeCoreAgentAstream:
    """Test ClaudeCoreAgent.astream method."""

    @pytest.mark.asyncio
    async def test_astream_basic(self, claude_agent):
        """Test basic astream execution."""
        # Mock claude-agent-sdk imports - patch at the source module
        with patch("claude_agent_sdk.query") as mock_query:
            # Setup mock stream
            mock_stream = AsyncMock()
            mock_stream.__aenter__.return_value = mock_stream
            mock_stream.__aexit__.return_value = None

            # Mock AssistantMessage with TextBlock
            from claude_agent_sdk import AssistantMessage, TextBlock

            mock_message = AssistantMessage(
                content=[TextBlock(text="Response text")],
                model="claude-sonnet-4-6",
                session_id="test-session-123",
            )
            mock_stream.__aiter__.return_value = [mock_message]

            mock_query.return_value = mock_stream

            # Mock session bridge functions
            with patch(
                "soothe.foundation.core.agent.claude_core_agent.resolve_resume_session_id",
                new_callable=AsyncMock,
                return_value=None,
            ):
                with patch(
                    "soothe.foundation.core.agent.claude_core_agent.record_claude_session",
                    new_callable=AsyncMock,
                ):
                    # Execute astream
                    chunks = []
                    async for chunk in claude_agent.astream(
                        "Test input",
                        {"configurable": {"thread_id": "test-123"}},
                        stream_mode=["messages"],
                    ):
                        chunks.append(chunk)

                    # Verify we got chunks
                    assert len(chunks) > 0

    @pytest.mark.asyncio
    async def test_astream_error_handling(self, claude_agent):
        """Test astream error handling."""
        with patch("claude_agent_sdk.query") as mock_query:
            # Mock stream that raises exception
            mock_stream = AsyncMock()
            mock_stream.__aenter__.return_value = mock_stream
            mock_stream.__aexit__.return_value = None
            mock_stream.__aiter__.side_effect = Exception("Test error")

            mock_query.return_value = mock_stream

            with patch(
                "soothe.foundation.core.agent.claude_core_agent.resolve_resume_session_id",
                new_callable=AsyncMock,
                return_value=None,
            ):
                with patch(
                    "soothe.foundation.core.agent.claude_core_agent.record_claude_session",
                    new_callable=AsyncMock,
                ):
                    # Execute astream - should not raise
                    chunks = []
                    async for chunk in claude_agent.astream("Test input"):
                        chunks.append(chunk)

                    # Should complete without error
