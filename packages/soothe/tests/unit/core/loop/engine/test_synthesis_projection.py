"""Tests for user-safe synthesis evidence projection."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from soothe.foundation.loop.engine.scenario_classifier import ScenarioClassification
from soothe.foundation.loop.engine.synthesis_projection import (
    build_synthesis_messages,
    flatten_execute_human_content,
    project_synthesis_user_context,
    render_synthesis_system_prompt,
)
from soothe.foundation.loop.prompts.user_message import UserMessageBuilder
from soothe.foundation.loop.state.schemas import LoopState, StepResult
from soothe.foundation.loop.utils.messages import LoopAIMessage, LoopHumanMessage


def test_flatten_execute_envelope_extracts_goal() -> None:
    builder = UserMessageBuilder()
    msg = builder.build_execute_step_message(
        "Search the repo for *.yml config",
        execution_hints="hint",
    )
    flat = flatten_execute_human_content(msg)
    assert flat == "Search the repo for *.yml config"
    assert "EXECUTION HINTS" not in flat


def test_projection_excludes_plan_phases() -> None:
    builder = UserMessageBuilder()
    plan_human = LoopHumanMessage(
        content=builder.build_plan_assess_message(goal="Analyze latency"),
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
    assert "GOAL:" not in ctx.evidence_body
    assert "README documents" in ctx.evidence_body


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
    assert "STEP SUMMARIES:" in ctx.evidence_body
    assert "[Step s1]" in ctx.evidence_body


def test_system_prompt_has_no_orchestration_vocabulary() -> None:
    classification = ScenarioClassification(
        scenario="general_summary",
        sections=["Summary"],
        contextual_focus=["Outcomes"],
        evidence_emphasis="Group by theme",
    )
    text = render_synthesis_system_prompt(classification)
    lowered = text.lower()
    assert "sloop" not in lowered
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
    assert "GOAL:" in human
    assert "Research topic X" in human
    assert "EVIDENCE:" in human or "STEP SUMMARIES:" in human
    assert "StrangeLoop" not in human
    # IG-524: EXECUTION SUMMARY and AVAILABLE BUILT-IN SCENARIOS removed from user message
    assert "EXECUTION SUMMARY:" not in human
    assert "AVAILABLE BUILT-IN SCENARIOS:" not in human


def test_transcript_uses_standard_conversation_markers() -> None:
    """IG-524: Transcript uses USER:/AI: instead of [Task]/[Finding]."""
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
        goal="Analyze code",
        thread_id="t",
        loop_messages=[execute_human, execute_ai],
    )
    ctx = project_synthesis_user_context(state)
    # IG-524: Standard markers USER:/AI: instead of [Task]/[Finding]
    assert "USER: Execute: read README" in ctx.evidence_body
    assert "AI: README documents the API." in ctx.evidence_body
    # Legacy markers removed
    assert "[Task]" not in ctx.evidence_body
    assert "[Finding]" not in ctx.evidence_body


def test_system_prompt_includes_scenario_list() -> None:
    """IG-524: Available scenarios moved to system prompt for caching."""
    classification = ScenarioClassification(
        scenario="general_summary",
        sections=["Summary"],
        contextual_focus=["Outcomes"],
        evidence_emphasis="Group by theme",
    )
    text = render_synthesis_system_prompt(classification)
    # IG-524: Scenario list in system prompt (not user message)
    assert "code_architecture_design" in text
    assert "research_synthesis" in text
    assert "general_summary" in text
