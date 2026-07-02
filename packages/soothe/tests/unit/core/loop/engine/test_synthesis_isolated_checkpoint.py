"""Tests for IG-302 synthesis isolated LangGraph checkpoint thread."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from soothe.foundation.sloop.engine.scenario_classifier import ScenarioClassification
from soothe.foundation.sloop.engine.synthesis import (
    SOOTHE_GOAL_SYNTHESIS_CONFIG_KEY,
    SynthesisGenerator,
    synthesis_checkpoint_thread_id,
)
from soothe.foundation.sloop.state.schemas import LoopState, StepResult
from soothe.foundation.sloop.utils.messages import LoopAIMessage, LoopHumanMessage


def test_synthesis_checkpoint_thread_id_is_unique_and_prefixed() -> None:
    parent = "thread-abc"
    a = synthesis_checkpoint_thread_id(parent)
    b = synthesis_checkpoint_thread_id(parent)
    assert a != b
    assert a.startswith(f"{parent}__synth_gc__")
    assert b.startswith(f"{parent}__synth_gc__")


class _RecordingLlm:
    """Minimal LLM stand-in; avoids MagicMock swallowing ``astream`` assignments."""

    def __init__(self, captured: dict) -> None:
        self._captured = captured

    def astream(self, messages, config=None, **kwargs):  # noqa: ANN001
        async def _stream():
            self._captured["messages"] = list(messages)
            self._captured["config"] = config
            if False:  # pragma: no cover — async generator
                yield None

        return _stream()


def _recording_llm(captured: dict) -> _RecordingLlm:
    return _RecordingLlm(captured)


@pytest.mark.asyncio
async def test_generate_synthesis_astream_uses_isolated_thread_and_workspace() -> None:
    """Synthesis LLM astream must use a fresh thread_id + workspace for checkpointer (IG-302)."""
    captured: dict = {}
    llm = _recording_llm(captured)

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

    gen = SynthesisGenerator(llm, MagicMock(), soothe_config=None)
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
    llm = _recording_llm(captured)

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
    monkeypatch.setattr(
        "soothe.utils.observability.langfuse._merge.cached_langfuse_callback_handler",
        lambda _c: handler,
    )

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

    gen = SynthesisGenerator(llm, MagicMock(), soothe_cfg, loop_id="loop-9")
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
    llm = _recording_llm(captured)

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

    gen = SynthesisGenerator(llm, MagicMock(), soothe_config=None)
    with patch.object(
        SynthesisGenerator,
        "_classify_scenario",
        new_callable=AsyncMock,
        return_value=classification,
    ):
        async for _ in gen.generate_synthesis("g", state):
            pass

    msgs = captured.get("messages") or []
    assert len(msgs) == 4
    assert isinstance(msgs[0], SystemMessage)
    assert isinstance(msgs[1], LoopHumanMessage)
    assert isinstance(msgs[2], LoopAIMessage)
    assert isinstance(msgs[3], HumanMessage)
    assert "README says hello" in str(msgs[2].content)
    human = msgs[3].content
    assert isinstance(human, str)
    assert human.startswith("TASK:")
    assert "Plan assess context" not in human
    assert "StrangeLoop" not in human.lower()
