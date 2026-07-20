"""Unit tests for MCPActivationMiddleware."""

from unittest.mock import MagicMock

import pytest
from langchain_core.messages import ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.types import Command

from soothe_nano.mcp.mcp_utils import MCPToolDescriptor
from soothe_nano.middleware.mcp_activation import MCPActivationMiddleware


def _registry() -> MagicMock:
    reg = MagicMock()
    always = StructuredTool.from_function(
        func=lambda: "core",
        name="mcp__core__tool",
        description="always loaded",
    )
    deferred_tool = StructuredTool.from_function(
        func=lambda: "def",
        name="mcp__gh__create_issue",
        description="create issue",
    )
    reg.always_loaded_tools.return_value = [always]
    reg.all_tools.return_value = [always, deferred_tool]
    reg.deferred_tools.return_value = [
        MCPToolDescriptor(
            name="mcp__gh__create_issue",
            bare_name="create_issue",
            description="create issue on github",
            server="gh",
            is_essential=False,
        )
    ]
    return reg


@pytest.mark.asyncio
async def test_abefore_agent_inits_mcp_activation() -> None:
    mw = MCPActivationMiddleware(mcp_registry=_registry())
    updates = await mw.abefore_agent({}, MagicMock())
    assert updates is not None
    assert "mcp_activation" in updates
    assert updates["mcp_activation"]["sent"] == set()
    assert updates["mcp_activation"]["promoted"] == set()


@pytest.mark.asyncio
async def test_search_mcp_tools_promotes_matches() -> None:
    registry = _registry()
    mw = MCPActivationMiddleware(mcp_registry=registry)
    mw.set_tool_catalog()

    request = MagicMock()
    request.tool_call = {
        "name": "search_mcp_tools",
        "args": {"query": "create", "limit": 5},
        "id": "tc1",
    }
    request.state = {"mcp_activation": {"sent": set(), "promoted": set()}}

    async def handler(req):
        raise AssertionError("handler should not run")

    result = await mw.awrap_tool_call(request, handler)
    assert isinstance(result, Command)
    update = result.update
    assert isinstance(update, dict)
    message = update["messages"][0]
    assert isinstance(message, ToolMessage)
    assert "Promoted" in message.content
    assert "mcp__gh__create_issue" in message.content
    assert "mcp__gh__create_issue" in update["mcp_activation"]["promoted"]


@pytest.mark.asyncio
async def test_awrap_model_call_binds_core_and_promoted_only() -> None:
    registry = _registry()
    mw = MCPActivationMiddleware(mcp_registry=registry)
    mw.set_tool_catalog()

    core = registry.all_tools()[0]
    deferred = registry.all_tools()[1]
    builtin = StructuredTool.from_function(
        func=lambda: "r",
        name="read_file",
        description="read",
    )
    tools = [builtin, core, deferred]
    state = {
        "mcp_activation": {"sent": set(), "promoted": set()},
        "disabled_mcp_servers": set(),
    }

    class _Req:
        def __init__(self) -> None:
            self.state = state
            self.tools = list(tools)

        def override(self, **kwargs: object):
            out = _Req()
            out.tools = list(kwargs.get("tools", self.tools))  # type: ignore[arg-type]
            return out

    request = _Req()
    captured: dict[str, list] = {}

    async def handler(req: object) -> MagicMock:
        captured["tools"] = list(getattr(req, "tools", []))
        return MagicMock()

    await mw.awrap_model_call(request, handler)  # type: ignore[arg-type]
    names = {t.name for t in captured["tools"]}
    assert "read_file" in names
    assert "mcp__core__tool" in names
    assert "mcp__gh__create_issue" not in names

    request.state["mcp_activation"]["promoted"] = {"mcp__gh__create_issue"}
    await mw.awrap_model_call(request, handler)  # type: ignore[arg-type]
    names2 = {t.name for t in captured["tools"]}
    assert "mcp__gh__create_issue" in names2
