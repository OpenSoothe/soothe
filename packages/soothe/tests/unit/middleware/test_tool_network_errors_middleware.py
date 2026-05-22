"""Tests for NetworkToolErrorsMiddleware."""

from __future__ import annotations

import ssl
from unittest.mock import MagicMock

import pytest
from langchain.agents.middleware.types import ToolCallRequest

from soothe.middleware.tool_network_errors import NetworkToolErrorsMiddleware


@pytest.mark.asyncio
async def test_ssl_error_returns_tool_message():
    middleware = NetworkToolErrorsMiddleware()
    request = ToolCallRequest(
        tool_call={
            "id": "call-1",
            "name": "requests_get",
            "args": {"url": "https://mcap.dev"},
        },
        tool=None,
        state={"messages": []},
        runtime=MagicMock(),
    )

    async def failing_handler(_req: ToolCallRequest):
        raise ssl.SSLCertVerificationError(1, "[SSL: CERTIFICATE_VERIFY_FAILED]")

    result = await middleware.awrap_tool_call(request, failing_handler)

    assert result.tool_call_id == "call-1"
    assert "Error:" in str(result.content)
    assert "verify_ssl" in str(result.content)


@pytest.mark.asyncio
async def test_unrelated_error_is_reraised():
    middleware = NetworkToolErrorsMiddleware()
    request = ToolCallRequest(
        tool_call={"id": "call-2", "name": "grep", "args": {}},
        tool=None,
        state={"messages": []},
        runtime=MagicMock(),
    )

    async def failing_handler(_req: ToolCallRequest):
        raise ValueError("not a network error")

    with pytest.raises(ValueError, match="not a network error"):
        await middleware.awrap_tool_call(request, failing_handler)
