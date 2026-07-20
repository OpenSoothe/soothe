"""Unit tests for MCP progressive tool surfacing (RFC-412).

Exercises search → promote → bind across MCPActivationMiddleware and
ProgressiveToolMiddleware (discovery stubs must stay bound on cold start).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from langchain_core.messages import ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.types import Command

from soothe_nano.config import SootheConfig
from soothe_nano.mcp.mcp_progressive import create_search_mcp_tools_tool
from soothe_nano.mcp.mcp_utils import MCPToolDescriptor
from soothe_nano.middleware import build_soothe_middleware_stack
from soothe_nano.middleware.mcp_activation import MCPActivationMiddleware
from soothe_nano.middleware.progressive_listing import ProgressiveListingMiddleware
from soothe_nano.middleware.progressive_tools import ProgressiveToolMiddleware
from soothe_nano.middleware.system_prompt import SystemPromptMiddleware


def _deferred_descriptors(count: int = 50) -> list[MCPToolDescriptor]:
    descriptors: list[MCPToolDescriptor] = []
    for i in range(count):
        descriptors.append(
            MCPToolDescriptor(
                name=f"mcp__mock__tool_{i:02d}",
                bare_name=f"tool_{i:02d}",
                description=f"Mock deferred MCP tool number {i}",
                server="mock",
                is_essential=False,
            )
        )
    return descriptors


def _tool_from_descriptor(d: MCPToolDescriptor) -> StructuredTool:
    return StructuredTool.from_function(
        func=lambda: d.name,
        name=d.name,
        description=d.description,
    )


def _mock_mcp_registry(*, deferred_count: int = 50) -> MagicMock:
    always = StructuredTool.from_function(
        func=lambda: "core",
        name="mcp__mock__always_loaded",
        description="Always-loaded MCP tool",
    )
    deferred = _deferred_descriptors(deferred_count)
    deferred_tools = [_tool_from_descriptor(d) for d in deferred]

    registry = MagicMock()
    registry.always_loaded_tools.return_value = [always]
    registry.all_tools.return_value = [always, *deferred_tools]
    registry.deferred_tools.return_value = deferred
    return registry


def _full_catalog(registry: MagicMock) -> list[StructuredTool]:
    catalog = list(registry.all_tools())
    catalog.append(create_search_mcp_tools_tool())
    return catalog


@pytest.fixture
def mcp_surfacing_config(test_config: SootheConfig) -> SootheConfig:
    """Ensure progressive builtin tools are enabled (default) for binding tests."""
    test_config.progressive_tools.enabled = True
    test_config.progressive_tools.search_tools_enabled = True
    return test_config


def _middleware_instances(
    config: SootheConfig, registry: MagicMock
) -> tuple[
    ProgressiveToolMiddleware,
    MCPActivationMiddleware,
    ProgressiveListingMiddleware,
    SystemPromptMiddleware,
]:
    stack = build_soothe_middleware_stack(config, policy=None, mcp_registry=registry)
    progressive = next(m for m in stack if isinstance(m, ProgressiveToolMiddleware))
    mcp_activation = next(m for m in stack if isinstance(m, MCPActivationMiddleware))
    progressive_listing = next(m for m in stack if isinstance(m, ProgressiveListingMiddleware))
    system_prompt = next(m for m in stack if isinstance(m, SystemPromptMiddleware))
    catalog = _full_catalog(registry)
    progressive.set_tool_catalog(catalog)
    mcp_activation.set_tool_catalog()
    return progressive, mcp_activation, progressive_listing, system_prompt


class _ModelRequest:
    def __init__(self, tools: list[StructuredTool], state: dict) -> None:
        self.tools = list(tools)
        self.state = state

    def override(self, **kwargs: object) -> _ModelRequest:
        tools = list(kwargs.get("tools", self.tools))  # type: ignore[arg-type]
        return _ModelRequest(tools, self.state)


@pytest.mark.asyncio
async def test_cold_start_binds_discovery_stub_not_deferred_mcp(
    mcp_surfacing_config: SootheConfig,
) -> None:
    """search_mcp_tools stays bound; 50 deferred mcp__ tools are filtered."""
    registry = _mock_mcp_registry()
    progressive, mcp_activation, _, _ = _middleware_instances(mcp_surfacing_config, registry)
    catalog = _full_catalog(registry)
    state = {"mcp_activation": {"sent": set(), "promoted": set()}}

    request = _ModelRequest(catalog, state)
    captured: dict[str, list[StructuredTool]] = {}

    async def handler(req: _ModelRequest) -> MagicMock:
        captured["tools"] = list(req.tools)
        return MagicMock()

    await progressive.awrap_model_call(request, handler)  # type: ignore[arg-type]
    await mcp_activation.awrap_model_call(request, handler)  # type: ignore[arg-type]

    names = {t.name for t in captured["tools"]}
    assert "search_mcp_tools" in names
    assert "mcp__mock__always_loaded" in names
    deferred_names = {d.name for d in registry.deferred_tools()}
    assert names.isdisjoint(deferred_names)


@pytest.mark.asyncio
async def test_search_mcp_tools_promotes_and_next_hop_binds(
    mcp_surfacing_config: SootheConfig,
) -> None:
    """search_mcp_tools promotes matches; subsequent model hop binds them."""
    registry = _mock_mcp_registry()
    progressive, mcp_activation, _, _ = _middleware_instances(mcp_surfacing_config, registry)
    catalog = _full_catalog(registry)
    state: dict = {
        "mcp_activation": {"sent": set(), "promoted": set()},
        "tool_activation": {"sent": set(), "promoted": set()},
    }

    request = MagicMock()
    request.tool_call = {
        "name": "search_mcp_tools",
        "args": {"query": "tool_07", "limit": 5},
        "id": "tc-search",
    }
    request.state = state

    async def handler(req: object) -> ToolMessage:
        raise AssertionError("search_mcp_tools must be handled by middleware")

    result = await mcp_activation.awrap_tool_call(request, handler)
    assert isinstance(result, Command)
    update = result.update
    assert isinstance(update, dict)
    promoted = update["mcp_activation"]["promoted"]
    assert "mcp__mock__tool_07" in promoted

    state["mcp_activation"] = update["mcp_activation"]
    model_request = _ModelRequest(catalog, state)
    captured: dict[str, list[StructuredTool]] = {}

    async def model_handler(req: _ModelRequest) -> MagicMock:
        captured["tools"] = list(req.tools)
        return MagicMock()

    await progressive.awrap_model_call(model_request, model_handler)  # type: ignore[arg-type]
    await mcp_activation.awrap_model_call(model_request, model_handler)  # type: ignore[arg-type]

    names = {t.name for t in captured["tools"]}
    assert "mcp__mock__tool_07" in names
    assert "mcp__mock__tool_08" not in names


@pytest.mark.asyncio
async def test_system_prompt_lists_deferred_delta_then_excludes_promoted(
    mcp_surfacing_config: SootheConfig,
) -> None:
    """<AVAILABLE_MCP_TOOLS> lists unsent deferred tools and skips promoted ones."""
    registry = _mock_mcp_registry(deferred_count=50)
    _, _, progressive_listing, _ = _middleware_instances(mcp_surfacing_config, registry)

    state: dict = {
        "mcp_activation": {
            "sent": {f"mcp__mock__tool_{i:02d}" for i in range(10)},
            "promoted": {"mcp__mock__tool_07"},
        },
        "routing_classification": {"task_complexity": "simple"},
    }
    request = _ModelRequest(_full_catalog(registry), state)
    progressive_listing.modify_request(request)  # type: ignore[arg-type]
    block = state.get("_available_mcp_tools_block")
    assert isinstance(block, str)
    assert "<AVAILABLE_MCP_TOOLS>" in block
    assert "mcp__mock__tool_07" not in block
    assert "mcp__mock__tool_00" not in block
    assert "mcp__mock__tool_11" in block
