"""Unit tests for executor-bound decompose_task (IG-751 P1)."""

from __future__ import annotations

from unittest.mock import patch

from soothe.context.decomposition import DecompositionProposal, ProposedSubtask
from soothe.prompts.user_message import UserMessageBuilder
from soothe.sloop.decompose.runtime import (
    bind_decompose_runtime,
    current_evidence_calls,
    current_step_id,
    record_evidence_call,
    reset_decompose_runtime,
)
from soothe.sloop.decompose.tool import build_decompose_task_tool


def test_decompose_tool_queues_proposal() -> None:
    sink: list[DecompositionProposal] = []
    tokens = bind_decompose_runtime(step_id="AAA-01", sink=sink, wave_seq=1)
    try:
        # Simulate one prior grounding call (the model read a file before
        # proposing). Without this the evidence-call gate rejects the proposal.
        record_evidence_call()
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


# ── Evidence-call gate (d15f hallucination defense, scheme 2d) ─────────────


def test_decompose_tool_rejected_with_no_prior_evidence() -> None:
    """A decompose_task issued with zero grounding calls is rejected (d15f)."""
    sink: list[DecompositionProposal] = []
    tokens = bind_decompose_runtime(step_id="INF-01", sink=sink)
    try:
        tool = build_decompose_task_tool()
        result = tool.invoke(
            {
                "task": "enhance all clients",
                "subtasks": [
                    {"description": "client A", "full_description": "do A"},
                ],
            }
        )
        assert "NOT queued" in result
        assert "evidence" in result.lower()
        assert len(sink) == 0  # proposal not queued
    finally:
        reset_decompose_runtime(tokens)


def test_decompose_tool_accepted_after_one_evidence_call() -> None:
    """One grounding call satisfies the evidence gate; proposal is queued."""
    sink: list[DecompositionProposal] = []
    tokens = bind_decompose_runtime(step_id="INF-01", sink=sink)
    try:
        record_evidence_call()
        tool = build_decompose_task_tool()
        result = tool.invoke(
            {
                "task": "enhance all clients",
                "subtasks": [
                    {"description": "client A", "full_description": "do A"},
                ],
            }
        )
        assert "queued" in result.lower()
        assert len(sink) == 1
    finally:
        reset_decompose_runtime(tokens)


# ── Path-existence guard (d15f hallucination defense, scheme 2c) ───────────


def test_decompose_tool_rejects_unconfirmed_paths(tmp_path) -> None:
    """A proposal citing non-existent paths is rejected even with evidence."""
    # Create a real client dir so one subtask is confirmed; the other cites a
    # fabricated path that does not exist (the d15f Swift hallucination).
    (tmp_path / "client" / "go").mkdir(parents=True)
    sink: list[DecompositionProposal] = []
    tokens = bind_decompose_runtime(step_id="INF-01", sink=sink)
    try:
        record_evidence_call()
        tool = build_decompose_task_tool()
        with patch(
            "soothe.sloop.decompose.runtime.langgraph_configurable",
            return_value={"workspace": str(tmp_path)},
        ):
            result = tool.invoke(
                {
                    "task": "enhance all clients",
                    "subtasks": [
                        {
                            "description": "Enhance Go client (client/go/)",
                            "full_description": "Review and enhance client/go/.",
                        },
                        {
                            "description": "Enhance Swift client (client/swift/)",
                            "full_description": "Review and enhance client/swift/.",
                        },
                    ],
                }
            )
        assert "NOT queued" in result
        assert "client/swift/" in result
        assert len(sink) == 0
    finally:
        reset_decompose_runtime(tokens)


def test_decompose_tool_fails_open_when_workspace_unset() -> None:
    """When workspace is unavailable, the path guard is skipped (fail open)."""
    sink: list[DecompositionProposal] = []
    tokens = bind_decompose_runtime(step_id="INF-01", sink=sink)
    try:
        record_evidence_call()
        tool = build_decompose_task_tool()
        with patch(
            "soothe.sloop.decompose.runtime.langgraph_configurable",
            return_value={},
        ):
            result = tool.invoke(
                {
                    "task": "enhance all clients",
                    "subtasks": [
                        {
                            "description": "Enhance Swift client (client/swift/)",
                            "full_description": "Review and enhance client/swift/.",
                        },
                    ],
                }
            )
        # No workspace → path guard skipped → proposal queued (evidence satisfied).
        assert "queued" in result.lower()
        assert len(sink) == 1
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


# ── Pregel copy_context isolation (loops 7e83 / 48bd regression) ──────────


def test_evidence_counter_survives_copy_context_snapshots() -> None:
    """Evidence increments made inside a ``copy_context()`` snapshot (how
    LangGraph's Pregel executor runs each ToolNode turn) must be visible to
    the parent context and to later snapshots that read the count at
    ``decompose_task`` time.

    Before the mutable-list fix the counter was a plain ``int``; ``ContextVar``
    writes are copy-on-write, so the increment vanished at the snapshot
    boundary and every ``decompose_task`` was wrongly rejected as
    "no prior evidence" despite dozens of ls/grep/read_file calls
    (loops 7e83, 48bd).
    """
    from contextvars import copy_context

    sink: list[DecompositionProposal] = []
    tokens = bind_decompose_runtime(step_id="NMK-01", sink=sink)
    try:
        assert current_evidence_calls() == 0

        # Simulate a grounding tool turn running inside a Pregel context snapshot.
        def grounding_turn() -> None:
            assert current_evidence_calls() == 0
            record_evidence_call()
            record_evidence_call()
            assert current_evidence_calls() == 2

        copy_context().run(grounding_turn)

        # Parent must observe the increment (this is what failed pre-fix).
        assert current_evidence_calls() == 2

        # A *different* snapshot (the decompose_task turn) must also see it.
        def decompose_turn() -> None:
            assert current_evidence_calls() == 2

        copy_context().run(decompose_turn)

        # A further grounding turn in another snapshot accumulates on top.
        def grounding_turn_2() -> None:
            record_evidence_call()

        copy_context().run(grounding_turn_2)
        assert current_evidence_calls() == 3
    finally:
        reset_decompose_runtime(tokens)
