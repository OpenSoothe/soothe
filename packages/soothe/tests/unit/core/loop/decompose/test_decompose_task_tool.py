"""Unit tests for executor-bound decompose_task (IG-751 P1)."""

from __future__ import annotations

from soothe.context.decomposition import DecompositionProposal, ProposedSubtask
from soothe.sloop.decompose.runtime import (
    bind_decompose_runtime,
    current_step_id,
    reset_decompose_runtime,
)
from soothe.sloop.decompose.tool import build_decompose_task_tool
from soothe.sloop.prompts.decompose import DECOMPOSITION_VS_TODOS_BLOCK
from soothe.sloop.prompts.user_message import UserMessageBuilder


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


def test_execute_envelope_includes_decompose_guidance() -> None:
    msg = UserMessageBuilder().build_execute_step_message(
        "Do the thing",
        step_id="S1",
    )
    assert "DECOMPOSITION vs TODOS" in msg
    assert "decompose_task" in msg
    assert DECOMPOSITION_VS_TODOS_BLOCK.strip().split("\n")[0] in msg or "write_todos" in msg
