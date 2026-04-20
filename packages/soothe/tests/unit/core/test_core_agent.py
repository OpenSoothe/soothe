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
        from soothe.core.agent import CoreAgent

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
        from soothe.core.agent import CoreAgent

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
        from soothe.core.agent import CoreAgent

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
        from soothe.core.agent import CoreAgent

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
        assert kw == {"subgraphs": False}
        assert isinstance(inp, dict)
        assert len(inp["messages"]) == 1
        assert inp["messages"][0].content == "test input"

    def test_create_factory_returns_core_agent(self) -> None:
        """create_soothe_agent() returns CoreAgent instance."""
        from soothe.config import SootheConfig
        from soothe.core.agent import CoreAgent, create_soothe_agent

        with patch("soothe.core.resolver.resolve_tools", return_value=[]):
            with patch("soothe.core.resolver.resolve_subagents", return_value=[]):
                with patch("soothe.core.resolver.resolve_memory", return_value=None):
                    with patch("soothe.core.resolver.resolve_planner", return_value=None):
                        with patch("soothe.core.resolver.resolve_policy", return_value=None):
                            with patch("deepagents.create_deep_agent") as mock_create:
                                mock_graph = _mock_graph()
                                mock_create.return_value = mock_graph

                                config = SootheConfig()
                                agent = create_soothe_agent(config)

                                assert isinstance(agent, CoreAgent)
                                assert agent.graph is mock_graph
                                assert agent.config is config

    def test_no_goal_engine_in_core_agent(self) -> None:
        """CoreAgent does NOT have goal_engine (Layer 3 responsibility)."""
        from soothe.core.agent import CoreAgent

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
        from soothe.core.agent import CoreAgent

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


class TestCoreAgentModuleExports:
    """Tests for module exports."""

    def test_core_agent_exported_from_core(self) -> None:
        """CoreAgent is exported from soothe.core."""
        from soothe.core import CoreAgent

        assert CoreAgent is not None

    def test_create_soothe_agent_exported(self) -> None:
        """create_soothe_agent is exported from soothe.core."""
        from soothe.core import create_soothe_agent

        assert create_soothe_agent is not None

    def test_core_agent_create_factory_method(self) -> None:
        """CoreAgent.create() factory method works."""
        from soothe.core.agent import CoreAgent

        with patch("soothe.core.agent._builder.create_soothe_agent") as mock_factory:
            mock_agent = MagicMock(spec=CoreAgent)
            mock_factory.return_value = mock_agent

            result = CoreAgent.create()

            mock_factory.assert_called_once()
            assert result is mock_agent
