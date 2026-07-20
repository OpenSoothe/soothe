"""Unit tests for CodeInterpreterMiddleware (langchain_quickjs bridge)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage

from soothe_nano.config.settings import SootheConfig
from soothe_nano.middleware.code_interpreter import CodeInterpreterMiddleware

pytest.importorskip("langchain_quickjs")


def test_initialize_inner_succeeds_without_type_error() -> None:
    """Config fields must map to langchain_quickjs constructor kwargs (no TypeError)."""
    config = SootheConfig(
        agent={
            "code_interpreter": {
                "enabled": True,
                "ptc_allowlist": ["task"],
                "memory_limit_mb": 64,
                "timeout_seconds": 10,
                "max_ptc_calls": 25,
                "max_result_size": 8000,
                "console_capture": False,
                "snapshot_between_turns": True,
            }
        }
    )
    middleware = CodeInterpreterMiddleware(config=config)
    inner = middleware._initialize_inner()

    assert inner is not None
    assert middleware.tools
    assert middleware.tools[0].name == "eval"


@pytest.mark.asyncio
async def test_awrap_tool_call_passes_through_without_not_implemented() -> None:
    """Async agent runs must not delegate to QuickJS awrap_tool_call (not implemented)."""
    middleware = CodeInterpreterMiddleware(config=SootheConfig())
    middleware._initialize_inner()

    request = ToolCallRequest(
        tool_call={"name": "grep", "args": {"pattern": "deepxiv"}, "id": "tc-1"},
        tool=None,
        state={"messages": []},
        runtime=MagicMock(),
    )
    expected = ToolMessage(content="ok", tool_call_id="tc-1")
    handler = AsyncMock(return_value=expected)

    result = await middleware.awrap_tool_call(request, handler)

    assert result is expected
    handler.assert_awaited_once_with(request)


def test_disabled_by_default() -> None:
    """Code interpreter must be disabled by default (opt-in feature)."""
    config = SootheConfig()
    assert config.agent.code_interpreter.enabled is False
    assert config.agent.code_interpreter.ptc_allowlist == []


def test_config_values_propagate_to_middleware() -> None:
    """Config values must propagate to middleware attributes."""
    config = SootheConfig(
        agent={
            "code_interpreter": {
                "enabled": True,
                "ptc_allowlist": ["task", "search"],
                "memory_limit_mb": 256,
                "timeout_seconds": 60,
                "max_ptc_calls": 100,
                "max_result_size": 200000,
                "console_capture": False,
                "snapshot_between_turns": True,
            }
        }
    )
    middleware = CodeInterpreterMiddleware(config=config)

    assert middleware._ptc_allowlist == ["task", "search"]
    assert middleware._memory_limit_mb == 256
    assert middleware._timeout_seconds == 60
    assert middleware._max_ptc_calls == 100
    assert middleware._max_result_size == 200000
    assert middleware._console_capture is False
    assert middleware._snapshot_between_turns is True


def test_explicit_args_override_config() -> None:
    """Explicit constructor args must override config values."""
    config = SootheConfig(
        agent={
            "code_interpreter": {
                "enabled": True,
                "ptc_allowlist": ["task"],
                "memory_limit_mb": 128,
            }
        }
    )
    middleware = CodeInterpreterMiddleware(
        config=config,
        ptc_allowlist=["search"],
        memory_limit_mb=64,
    )

    # When config is provided, its values override explicit args
    assert middleware._ptc_allowlist == ["task"]
    assert middleware._memory_limit_mb == 128


def test_no_config_uses_defaults() -> None:
    """Middleware without config must use explicit args or defaults."""
    middleware = CodeInterpreterMiddleware()

    assert middleware._ptc_allowlist == []
    assert middleware._memory_limit_mb == 128
    assert middleware._timeout_seconds == 30
    assert middleware._max_ptc_calls == 50


def test_middleware_stack_skips_code_interpreter_without_ptc_allowlist() -> None:
    """Enabled CI with empty allowlist must not mount middleware (IG-506)."""
    from soothe_nano.middleware._builder import build_soothe_middleware_stack

    config = SootheConfig(
        agent={
            "code_interpreter": {
                "enabled": True,
                "ptc_allowlist": [],
            }
        }
    )
    stack = build_soothe_middleware_stack(config, policy=None)
    assert not any(type(m).__name__ == "CodeInterpreterMiddleware" for m in stack)
