"""Unit tests for CoreAgent class (RFC-0023 Layer 1 interface)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from langgraph.graph.state import CompiledStateGraph


# Simple mock for tests
def _mock_graph() -> MagicMock:
    return MagicMock(spec=CompiledStateGraph)


class TestCoreAgentClass:
    """Tests for CoreAgent wrapper class."""

    def test_core_agent_has_typed_properties(self) -> None:
        """CoreAgent exposes typed properties for protocols."""
        from soothe.coreagent import SootheNanoAgent as CoreAgent

        # Create mock graph and protocols
        mock_graph = _mock_graph()
        mock_config = MagicMock()

        # Create CoreAgent with all protocols
        agent = CoreAgent(
            graph=mock_graph,
            config=mock_config,
            memory=MagicMock(),
            planner=MagicMock(),
            policy=MagicMock(),
            subagents=[MagicMock()],
        )

        # Verify properties exist and return correct values
        assert agent.graph is mock_graph
        assert agent.config is mock_config
        assert agent.memory is not None
        assert agent.planner is not None
        assert agent.policy is not None
        assert len(agent.subagents) == 1

    def test_core_agent_handles_none_protocols(self) -> None:
        """CoreAgent handles None protocol values gracefully."""
        from soothe.coreagent import SootheNanoAgent as CoreAgent

        mock_graph = _mock_graph()
        mock_config = MagicMock()

        agent = CoreAgent(
            graph=mock_graph,
            config=mock_config,
            memory=None,
            planner=None,
            policy=None,
            subagents=None,
        )

        assert agent.memory is None
        assert agent.planner is None
        assert agent.policy is None
        assert agent.subagents == []

    @pytest.mark.asyncio
    async def test_core_agent_astream_delegates_to_graph(self) -> None:
        """CoreAgent.astream() delegates to underlying graph."""
        from soothe.coreagent import SootheNanoAgent as CoreAgent

        mock_graph = _mock_graph()

        # Create an async generator for astream to return
        async def mock_astream(input_arg, config, **kwargs):
            yield "chunk1"
            yield "chunk2"

        mock_graph.astream = mock_astream
        mock_config = MagicMock()

        agent = CoreAgent(
            graph=mock_graph,
            config=mock_config,
        )

        # Call astream - it returns an async generator
        result = agent.astream("test input", {"thread_id": "123"})

        # Consume the generator to trigger the call
        chunks = [chunk async for chunk in result]

        assert chunks == ["chunk1", "chunk2"]

    @pytest.mark.asyncio
    async def test_core_agent_astream_with_none_config(self) -> None:
        """CoreAgent.astream() handles None config."""
        from soothe.coreagent import SootheNanoAgent as CoreAgent

        mock_graph = _mock_graph()

        # Track what args were passed
        call_args = []

        async def mock_astream(input_arg, config, **kwargs):
            call_args.append((input_arg, config, kwargs))
            yield "chunk"

        mock_graph.astream = mock_astream
        mock_config = MagicMock()

        agent = CoreAgent(
            graph=mock_graph,
            config=mock_config,
        )

        # Call with None config
        result = agent.astream("test input")

        # Consume the generator
        async for _ in result:
            pass

        # String input is normalized to graph state; config is {} when None; subgraphs=False
        inp, cfg, kw = call_args[0]
        assert cfg == {}
        # durability omitted when unset / no checkpointer (avoids LangGraph warning)
        assert kw == {"subgraphs": False}
        assert isinstance(inp, dict)
        assert len(inp["messages"]) == 1
        assert inp["messages"][0].content == "test input"

    def test_create_factory_returns_core_agent(self) -> None:
        """create_soothe_agent() returns CoreAgent instance."""
        from soothe.config import SootheConfig
        from soothe.coreagent import SootheNanoAgent as CoreAgent
        from soothe.coreagent import create_soothe_agent

        with patch("soothe.runner.resolver.resolve_tools", return_value=[]):
            with patch("soothe.runner.resolver.resolve_subagents", return_value=[]):
                with patch("soothe.runner.resolver.resolve_memory", return_value=None):
                    with patch("soothe.runner.resolver.resolve_planner", return_value=None):
                        with patch("soothe.runner.resolver.resolve_policy", return_value=None):
                            with patch("soothe_deepagents.create_deep_agent") as mock_create:
                                mock_graph = _mock_graph()
                                mock_create.return_value = mock_graph

                                config = SootheConfig()
                                mock_model = MagicMock()
                                with patch.object(
                                    SootheConfig,
                                    "create_chat_model",
                                    return_value=mock_model,
                                ):
                                    agent = create_soothe_agent(config, model=mock_model)

                                assert isinstance(agent, CoreAgent)
                                assert agent.graph is mock_graph
                                assert agent.config is config

    def test_no_goal_engine_in_core_agent(self) -> None:
        """CoreAgent does NOT have goal_engine (Layer 3 responsibility)."""
        from soothe.coreagent import SootheNanoAgent as CoreAgent

        mock_graph = _mock_graph()
        mock_config = MagicMock()

        agent = CoreAgent(
            graph=mock_graph,
            config=mock_config,
        )

        # goal_engine should NOT be an attribute
        assert not hasattr(agent, "_goal_engine")
        assert not hasattr(agent, "goal_engine")

    def test_no_soothe_star_attributes(self) -> None:
        """CoreAgent uses properties, not soothe_* attributes."""
        from soothe.coreagent import SootheNanoAgent as CoreAgent

        mock_graph = _mock_graph()
        mock_config = MagicMock()

        agent = CoreAgent(
            graph=mock_graph,
            config=mock_config,
            memory=MagicMock(),
        )

        # Old soothe_* attributes should NOT exist
        assert not hasattr(agent, "soothe_memory")
        assert not hasattr(agent, "soothe_planner")
        assert not hasattr(agent, "soothe_policy")
        assert not hasattr(agent, "soothe_config")
        assert not hasattr(agent, "soothe_subagents")
        assert not hasattr(agent, "soothe_goal_engine")


class TestCoreAgentStateRetrieval:
    """Tests for checkpointer-aware graph state reads (IG-477 / IG-519)."""

    @pytest.mark.asyncio
    async def test_aget_state_returns_none_without_checkpointer(self) -> None:
        """No checkpointer → None without raising or noisy logs."""
        from soothe.coreagent import SootheNanoAgent as CoreAgent

        mock_graph = _mock_graph()
        mock_graph.checkpointer = None
        agent = CoreAgent(graph=mock_graph, config=MagicMock())

        assert agent.can_read_graph_state is False
        assert await agent.aget_state({"configurable": {"thread_id": "t1"}}) is None
        assert await agent.execution_aget_state({"configurable": {"thread_id": "t1"}}) is None

    @pytest.mark.asyncio
    async def test_execution_aget_state_strips_null_pregel_checkpointer_override(self) -> None:
        """Ephemeral stream config pollution must not block main-graph state reads."""
        from unittest.mock import AsyncMock

        from langgraph._internal._constants import CONFIG_KEY_CHECKPOINTER
        from langgraph.checkpoint.memory import MemorySaver

        from soothe.coreagent import SootheNanoAgent as CoreAgent

        mock_graph = _mock_graph()
        mock_graph.checkpointer = MemorySaver()
        expected = MagicMock(name="state_snapshot")
        mock_graph.aget_state = AsyncMock(return_value=expected)

        agent = CoreAgent(graph=mock_graph, config=MagicMock())
        polluted = {
            "configurable": {
                "thread_id": "t1",
                CONFIG_KEY_CHECKPOINTER: None,
            },
        }

        result = await agent.execution_aget_state(polluted)

        assert result is expected
        call_config = mock_graph.aget_state.await_args.kwargs["config"]
        assert CONFIG_KEY_CHECKPOINTER not in call_config.get("configurable", {})

    @pytest.mark.asyncio
    async def test_execution_aget_state_strips_parent_checkpoint_ns(self) -> None:
        """StrangeLoop node checkpoint_ns must not trigger CoreAgent subgraph lookup."""
        from unittest.mock import AsyncMock

        from langgraph._internal._constants import (
            CONFIG_KEY_CHECKPOINT_ID,
            CONFIG_KEY_CHECKPOINT_MAP,
            CONFIG_KEY_CHECKPOINT_NS,
            CONFIG_KEY_CHECKPOINTER,
        )
        from langgraph.checkpoint.memory import MemorySaver

        from soothe.coreagent import SootheNanoAgent as CoreAgent

        mock_graph = _mock_graph()
        mock_graph.checkpointer = MemorySaver()
        expected = MagicMock(name="state_snapshot")
        mock_graph.aget_state = AsyncMock(return_value=expected)

        agent = CoreAgent(graph=mock_graph, config=MagicMock())
        polluted = {
            "configurable": {
                "thread_id": "t1",
                CONFIG_KEY_CHECKPOINTER: None,
                CONFIG_KEY_CHECKPOINT_NS: "execute:task-abc",
                CONFIG_KEY_CHECKPOINT_ID: "cp-parent",
                CONFIG_KEY_CHECKPOINT_MAP: {"execute": "cp-parent"},
            },
        }

        result = await agent.execution_aget_state(polluted)

        assert result is expected
        call_config = mock_graph.aget_state.await_args.kwargs["config"]
        conf = call_config.get("configurable", {})
        assert CONFIG_KEY_CHECKPOINTER not in conf
        assert CONFIG_KEY_CHECKPOINT_NS not in conf
        assert CONFIG_KEY_CHECKPOINT_ID not in conf
        assert CONFIG_KEY_CHECKPOINT_MAP not in conf
        assert conf.get("thread_id") == "t1"

    @pytest.mark.asyncio
    async def test_execution_aget_state_soft_fails_on_missing_subgraph(self) -> None:
        """Defensive: subgraph lookup miss returns None instead of crashing the step."""
        from unittest.mock import AsyncMock

        from langgraph.checkpoint.memory import MemorySaver

        from soothe.coreagent import SootheNanoAgent as CoreAgent

        mock_graph = _mock_graph()
        mock_graph.checkpointer = MemorySaver()
        mock_graph.aget_state = AsyncMock(side_effect=ValueError("Subgraph execute not found"))

        agent = CoreAgent(graph=mock_graph, config=MagicMock())
        assert await agent.execution_aget_state({"configurable": {"thread_id": "t1"}}) is None


class TestCoreAgentModuleExports:
    """Tests for module exports."""

    def test_core_agent_exported_from_core(self) -> None:
        """CoreAgent is exported from soothe.core."""
        from soothe.coreagent import SootheNanoAgent as CoreAgent

        assert CoreAgent is not None

    def test_create_soothe_agent_exported(self) -> None:
        """create_soothe_agent is exported from soothe.core."""
        from soothe.coreagent import create_soothe_agent

        assert create_soothe_agent is not None

    def test_core_agent_create_factory_method(self) -> None:
        """CoreAgent.create() factory method works."""
        from soothe.coreagent import SootheNanoAgent as CoreAgent

        with patch("soothe.coreagent.builder.create_soothe_agent") as mock_factory:
            mock_agent = MagicMock(spec=CoreAgent)
            mock_factory.return_value = mock_agent

            result = CoreAgent.create()

            mock_factory.assert_called_once()
            assert result is mock_agent
