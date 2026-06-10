"""Tests for ProgressiveToolMiddleware."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe.config import SootheConfig
from soothe.middleware.progressive_tools import ProgressiveToolMiddleware


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

    from langchain_core.messages import ToolMessage

    assert isinstance(result, ToolMessage)
    assert "wizsearch_search" in str(result.content)
    assert "wizsearch_search" in request.state["tool_activation"]["promoted"]
