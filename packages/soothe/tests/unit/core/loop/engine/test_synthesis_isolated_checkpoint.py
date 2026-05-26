"""Tests for IG-302 synthesis isolated LangGraph checkpoint thread."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from soothe.core.loop.engine.scenario_classifier import ScenarioClassification
from soothe.core.loop.engine.synthesis import (
    SOOTHE_GOAL_SYNTHESIS_CONFIG_KEY,
    SynthesisGenerator,
    synthesis_checkpoint_thread_id,
)
from soothe.core.loop.state.schemas import LoopState, StepResult
from soothe.core.loop.utils.messages import LoopAIMessage, LoopHumanMessage
from soothe.utils.observability import langfuse as langfuse_util


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

    gen = SynthesisGenerator(MagicMock(), core, soothe_config=None)
    with patch.object(
        SynthesisGenerator,
        "_classify_scenario",
        new_callable=AsyncMock,
        return_value=classification,
    ):
        async for _ in gen.generate_synthesis("g", state):
            pass

    cfg = captured.get("config") or {}
    conf = cfg.get("configurable") or {}
    tid = conf.get("thread_id", "")
    assert tid.startswith("parent-thread__synth_gc__")
    assert tid != "parent-thread"
    assert conf.get("workspace") == "/workspace/repo"
    assert conf.get(SOOTHE_GOAL_SYNTHESIS_CONFIG_KEY) is True


@pytest.mark.asyncio
async def test_generate_synthesis_sets_goal_synthesis_langfuse_run_name(monkeypatch) -> None:
    """Phase-2 synthesis uses the same run-name convention as execute-step (IG-377 pattern)."""
    captured: dict = {}

    async def recording_astream(graph_input, config=None, **kwargs):  # noqa: ARG001
        captured["config"] = config
        if False:
            yield None

    core = MagicMock()
    core.astream = recording_astream

    classification = ScenarioClassification(
        scenario="general_summary",
        sections=["Summary"],
        contextual_focus=["c1"],
        evidence_emphasis="Use evidence",
    )

    from soothe.config import SootheConfig
    from soothe.config.models import LangfuseIntegrationConfig, ObservabilityConfig

    obs = ObservabilityConfig(
        langfuse=LangfuseIntegrationConfig(enabled=True, trace_name="soothe-dev"),
    )
    soothe_cfg = SootheConfig(observability=obs)
    handler = MagicMock()
    monkeypatch.setattr(langfuse_util, "_langfuse_callback_handler", lambda _c: handler)

    state = LoopState(
        goal="g",
        thread_id="parent-thread",
        workspace=None,
        step_results=[
            StepResult(
                step_id="s1",
                success=True,
                outcome={"type": "generic", "step_input": "run", "output_summary": {"first": "x"}},
                error=None,
                duration_ms=1,
                thread_id="parent-thread",
            )
        ],
    )

    gen = SynthesisGenerator(MagicMock(), core, soothe_cfg, loop_id="loop-9")
    with patch.object(
        SynthesisGenerator,
        "_classify_scenario",
        new_callable=AsyncMock,
        return_value=classification,
    ):
        async for _ in gen.generate_synthesis("g", state):
            pass

    cfg = captured.get("config") or {}
    assert cfg.get("run_name") == "soothe-dev:goal-synthesis"
    assert (cfg.get("metadata") or {}).get("langfuse_session_id") == "parent-thread"
    assert (cfg.get("metadata") or {}).get("loop_id") == "loop-9"


@pytest.mark.asyncio
async def test_generate_synthesis_uses_projected_context_not_raw_ledger() -> None:
    """Synthesis sends system + projected evidence, excluding plan-phase ledger rows."""
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
        LoopHumanMessage(
            content="Plan assess context",
            thread_id="parent-thread",
            iteration=0,
            phase="plan_assess",
        ),
    ]
    state = LoopState(
        goal="g",
        thread_id="parent-thread",
        workspace=None,
        loop_messages=ledger,
        step_results=[],
    )

    gen = SynthesisGenerator(MagicMock(), core, soothe_config=None)
    with patch.object(
        SynthesisGenerator,
        "_classify_scenario",
        new_callable=AsyncMock,
        return_value=classification,
    ):
        async for _ in gen.generate_synthesis("g", state):
            pass

    msgs = captured.get("messages") or []
    assert len(msgs) == 2
    assert isinstance(msgs[0], SystemMessage)
    assert isinstance(msgs[1], HumanMessage)
    human = msgs[1].content
    assert isinstance(human, str)
    assert "<user_request>" in human
    assert "README says hello" in human
    assert "Plan assess context" not in human
    assert "AgentLoop" not in human.lower()
