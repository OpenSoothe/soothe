"""Tests for deepagents task-tool RunnableConfig propagation (``_patch.py``)."""

from __future__ import annotations

from unittest.mock import MagicMock

from deepagents.middleware import subagents as sm
from langchain.tools import ToolRuntime

import soothe.core.agent._patch  # noqa: F401  # applies patches on import


class _FakeMsg:
    """Minimal message with ``text`` for task tool result handling."""

    text = "done"


class _RecordingRunnable:
    """Runnable that records config passed to ``invoke`` / ``ainvoke``."""

    def __init__(self) -> None:
        self.invoke_configs: list[object] = []
        self.ainvoke_configs: list[object] = []

    def invoke(self, state: object, config: object | None = None) -> dict:
        self.invoke_configs.append(config)
        return {"messages": [_FakeMsg()]}

    async def ainvoke(self, state: object, config: object | None = None) -> dict:
        self.ainvoke_configs.append(config)
        return {"messages": [_FakeMsg()]}


def _runtime(config: dict) -> ToolRuntime:
    r = MagicMock(spec=ToolRuntime)
    r.state = {"messages": []}
    r.tool_call_id = "call-1"
    r.config = config
    return r


def test_task_tool_runtime_is_injected_arg_for_schema_strip() -> None:
    """PEP563 string annotations break StructuredTool._injected_args_keys; keep real types."""
    rec = _RecordingRunnable()
    tool = sm._build_task_tool([{"name": "browser", "description": "d", "runnable": rec}])
    assert "runtime" in tool._injected_args_keys


def test_task_tool_async_passes_parent_config_to_ainvoke() -> None:
    rec = _RecordingRunnable()
    tool = sm._build_task_tool([{"name": "browser", "description": "d", "runnable": rec}])
    cfg = {"configurable": {"thread_id": "tid-parent"}}

    async def _run() -> None:
        assert tool.coroutine is not None
        await tool.coroutine("do something", "browser", _runtime(cfg))

    import asyncio

    asyncio.run(_run())
    assert rec.ainvoke_configs == [cfg]


def test_task_tool_sync_passes_parent_config_to_invoke() -> None:
    rec = _RecordingRunnable()
    tool = sm._build_task_tool([{"name": "browser", "description": "d", "runnable": rec}])
    cfg = {"configurable": {"thread_id": "tid-parent"}}
    assert tool.func is not None
    tool.func("do something", "browser", _runtime(cfg))
    assert rec.invoke_configs == [cfg]
