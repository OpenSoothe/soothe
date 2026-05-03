"""Tests for IG-302 synthesis isolated LangGraph checkpoint thread."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from soothe.core.agent_loop.analysis.scenario_classifier import ScenarioClassification
from soothe.core.agent_loop.analysis.synthesis import (
    SynthesisGenerator,
    synthesis_checkpoint_thread_id,
)
from soothe.core.agent_loop.state.schemas import LoopState, StepResult
from soothe.core.agent_loop.utils.messages import LoopAIMessage, LoopHumanMessage


def test_synthesis_checkpoint_thread_id_is_unique_and_prefixed() -> None:
    parent = "thread-abc"
    a = synthesis_checkpoint_thread_id(parent)
    b = synthesis_checkpoint_thread_id(parent)
    assert a != b
    assert a.startswith(f"{parent}__synth_gc__")
    assert b.startswith(f"{parent}__synth_gc__")


@pytest.mark.asyncio
async def test_generate_synthesis_astream_uses_isolated_thread_and_workspace() -> None:
    """CoreAgent astream must use a fresh thread_id + workspace for checkpointer (IG-302)."""
    captured: dict = {}

    async def recording_astream(graph_input, config=None, **kwargs):  # noqa: ARG001
        captured["config"] = config
        if False:
            yield None

    core = MagicMock()
    core.astream = recording_astream

    classification = ScenarioClassification(
        scenario="general_summary",
        sections=["Summary", "Key Points"],
        contextual_focus=["c1"],
        evidence_emphasis="Use evidence",
    )

    state = LoopState(
        goal="g",
        thread_id="parent-thread",
        workspace="/workspace/repo",
        step_results=[
            StepResult(
                step_id="s1",
                success=True,
                outcome={
                    "type": "generic",
                    "step_input": "run",
                    "output_summary": {"first": "out", "last": "end"},
                },
                error=None,
                duration_ms=1,
                thread_id="parent-thread",
            )
        ],
    )
    plan = MagicMock()

    gen = SynthesisGenerator(MagicMock(), core, soothe_config=None)
    with patch.object(
        SynthesisGenerator,
        "_classify_scenario",
        new_callable=AsyncMock,
        return_value=classification,
    ):
        async for _ in gen.generate_synthesis("g", state, plan):
            pass

    cfg = captured.get("config") or {}
    conf = cfg.get("configurable") or {}
    tid = conf.get("thread_id", "")
    assert tid.startswith("parent-thread__synth_gc__")
    assert tid != "parent-thread"
    assert conf.get("workspace") == "/workspace/repo"


@pytest.mark.asyncio
async def test_generate_synthesis_passes_ledger_messages_before_instruction() -> None:
    """Goal-completion synthesis sends ``loop_messages`` copies then the instruction turn."""
    captured: dict = {}

    async def recording_astream(graph_input, config=None, **kwargs):  # noqa: ARG001
        captured["messages"] = list(graph_input.get("messages") or [])
        if False:
            yield None

    core = MagicMock()
    core.astream = recording_astream

    classification = ScenarioClassification(
        scenario="general_summary",
        sections=["Summary", "Key Points"],
        contextual_focus=["c1"],
        evidence_emphasis="Use evidence",
    )

    ledger = [
        LoopHumanMessage(
            content="Execute: read README",
            thread_id="parent-thread",
            iteration=0,
            phase="execute_step",
        ),
        LoopAIMessage(
            content="README says hello.",
            thread_id="parent-thread",
            iteration=0,
            phase="execute_step",
        ),
    ]
    state = LoopState(
        goal="g",
        thread_id="parent-thread",
        workspace=None,
        loop_messages=ledger,
        step_results=[],
    )
    plan = MagicMock()

    gen = SynthesisGenerator(MagicMock(), core, soothe_config=None)
    with patch.object(
        SynthesisGenerator,
        "_classify_scenario",
        new_callable=AsyncMock,
        return_value=classification,
    ):
        async for _ in gen.generate_synthesis("g", state, plan):
            pass

    msgs = captured.get("messages") or []
    assert len(msgs) == 3
    assert isinstance(msgs[0], LoopHumanMessage)
    assert isinstance(msgs[1], LoopAIMessage)
    assert isinstance(msgs[2], LoopHumanMessage)
    assert msgs[0].content.startswith("Execute:")
    assert "README says hello" in msgs[1].content
    assert msgs[2].phase == "goal_completion"
    assert "Generate a general_summary synthesis" in msgs[2].content
