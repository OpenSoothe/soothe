"""Unit tests for executor-bound decompose_task (IG-751 P1)."""

from __future__ import annotations

from unittest.mock import patch

from soothe.context.decomposition import DecompositionProposal, ProposedSubtask
from soothe.prompts.user_message import UserMessageBuilder
from soothe.sloop.decompose.runtime import (
    bind_decompose_runtime,
    current_step_id,
    reset_decompose_runtime,
)
from soothe.sloop.decompose.tool import build_decompose_task_tool


def test_decompose_tool_queues_proposal() -> None:
    sink: list[DecompositionProposal] = []
    tokens = bind_decompose_runtime(step_id="AAA-01", sink=sink, wave_seq=1)
    try:
        tool = build_decompose_task_tool()
        result = tool.invoke(
            {
                "task": "root work",
                "subtasks": [
                    {
                        "description": "child A",
                        "full_description": "do A thoroughly",
                        "expected_output": "A done",
                    }
                ],
            }
        )
        assert "queued" in result.lower()
        assert len(sink) == 1
        assert sink[0].parent_step_id == "AAA-01"
        assert sink[0].wave_seq == 1
        assert sink[0].subtasks[0].description == "child A"
    finally:
        reset_decompose_runtime(tokens)
    assert current_step_id() is None


def test_decompose_tool_errors_without_runtime() -> None:
    tool = build_decompose_task_tool()
    result = tool.invoke(
        {
            "task": "x",
            "subtasks": [ProposedSubtask(description="only")],
        }
    )
    assert result.startswith("Error:")


def test_decompose_tool_errors_with_no_subtasks() -> None:
    sink: list[DecompositionProposal] = []
    tokens = bind_decompose_runtime(step_id="AAA-01", sink=sink)
    try:
        tool = build_decompose_task_tool()
        result = tool.invoke({"task": "some work", "subtasks": []})
        assert "Error" in result
        assert "no subtasks" in result.lower()
        assert len(sink) == 0
    finally:
        reset_decompose_runtime(tokens)


def test_decompose_tool_accepts_proposedsubtask_instances() -> None:
    """Subtasks may arrive as ProposedSubtask instances or dicts."""
    sink: list[DecompositionProposal] = []
    tokens = bind_decompose_runtime(step_id="AAA-01", sink=sink)
    try:
        tool = build_decompose_task_tool()
        result = tool.invoke(
            {
                "task": "root work",
                "subtasks": [
                    ProposedSubtask(description="instance subtask"),
                    {"description": "dict subtask"},
                ],
            }
        )
        assert "queued" in result.lower()
        assert len(sink[0].subtasks) == 2
        assert sink[0].subtasks[0].description == "instance subtask"
        assert sink[0].subtasks[1].description == "dict subtask"
    finally:
        reset_decompose_runtime(tokens)


def test_decompose_tool_truncates_branch_cap() -> None:
    """Excess subtasks are truncated to max_branch_root, not rejected."""
    sink: list[DecompositionProposal] = []
    tokens = bind_decompose_runtime(step_id="CAP-01", sink=sink)
    try:
        tool = build_decompose_task_tool()
        with patch(
            "soothe.sloop.decompose.tool.langgraph_configurable",
            return_value={"soothe_max_branch_root": 3},
        ):
            result = tool.invoke(
                {
                    "task": "too many subtasks",
                    "subtasks": [
                        {"description": f"subtask {i}"} for i in range(6)
                    ],
                }
            )
        assert "queued" in result.lower()
        assert "3 subtasks" in result
        assert len(sink) == 1
        assert len(sink[0].subtasks) == 3  # truncated from 6
    finally:
        reset_decompose_runtime(tokens)


def test_decompose_tool_default_branch_cap_is_8() -> None:
    """Without a configurable max_branch_root, the default cap is 8."""
    sink: list[DecompositionProposal] = []
    tokens = bind_decompose_runtime(step_id="DEF-01", sink=sink)
    try:
        tool = build_decompose_task_tool()
        with patch(
            "soothe.sloop.decompose.tool.langgraph_configurable",
            return_value={},
        ):
            tool.invoke(
                {
                    "task": "many subtasks",
                    "subtasks": [
                        {"description": f"subtask {i}"} for i in range(12)
                    ],
                }
            )
        assert len(sink[0].subtasks) == 8  # default cap
    finally:
        reset_decompose_runtime(tokens)


def test_decompose_tool_returns_terminal_message() -> None:
    """The tool result must tell the model to end the thread."""
    sink: list[DecompositionProposal] = []
    tokens = bind_decompose_runtime(step_id="END-01", sink=sink)
    try:
        tool = build_decompose_task_tool()
        result = tool.invoke(
            {
                "task": "root work",
                "subtasks": [{"description": "child A"}],
            }
        )
        assert "should end" in result.lower()
        assert "do not continue" in result.lower()
    finally:
        reset_decompose_runtime(tokens)


def test_execute_envelope_is_instance_focused() -> None:
    msg = UserMessageBuilder().build_execute_step_message(
        "Do the thing",
        step_id="S1",
    )
    assert "EXECUTION TASK:" in msg
    assert "DECOMPOSITION vs TODOS" not in msg
    assert "FINISH HERE" not in msg
