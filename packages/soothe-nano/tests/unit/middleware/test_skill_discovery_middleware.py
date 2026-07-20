"""Tests for skill discovery tools in SkillActivationMiddleware (IG-543)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from soothe_nano.middleware.skill_activation import (
    INVOKE_SKILL_TOOL,
    SEARCH_SKILLS_TOOL,
    SkillActivationMiddleware,
)
from soothe_nano.skills.index import SkillIndexEntry
from soothe_nano.skills.registry import ProgressiveSkillRegistry


def _entry(name: str, *, source: str = "user") -> SkillIndexEntry:
    return SkillIndexEntry(
        name=name,
        description=f"{name} description",
        tags=name,
        source=source,
        path="/tmp",
        mtime=0.0,
    )


@pytest.fixture
def middleware() -> SkillActivationMiddleware:
    config = MagicMock()
    config.progressive_skills.core_skills = None
    config.progressive_skills.intent_prefetch_enabled = False
    return SkillActivationMiddleware(
        registry=ProgressiveSkillRegistry(),
        catalog_provider=lambda: [
            _entry("weather", source="builtin"),
            _entry("db-migrate"),
        ],
        config=config,
    )


class TestSearchSkills:
    @pytest.mark.asyncio
    async def test_discovers_deferred_skill(self, middleware: SkillActivationMiddleware) -> None:
        request = MagicMock()
        request.metadata = {}
        request.tool_call = {
            "name": SEARCH_SKILLS_TOOL,
            "args": {"query": "db-migrate", "limit": 5},
            "id": "s1",
        }
        request.state = {"skill_activation": ProgressiveSkillRegistry.init_activation_state()}

        result = await middleware.awrap_tool_call(request, AsyncMock())

        assert result.update is not None
        activation = result.update["skill_activation"]
        assert "db-migrate" in activation["activated"]
        message = result.update["messages"][0]
        assert "db-migrate" in message.content

    @pytest.mark.asyncio
    async def test_core_skill_not_searchable(self, middleware: SkillActivationMiddleware) -> None:
        request = MagicMock()
        request.metadata = {}
        request.tool_call = {
            "name": SEARCH_SKILLS_TOOL,
            "args": {"query": "weather", "limit": 5},
            "id": "s2",
        }
        request.state = {"skill_activation": ProgressiveSkillRegistry.init_activation_state()}

        result = await middleware.awrap_tool_call(request, AsyncMock())

        message = result.update["messages"][0]
        assert "No deferred skills matched" in message.content


class TestInvokeSkill:
    @pytest.mark.asyncio
    async def test_missing_skill_returns_error(self, middleware: SkillActivationMiddleware) -> None:
        request = MagicMock()
        request.metadata = {}
        request.tool_call = {
            "name": INVOKE_SKILL_TOOL,
            "args": {"name": "missing-skill"},
            "id": "i1",
        }
        request.state = {
            "skill_activation": ProgressiveSkillRegistry.init_activation_state(),
            "workspace": "/tmp",
        }

        result = await middleware.awrap_tool_call(request, AsyncMock())

        message = result.update["messages"][0]
        assert "not found" in message.content.lower()
