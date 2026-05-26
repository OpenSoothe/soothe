"""Tests for user-safe synthesis evidence projection."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from soothe.core.loop.engine.scenario_classifier import ScenarioClassification
from soothe.core.loop.engine.synthesis_projection import (
    build_synthesis_messages,
    flatten_execute_human_content,
    project_synthesis_user_context,
    render_synthesis_system_prompt,
)
from soothe.core.loop.state.schemas import LoopState, StepResult
from soothe.core.loop.utils.messages import LoopAIMessage, LoopHumanMessage
from soothe.core.prompts.user_envelope import (
    build_execute_step_envelope,
    build_plan_context_envelope,
)


def test_flatten_execute_envelope_extracts_user_query() -> None:
    envelope = build_execute_step_envelope(
        "Search the repo for *.yml config",
        execution_hints="hint",
    )
    flat = flatten_execute_human_content(envelope)
    assert flat == "Search the repo for *.yml config"
    assert "GOAL_PROGRESS" not in flat
    assert "EXECUTION_HINTS" not in flat


def test_projection_excludes_plan_phases() -> None:
    plan_human = LoopHumanMessage(
        content=build_plan_context_envelope("Analyze latency", iteration=1, max_iterations=3),
        thread_id="t",
        iteration=0,
        phase="plan_assess",
    )
    execute_human = LoopHumanMessage(
        content="Execute: read README",
        thread_id="t",
        iteration=0,
        phase="execute_step",
    )
    execute_ai = LoopAIMessage(
        content="README documents the API.",
        thread_id="t",
        iteration=0,
        phase="execute_step",
    )
    state = LoopState(
        goal="Analyze latency",
        thread_id="t",
        loop_messages=[plan_human, execute_human, execute_ai],
    )
    ctx = project_synthesis_user_context(state)
    assert "GOAL_PROGRESS" not in ctx.evidence_body
    assert "Execute iteration" not in ctx.evidence_body
    assert "README documents" in ctx.evidence_body
    assert "read README" in ctx.evidence_body or "Execute:" in ctx.evidence_body


def test_projection_includes_step_summaries() -> None:
    state = LoopState(
        goal="run tests",
        thread_id="t",
        step_results=[
            StepResult(
                step_id="s1",
                success=True,
                outcome={"type": "generic", "step_input": "x", "output_summary": {}},
                error=None,
                duration_ms=1,
                thread_id="t",
            )
        ],
    )
    ctx = project_synthesis_user_context(state)
    assert "<step_summaries>" in ctx.evidence_body
    assert 'step id="s1"' in ctx.evidence_body


def test_system_prompt_has_no_orchestration_vocabulary() -> None:
    classification = ScenarioClassification(
        scenario="general_summary",
        sections=["Summary"],
        contextual_focus=["Outcomes"],
        evidence_emphasis="Group by theme",
    )
    text = render_synthesis_system_prompt(classification)
    lowered = text.lower()
    assert "agentloop" not in lowered
    assert "ledger" not in lowered
    assert "iteration" not in lowered
    assert "goal completion" not in lowered


def test_build_synthesis_messages_uses_system_and_human_only() -> None:
    classification = ScenarioClassification(
        scenario="research_synthesis",
        sections=["Key Findings"],
        contextual_focus=["Sources"],
        evidence_emphasis="Cite outcomes",
    )
    state = LoopState(goal="Research topic X", thread_id="t")
    msgs = build_synthesis_messages(state, classification, max_chars=50_000)
    assert len(msgs) == 2
    assert isinstance(msgs[0], SystemMessage)
    assert isinstance(msgs[1], HumanMessage)
    human = msgs[1].content
    assert isinstance(human, str)
    assert "<user_request>" in human
    assert "Research topic X" in human
    assert "<execution_evidence>" in human
    assert "AgentLoop" not in human
