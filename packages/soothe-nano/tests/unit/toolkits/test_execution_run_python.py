"""Unit tests for run_python REPL persistence and async path."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from soothe_nano.toolkits.execution import RunPythonREPLTool


def test_run_python_persistence_on_same_instance() -> None:
    tool = RunPythonREPLTool()
    tool._run(code="counter = 1")
    out = tool._run(code="print(counter + 1)")
    assert "2" in str(out)


def test_run_python_fresh_instance_has_isolated_namespace() -> None:
    tool_a = RunPythonREPLTool()
    tool_a._run(code="counter = 99")
    tool_b = RunPythonREPLTool()
    out = tool_b._run(code="print('counter' in dir())")
    assert "False" in str(out)


def test_run_python_description_mentions_catalog_rebuild() -> None:
    tool = RunPythonREPLTool()
    assert "tool catalog is rebuilt" in tool.description


@pytest.mark.asyncio
async def test_run_python_arun_uses_executor() -> None:
    tool = RunPythonREPLTool()

    async def fake_executor(_pool, fn, code):
        return fn(code)

    with patch("soothe_nano.toolkits.execution.run_in_executor", side_effect=fake_executor):
        result = await tool._arun(code="print(42)")
    assert "42" in str(result)
