"""Tests for ``soothe.middleware.skill_activation`` (RFC-105)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langgraph.types import Command

from soothe.middleware.skill_activation import FILE_OP_TOOLS, SkillActivationMiddleware
from soothe.skills.registry import ProgressiveSkillRegistry


@pytest.fixture
def middleware() -> SkillActivationMiddleware:
    config = MagicMock()
    config.progressive_skills.intent_prefetch_enabled = False
    return SkillActivationMiddleware(
        registry=ProgressiveSkillRegistry(),
        catalog_provider=lambda: [],
        config=config,
    )


class TestAbeforeAgent:
    @pytest.mark.asyncio
    async def test_inits_skill_activation_state(self, middleware) -> None:
        state = {}
        runtime = MagicMock()
        result = await middleware.abefore_agent(state, runtime)
        assert result is not None
        assert "skill_activation" in result
        assert "activated" in result["skill_activation"]

    @pytest.mark.asyncio
    async def test_skips_if_already_present(self, middleware) -> None:
        state = {
            "skill_activation": {
                **ProgressiveSkillRegistry.init_activation_state(),
                "activated": {"x"},
                "intent_prefetched": True,
            }
        }
        runtime = MagicMock()
        result = await middleware.abefore_agent(state, runtime)
        assert result is None


class TestAwrapToolCall:
    @pytest.mark.asyncio
    async def test_passes_through_non_file_op(self, middleware) -> None:
        request = MagicMock()
        request.tool_call = {"name": "web_search", "args": {}, "id": "1"}
        handler = AsyncMock(return_value="result")

        result = await middleware.awrap_tool_call(request, handler)
        assert result == "result"
        handler.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_search_tools_redirect_when_skill_context_loaded(self, middleware) -> None:
        request = MagicMock()
        request.tool_call = {
            "name": "search_tools",
            "args": {"query": "weather"},
            "id": "st1",
        }
        request.state = {
            "skill_activation": {
                **ProgressiveSkillRegistry.init_activation_state(),
                "invoked": {"weather"},
                "invoked_bodies": {"weather": "curl wttr.in/Beijing"},
            }
        }
        handler = AsyncMock()

        result = await middleware.awrap_tool_call(request, handler)

        handler.assert_not_awaited()
        assert isinstance(result, Command)
        message = result.update["messages"][0]
        assert message.name == "search_tools"
        assert "SKILL_CONTEXT" in message.content

    @pytest.mark.asyncio
    async def test_passes_through_file_op_without_paths(self, middleware) -> None:
        request = MagicMock()
        request.tool_call = {"name": "read_file", "args": {}, "id": "2"}
        request.state = {"skill_activation": ProgressiveSkillRegistry.init_activation_state()}
        handler = AsyncMock(return_value="result")

        result = await middleware.awrap_tool_call(request, handler)
        assert result == "result"

    @pytest.mark.asyncio
    async def test_passes_through_file_op_without_state(self, middleware) -> None:
        request = MagicMock()
        request.tool_call = {"name": "read_file", "args": {"file_path": "/tmp/test.py"}, "id": "3"}
        request.state = {}
        handler = AsyncMock(return_value="result")

        result = await middleware.awrap_tool_call(request, handler)
        assert result == "result"


class TestFileOpTools:
    def test_common_file_ops_included(self) -> None:
        assert "read_file" in FILE_OP_TOOLS
        assert "write_file" in FILE_OP_TOOLS
        assert "edit_file" in FILE_OP_TOOLS
        assert "glob" in FILE_OP_TOOLS
        assert "grep" in FILE_OP_TOOLS
