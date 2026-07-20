"""Tests for unified model call profiler (Soothe middleware + soothe_deepagents patches)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from langchain.agents.middleware.types import AgentMiddleware

from soothe_nano.config.settings import SootheConfig
from soothe_nano.middleware.model_call_profiler import (
    _implements_model_call_hook,
    _patch_deepagents_awrap_model_call,
    install_model_call_profiler,
    is_profiler_enabled,
)


class _FakeMiddleware:
    """Minimal middleware stand-in for soothe_deepagents patch tests."""

    _soothe_deepagents_profiler_patched = False

    async def awrap_model_call(self, request, handler):
        await AsyncMock()()
        return await handler(request)


def test_is_profiler_enabled_reads_config() -> None:
    assert is_profiler_enabled(SootheConfig()) is False
    assert is_profiler_enabled(SootheConfig(observability={"profile_model_calls": True})) is True


def test_install_skips_when_disabled() -> None:
    install_model_call_profiler(enabled=False)


def test_implements_model_call_hook() -> None:
    class _NoHookMiddleware(AgentMiddleware):
        pass

    class _AsyncHookMiddleware(AgentMiddleware):
        async def awrap_model_call(self, request, handler):
            return await handler(request)

    assert _implements_model_call_hook(_NoHookMiddleware) is False
    assert _implements_model_call_hook(_AsyncHookMiddleware) is True


def test_install_skips_patch_tool_calls_middleware() -> None:
    from langchain.agents.middleware.types import AgentMiddleware
    from soothe_deepagents.middleware.patch_tool_calls import PatchToolCallsMiddleware

    from soothe_nano.middleware.model_call_profiler import _DEEPAGENTS_PATCHED_ATTR

    install_model_call_profiler(enabled=True)

    assert PatchToolCallsMiddleware.awrap_model_call is AgentMiddleware.awrap_model_call
    assert not getattr(PatchToolCallsMiddleware, _DEEPAGENTS_PATCHED_ATTR, False)


@pytest.mark.asyncio
async def test_patch_deepagents_awrap_model_call_logs_timing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from soothe_nano.middleware import model_call_profiler as mod

    cls = _FakeMiddleware
    cls._soothe_deepagents_profiler_patched = False

    _patch_deepagents_awrap_model_call(cls, "FakeMiddleware")

    async def inner_handler(request):
        return "ok"

    instance = cls()
    with caplog.at_level("INFO", logger=mod.logger.name):
        result = await instance.awrap_model_call({"x": 1}, inner_handler)

    assert result == "ok"
    assert any("[DeepAgentsProfiler] FakeMiddleware pre=" in r.message for r in caplog.records)

    wrapped = cls.awrap_model_call
    _patch_deepagents_awrap_model_call(cls, "FakeMiddleware")
    assert cls.awrap_model_call is wrapped


@pytest.mark.asyncio
async def test_patch_deepagents_awrap_model_call_preserves_short_circuit_return() -> None:
    """Middleware that skips the inner handler must still return its response."""

    class _ShortCircuitMiddleware:
        _soothe_deepagents_profiler_patched = False

        async def awrap_model_call(self, request, handler):
            return "short-circuit"

    cls = _ShortCircuitMiddleware
    _patch_deepagents_awrap_model_call(cls, "ShortCircuitMiddleware")

    instance = cls()
    result = await instance.awrap_model_call({"x": 1}, AsyncMock())
    assert result == "short-circuit"
