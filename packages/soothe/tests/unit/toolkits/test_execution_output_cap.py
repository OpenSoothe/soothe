"""Tests for configurable execution toolkit output cap."""

from __future__ import annotations

from soothe.toolkits.execution import ExecutionToolkit, _execution_max_output_from_config


def test_execution_toolkit_passes_max_output_length() -> None:
    toolkit = ExecutionToolkit(max_output_length=500)
    tools = toolkit.get_tools()
    run_command = next(t for t in tools if t.name == "run_command")
    assert run_command.max_output_length == 500


def test_execution_max_output_from_config_default() -> None:
    assert _execution_max_output_from_config(None) == 100_000
