"""Tests for ToolOutputCapMiddleware."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import ToolMessage

from soothe.config import SootheConfig
from soothe.middleware.tool_output_cap import ToolOutputCapMiddleware, _truncate_content


@pytest.fixture
def config() -> SootheConfig:
    cfg = SootheConfig()
    cfg.agent.loop.tool_output.code_exec_max_output_chars = 100
    cfg.agent.loop.tool_output.tool_output_max_chars = 50
    return cfg


@pytest.mark.asyncio
async def test_awrap_tool_call_truncates_run_command_output(config: SootheConfig) -> None:
    middleware = ToolOutputCapMiddleware(config=config)
    long_output = "x" * 200
    request = MagicMock()
    request.tool_call = {"name": "run_command", "id": "tc1"}
    request.state = {}

    handler = AsyncMock(
        return_value=ToolMessage(content=long_output, tool_call_id="tc1", name="run_command"),
    )
    result = await middleware.awrap_tool_call(request, handler)

    assert isinstance(result, ToolMessage)
    assert len(str(result.content)) <= 100
    assert "truncated" in str(result.content)


@pytest.mark.asyncio
async def test_awrap_model_call_truncates_tool_messages_in_request(config: SootheConfig) -> None:
    middleware = ToolOutputCapMiddleware(config=config)
    long_output = "y" * 200
    original_messages = [
        ToolMessage(content=long_output, tool_call_id="tc2", name="read_file"),
    ]

    class _Req:
        def __init__(self) -> None:
            self.messages = list(original_messages)
            self.system_message = None
            self.tools: list[object] = []

        def override(self, **kwargs: object) -> _Req:
            out = _Req()
            out.messages = list(kwargs.get("messages", self.messages))  # type: ignore[arg-type]
            out.tools = self.tools
            return out

    request = _Req()
    captured: dict[str, object] = {}

    async def handler(req: object) -> MagicMock:
        captured["messages"] = getattr(req, "messages", None)
        return MagicMock()

    await middleware.awrap_model_call(request, handler)  # type: ignore[arg-type]

    msgs = captured.get("messages")
    assert isinstance(msgs, list)
    assert len(str(msgs[0].content)) <= 50


def test_truncate_content_preserves_short_text() -> None:
    assert _truncate_content("hello", 50) == "hello"
