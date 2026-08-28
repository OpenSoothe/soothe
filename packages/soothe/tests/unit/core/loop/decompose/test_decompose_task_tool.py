"""Unit tests for executor-bound decompose_task (IG-751 P1)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from soothe.context.decomposition import DecompositionProposal, ProposedSubtask
from soothe.prompts.user_message import UserMessageBuilder
from soothe.sloop.decompose.runtime import (
    bind_decompose_runtime,
    current_evidence_calls,
    current_step_id,
    record_evidence_call,
    record_evidence_output,
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


# ── LLM grounding critic (d15f hallucination defense, scheme 2c) ───────────
#
# The rigid filesystem-path guard was replaced by an LLM-driven critic that
# judges whether a proposal's claims are backed by the evidence the agent
# gathered. The async path (_arun_decompose_task) runs the critic; the sync
# path (_run_decompose_task) cannot (LLM calls are async) and fails open.


def test_decompose_tool_sync_path_fails_open_without_critic() -> None:
    """Sync path has no fast_model → critic skipped → proposal queued.

    The sync variant cannot call the async LLM critic, so when no fast_model
    is bound in the configurable it fails open (queues the proposal). The
    zero-evidence gate still applies.
    """
    sink: list[DecompositionProposal] = []
    tokens = bind_decompose_runtime(step_id="INF-01", sink=sink)
    try:
        record_evidence_call()
        tool = build_decompose_task_tool()
        with patch(
            "soothe.sloop.decompose.tool.langgraph_configurable",
            return_value={},  # no fast_model → critic skipped
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
        assert "queued" in result.lower()
        assert len(sink) == 1
    finally:
        reset_decompose_runtime(tokens)


@pytest.mark.asyncio
async def test_decompose_tool_async_rejects_ungrounded_claims() -> None:
    """Async path: critic returns ungrounded → soft-reject, proposal not queued."""
    from unittest.mock import AsyncMock, MagicMock

    from soothe.sloop.decompose.grounding_guard import (
        GroundingVerdict,
        UngroundedClaim,
    )

    sink: list[DecompositionProposal] = []
    tokens = bind_decompose_runtime(step_id="INF-01", sink=sink)
    try:
        record_evidence_call()
        record_evidence_output("client/go/ exists with 3 files")
        tool = build_decompose_task_tool()
        mock_model = MagicMock()
        verdict = GroundingVerdict(
            grounded=False,
            ungrounded_claims=[
                UngroundedClaim(
                    subtask=1,
                    claim="client/swift/",
                    reason="no swift reference in evidence",
                )
            ],
        )
        with (
            patch(
                "soothe.sloop.decompose.tool.langgraph_configurable",
                return_value={"fast_model": mock_model},
            ),
            patch(
                "soothe_nano.llm.ainvoke_structured_traced",
                new_callable=AsyncMock,
                return_value=verdict.model_dump(),
            ),
        ):
            result = await tool.ainvoke(
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


@pytest.mark.asyncio
async def test_decompose_tool_async_queues_grounded_proposal() -> None:
    """Async path: critic returns grounded → proposal queued."""
    from unittest.mock import AsyncMock, MagicMock

    from soothe.sloop.decompose.grounding_guard import GroundingVerdict

    sink: list[DecompositionProposal] = []
    tokens = bind_decompose_runtime(step_id="INF-01", sink=sink)
    try:
        record_evidence_call()
        record_evidence_output("client/go/ exists with 3 files")
        tool = build_decompose_task_tool()
        mock_model = MagicMock()
        verdict = GroundingVerdict(grounded=True, ungrounded_claims=[])
        with (
            patch(
                "soothe.sloop.decompose.tool.langgraph_configurable",
                return_value={"fast_model": mock_model},
            ),
            patch(
                "soothe_nano.llm.ainvoke_structured_traced",
                new_callable=AsyncMock,
                return_value=verdict.model_dump(),
            ),
        ):
            result = await tool.ainvoke(
                {
                    "task": "enhance all clients",
                    "subtasks": [
                        {
                            "description": "Enhance Go client (client/go/)",
                            "full_description": "Review and enhance client/go/.",
                        },
                    ],
                }
            )
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


# ── FAST-model auto-generation path ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_decompose_tool_auto_generates_subtasks_via_fast_model() -> None:
    """When subtasks are omitted, the FAST model generates them from evidence."""
    from unittest.mock import MagicMock

    from soothe.sloop.decompose.grounding_guard import GeneratedSubtask

    sink: list[DecompositionProposal] = []
    tokens = bind_decompose_runtime(step_id="GEN-01", sink=sink)
    try:
        record_evidence_call()
        record_evidence_output("packages/soothe/src/soothe/config/ exists")
        record_evidence_output("packages/soothe/src/soothe/sloop/ exists")
        tool = build_decompose_task_tool()
        mock_model = MagicMock()

        generated = [
            GeneratedSubtask(
                description="Polish config/ docstrings",
                full_description="Rewrite docstrings in packages/soothe/src/soothe/config/",
            ),
            GeneratedSubtask(
                description="Polish sloop/ docstrings",
                full_description="Rewrite docstrings in packages/soothe/src/soothe/sloop/",
            ),
        ]

        # The first call (generation) returns subtasks; the second (critic)
        # returns grounded=True.
        call_count = 0

        async def _mock_structured(*_a: object, **_kw: object) -> dict:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"subtasks": [s.model_dump() for s in generated]}
            return {"grounded": True, "ungrounded_claims": []}

        with (
            patch(
                "soothe.sloop.decompose.tool.langgraph_configurable",
                return_value={"fast_model": mock_model},
            ),
            patch(
                "soothe_nano.llm.ainvoke_structured_traced",
                new=_mock_structured,
            ),
        ):
            result = await tool.ainvoke({"task": "Polish docstrings"})

        assert "queued" in result.lower()
        assert len(sink) == 1
        assert len(sink[0].subtasks) == 2
        assert sink[0].subtasks[0].description == "Polish config/ docstrings"
    finally:
        reset_decompose_runtime(tokens)


@pytest.mark.asyncio
async def test_decompose_tool_auto_generation_fails_open() -> None:
    """When FAST-model generation fails, the tool asks for explicit subtasks."""
    from unittest.mock import MagicMock

    sink: list[DecompositionProposal] = []
    tokens = bind_decompose_runtime(step_id="GEN-02", sink=sink)
    try:
        record_evidence_call()
        record_evidence_output("some evidence")
        tool = build_decompose_task_tool()
        mock_model = MagicMock()

        async def _failing_structured(*_a: object, **_kw: object) -> dict:
            raise RuntimeError("provider down")

        with (
            patch(
                "soothe.sloop.decompose.tool.langgraph_configurable",
                return_value={"fast_model": mock_model},
            ),
            patch(
                "soothe_nano.llm.ainvoke_structured_traced",
                new=_failing_structured,
            ),
        ):
            result = await tool.ainvoke({"task": "Polish docstrings"})

        assert "Error" in result
        assert "explicit subtasks" in result.lower()
        assert len(sink) == 0
    finally:
        reset_decompose_runtime(tokens)


def test_decompose_tool_sync_path_requires_explicit_subtasks() -> None:
    """Sync path cannot auto-generate; asks for explicit subtasks."""
    sink: list[DecompositionProposal] = []
    tokens = bind_decompose_runtime(step_id="GEN-03", sink=sink)
    try:
        record_evidence_call()
        tool = build_decompose_task_tool()
        result = tool.invoke({"task": "some work"})
        assert "Error" in result
        assert "explicit subtasks" in result.lower()
        assert len(sink) == 0
    finally:
        reset_decompose_runtime(tokens)
