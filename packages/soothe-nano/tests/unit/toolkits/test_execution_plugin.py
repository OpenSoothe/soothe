"""Unit tests for ExecutionPlugin tool loading."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from soothe_nano.toolkits.execution import (
    KillProcessTool,
    RunBackgroundTool,
    RunCommandShellTool,
    RunPythonREPLTool,
    TailBackgroundLogTool,
)


@pytest.mark.asyncio
async def test_execution_plugin_on_load_wires_config() -> None:
    from soothe_nano.toolkits.execution import ExecutionPlugin

    plugin = ExecutionPlugin()
    context = MagicMock()
    context.config = SimpleNamespace(workspace_root="/ws/proj", timeout=90)
    context.soothe_config = SimpleNamespace(security=SimpleNamespace())
    context.logger = MagicMock()

    await plugin.on_load(context)

    tools = plugin.get_tools()
    assert len(tools) == 5
    run_command = next(t for t in tools if isinstance(t, RunCommandShellTool))
    run_background = next(t for t in tools if isinstance(t, RunBackgroundTool))
    assert isinstance(next(t for t in tools if isinstance(t, RunPythonREPLTool)), RunPythonREPLTool)
    assert isinstance(
        next(t for t in tools if isinstance(t, TailBackgroundLogTool)), TailBackgroundLogTool
    )
    assert isinstance(next(t for t in tools if isinstance(t, KillProcessTool)), KillProcessTool)
    assert run_command.workspace_root == "/ws/proj"
    assert run_command.timeout == 90
    assert run_background.workspace_root == "/ws/proj"
    context.logger.info.assert_called_once()
