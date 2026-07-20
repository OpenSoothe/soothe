"""Tests for ProgressiveToolMiddleware."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from soothe_nano.config.settings import SootheConfig
from soothe_nano.middleware.progressive_tools import ProgressiveToolMiddleware
from soothe_nano.toolkits.progressive.registry import merge_tool_activation


def _tool(name: str) -> MagicMock:
    t = MagicMock()
    t.name = name
    t.description = f"Tool {name}"
    return t


@pytest.fixture
def config() -> SootheConfig:
    cfg = SootheConfig()
    cfg.progressive_tools.enabled = True
    cfg.progressive_tools.core_tools = ["run_command", "read_file", "search_tools"]
    return cfg


@pytest.mark.asyncio
async def test_first_hop_binds_core_only(config: SootheConfig) -> None:
    middleware = ProgressiveToolMiddleware(config=config)
    tools = [
        _tool("run_command"),
        _tool("read_file"),
        _tool("search_tools"),
        _tool("wizsearch_search"),
    ]
    middleware.set_tool_catalog(tools)

    class _Req:
        def __init__(self) -> None:
            self.state: dict[str, object] = {}
            self.tools = list(tools)

        def override(self, **kwargs: object) -> _Req:
            out = _Req()
            out.state = self.state
            out.tools = list(kwargs.get("tools", self.tools))  # type: ignore[arg-type]
            return out

    request = _Req()
    captured: dict[str, object] = {}

    async def handler(req: object) -> MagicMock:
        captured["tools"] = getattr(req, "tools", None)
        return MagicMock()

    await middleware.awrap_model_call(request, handler)  # type: ignore[arg-type]

    bound = captured.get("tools")
    assert isinstance(bound, list)
    assert {t.name for t in bound} == {"run_command", "read_file", "search_tools"}


@pytest.mark.asyncio
async def test_search_tools_promotes_matches(config: SootheConfig) -> None:
    middleware = ProgressiveToolMiddleware(config=config)
    tools = [_tool("run_command"), _tool("wizsearch_search")]
    middleware.set_tool_catalog(tools)

    request = MagicMock()
    request.tool_call = {"name": "search_tools", "args": {"query": "wiz", "limit": 5}, "id": "s1"}
    request.state = {"tool_activation": {"sent": set(), "promoted": set()}}

    result = await middleware.awrap_tool_call(request, AsyncMock())

    assert isinstance(result, Command)
    update = result.update
    assert isinstance(update, dict)
    message = update["messages"][0]
    assert isinstance(message, ToolMessage)
    assert "wizsearch_search" in str(message.content)
    assert "wizsearch_search" in update["tool_activation"]["promoted"]


@pytest.mark.asyncio
async def test_second_hop_binds_promoted_tools(config: SootheConfig) -> None:
    middleware = ProgressiveToolMiddleware(config=config)
    tools = [
        _tool("run_command"),
        _tool("read_file"),
        _tool("search_tools"),
        _tool("wizsearch_search"),
    ]
    middleware.set_tool_catalog(tools)

    state: dict[str, object] = {"tool_activation": {"sent": set(), "promoted": set()}}

    search_request = MagicMock()
    search_request.tool_call = {
        "name": "search_tools",
        "args": {"query": "wiz", "limit": 5},
        "id": "s1",
    }
    search_request.state = state

    command = await middleware.awrap_tool_call(search_request, AsyncMock())
    assert isinstance(command, Command)
    update = command.update
    assert isinstance(update, dict)
    merged = merge_tool_activation(state.get("tool_activation"), update.get("tool_activation"))
    state["tool_activation"] = merged

    class _Req:
        def __init__(self) -> None:
            self.state = state
            self.tools = list(tools)

        def override(self, **kwargs: object) -> _Req:
            out = _Req()
            out.state = self.state
            out.tools = list(kwargs.get("tools", self.tools))  # type: ignore[arg-type]
            return out

    request = _Req()
    captured: dict[str, object] = {}

    async def handler(req: object) -> MagicMock:
        captured["tools"] = getattr(req, "tools", None)
        return MagicMock()

    await middleware.awrap_model_call(request, handler)  # type: ignore[arg-type]

    bound = captured.get("tools")
    assert isinstance(bound, list)
    assert {t.name for t in bound} == {
        "run_command",
        "read_file",
        "search_tools",
        "wizsearch_search",
    }


def test_state_schema_declares_tool_activation() -> None:
    assert "tool_activation" in ProgressiveToolMiddleware.state_schema.__annotations__


@pytest.mark.asyncio
async def test_invalid_tool_not_promoted(config: SootheConfig) -> None:
    """Hallucinated tool names must not pollute tool_activation.promoted."""
    middleware = ProgressiveToolMiddleware(config=config)
    tools = [_tool("run_command"), _tool("wizsearch_search")]
    middleware.set_tool_catalog(tools)

    request = MagicMock()
    request.tool_call = {
        "name": "read_command",
        "args": {"command": "grep foo"},
        "id": "bad1",
    }
    request.state = {"tool_activation": {"sent": set(), "promoted": set()}}

    async def handler(_req: object) -> ToolMessage:
        return ToolMessage(
            content="Error: read_command is not a valid tool, try one of [run_command].",
            tool_call_id="bad1",
            name="read_command",
            status="error",
        )

    result = await middleware.awrap_tool_call(request, handler)
    assert isinstance(result, ToolMessage)
    assert "read_command" not in request.state["tool_activation"].get("promoted", set())


@pytest.mark.asyncio
async def test_deferred_tool_still_promoted_on_success(config: SootheConfig) -> None:
    middleware = ProgressiveToolMiddleware(config=config)
    tools = [_tool("run_command"), _tool("wizsearch_search")]
    middleware.set_tool_catalog(tools)

    request = MagicMock()
    request.tool_call = {"name": "wizsearch_search", "args": {"query": "x"}, "id": "ok1"}
    request.state = {"tool_activation": {"sent": set(), "promoted": set()}}

    async def handler(_req: object) -> ToolMessage:
        return ToolMessage(content="results", tool_call_id="ok1", name="wizsearch_search")

    result = await middleware.awrap_tool_call(request, handler)
    assert isinstance(result, Command)
    update = result.update
    assert isinstance(update, dict)
    assert "wizsearch_search" in update["tool_activation"]["promoted"]


@pytest.mark.asyncio
async def test_default_core_binds_skill_discovery_tools() -> None:
    """Core tier must include search_skills/invoke_skill so AVAILABLE_SKILLS is usable."""
    cfg = SootheConfig()
    cfg.progressive_tools.enabled = True
    middleware = ProgressiveToolMiddleware(config=cfg)
    tools = [
        _tool("run_command"),
        _tool("search_tools"),
        _tool("search_skills"),
        _tool("invoke_skill"),
        _tool("wizsearch_search"),
    ]
    middleware.set_tool_catalog(tools)

    class _Req:
        def __init__(self) -> None:
            self.state: dict[str, object] = {}
            self.tools = list(tools)

        def override(self, **kwargs: object) -> _Req:
            out = _Req()
            out.state = self.state
            out.tools = list(kwargs.get("tools", self.tools))  # type: ignore[arg-type]
            return out

    request = _Req()
    captured: dict[str, object] = {}

    async def handler(req: object) -> MagicMock:
        captured["tools"] = getattr(req, "tools", None)
        return MagicMock()

    await middleware.awrap_model_call(request, handler)  # type: ignore[arg-type]

    bound = captured.get("tools")
    assert isinstance(bound, list)
    assert {t.name for t in bound} == {
        "run_command",
        "search_tools",
        "search_skills",
        "invoke_skill",
    }
