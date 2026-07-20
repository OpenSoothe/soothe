"""Tests for ProgressiveListingMiddleware."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from langchain.agents.middleware.types import ModelRequest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from soothe_nano.config.settings import SootheConfig
from soothe_nano.middleware.progressive_listing import ProgressiveListingMiddleware
from soothe_nano.middleware.progressive_tools import ProgressiveToolMiddleware


def test_prepares_available_tools_block_with_deferred_entries() -> None:
    config = SootheConfig()
    config.progressive_tools.enabled = True
    config.progressive_tools.core_tools = ["run_command", "read_file", "search_tools"]

    progressive = ProgressiveToolMiddleware(config=config)
    core = SimpleNamespace(name="run_command", description="Shell")
    deferred = SimpleNamespace(name="wizsearch_search", description="Web search tool")
    progressive.set_tool_catalog([core, deferred])

    listing = ProgressiveListingMiddleware(
        config=config,
        progressive_tool_middleware=progressive,
    )
    request = ModelRequest(
        model=GenericFakeChatModel(messages=iter([AIMessage(content="ok")])),
        messages=[HumanMessage(content="help me search")],
        system_message=SystemMessage(content="base"),
        tools=[core],
        state={"routing_classification": {"task_complexity": "simple"}},
    )

    listing.modify_request(request)
    block = request.state.get("_available_tools_block")
    assert isinstance(block, str)
    assert "<AVAILABLE_TOOLS>" in block
    assert "wizsearch_search" in block


def test_prepares_available_mcp_tools_block() -> None:
    config = SootheConfig()
    registry = MagicMock()
    registry.always_loaded_tools.return_value = [SimpleNamespace(name="mcp__mock__core")]
    registry.deferred_tools.return_value = [
        SimpleNamespace(
            name="mcp__mock__tool_01",
            bare_name="tool_01",
            description="Mock MCP tool",
            server="mock",
            is_essential=False,
        )
    ]
    listing = ProgressiveListingMiddleware(config=config, mcp_registry=registry)
    request = ModelRequest(
        model=GenericFakeChatModel(messages=iter([AIMessage(content="ok")])),
        messages=[HumanMessage(content="use MCP")],
        system_message=SystemMessage(content="base"),
        tools=[],
        state={"routing_classification": {"task_complexity": "simple"}},
    )

    listing.modify_request(request)
    block = request.state.get("_available_mcp_tools_block")
    assert isinstance(block, str)
    assert "<AVAILABLE_MCP_TOOLS>" in block
    assert "mcp__mock__tool_01" in block
