"""Tests for user-safe synthesis evidence projection."""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from soothe.sloop.engine.scenario_classifier import ScenarioClassification
from soothe.sloop.engine.synthesis_projection import (
    build_synthesis_messages,
    flatten_execute_human_content,
    render_synthesis_system_prompt,
)
from soothe.sloop.prompts.user_message import UserMessageBuilder
from soothe.sloop.state.schemas import LoopState, StepExecutionRecord
from soothe.sloop.utils.messages import LoopAIMessage, LoopHumanMessage


def test_flatten_execute_envelope_extracts_goal() -> None:
    builder = UserMessageBuilder()
    msg = builder.build_execute_step_message(
        "Search the repo for *.yml config",
        instructions="- hint",
    )
    flat = flatten_execute_human_content(msg)
    assert flat == "Search the repo for *.yml config"
    assert "INSTRUCTIONS" not in flat


def test_build_synthesis_message_is_task_only() -> None:
    text = UserMessageBuilder().build_synthesis_message()
    assert text.startswith("TASK:")
    assert "GOAL:" not in text
    assert "INTENT:" not in text
    assert "CONTEXTUAL FOCUS:" not in text
    assert "EVIDENCE EMPHASIS:" not in text
    assert "EVIDENCE:" not in text
    assert "prefer bullets" in text.lower() or "Prefer bullets" in text
    assert "required sections" not in text.lower()
    assert "prior-goal status" in text.lower() or "prior completion" in text.lower()


def test_projection_excludes_plan_phases_from_ledger() -> None:
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

    classification = ScenarioClassification(
        scenario="general_summary",
        sections=["Summary"],
        contextual_focus=["Outcomes"],
        evidence_emphasis="Group by theme",
    )
    msgs = build_synthesis_messages(state, classification, max_chars=50_000)
    assert len(msgs) == 4
    assert isinstance(msgs[0], SystemMessage)
    assert isinstance(msgs[1], LoopHumanMessage)
    assert isinstance(msgs[2], LoopAIMessage)
    assert isinstance(msgs[3], HumanMessage)
    assert msgs[1].content == "Execute: read README"
    assert "README documents the API." in str(msgs[2].content)
    human = msgs[3].content
    assert isinstance(human, str)
    assert human.startswith("TASK:")
    assert "Plan assess context" not in human


def test_system_prompt_includes_user_goal_and_focus() -> None:
    classification = ScenarioClassification(
        scenario="general_summary",
        sections=["Summary"],
        contextual_focus=["Summarize key findings for: count file types"],
        evidence_emphasis="Present key outcomes concisely",
    )
    text = render_synthesis_system_prompt(
        classification,
        user_goal="count all file types of packages",
    )
    assert "count all file types of packages" in text
    assert "Summarize key findings for: count file types" in text
    assert "Present key outcomes concisely" in text
    lowered = text.lower()
    assert "sloop" not in lowered
    assert "ledger" not in lowered
    assert "iteration" not in lowered
    assert "goal completion" not in lowered


def test_build_synthesis_messages_injects_execute_ledger_before_task_human() -> None:
    classification = ScenarioClassification(
        scenario="research_synthesis",
        sections=["Key Findings"],
        contextual_focus=["Sources"],
        evidence_emphasis="Cite outcomes",
    )
    execute_human = LoopHumanMessage(
        content="Execute: gather sources",
        thread_id="t",
        iteration=0,
        phase="execute_step",
    )
    execute_ai = LoopAIMessage(
        content="Found three papers.",
        thread_id="t",
        iteration=0,
        phase="execute_step",
    )
    state = LoopState(
        goal="Research topic X",
        thread_id="t",
        loop_messages=[execute_human, execute_ai],
        step_results=[
            StepExecutionRecord(
                step_id="s1",
                success=True,
                outcome={"type": "generic", "step_input": "x", "output_summary": {}},
                error=None,
                duration_ms=1,
                thread_id="t",
            )
        ],
    )
    msgs = build_synthesis_messages(state, classification, max_chars=50_000)
    assert len(msgs) == 4
    assert isinstance(msgs[0], SystemMessage)
    assert "Research topic X" in str(msgs[0].content)
    assert isinstance(msgs[1], LoopHumanMessage)
    assert isinstance(msgs[2], LoopAIMessage)
    assert isinstance(msgs[3], HumanMessage)
    human = msgs[3].content
    assert isinstance(human, str)
    assert human.startswith("TASK:")
    assert "Found three papers." not in human
    assert "STEP SUMMARIES" not in human
    assert "StrangeLoop" not in human


def test_build_synthesis_messages_system_and_task_only_when_no_ledger() -> None:
    classification = ScenarioClassification(
        scenario="general_summary",
        sections=["Summary"],
        contextual_focus=["Outcomes"],
        evidence_emphasis="Group by theme",
    )
    state = LoopState(goal="Research topic X", thread_id="t")
    msgs = build_synthesis_messages(state, classification, max_chars=50_000)
    assert len(msgs) == 2
    assert isinstance(msgs[0], SystemMessage)
    assert isinstance(msgs[1], HumanMessage)
    assert str(msgs[1].content).startswith("TASK:")


def test_synthesis_system_prompt_includes_agent_instructions(tmp_path) -> None:
    """Goal synthesis inlines AGENTS.md/CLAUDE.md like execute-type prompts."""
    (tmp_path / "AGENTS.md").write_text("# Rules\n\nBe concise in reports.\n", encoding="utf-8")
    classification = ScenarioClassification(
        scenario="general_summary",
        sections=["Summary"],
        contextual_focus=["Outcomes"],
        evidence_emphasis="Group by theme",
    )
    text = render_synthesis_system_prompt(
        classification,
        user_goal="Summarize work",
        workspace=str(tmp_path),
        agent_instructions_max_chars=8000,
    )
    assert "<AGENT_INSTRUCTIONS>" in text
    assert "Be concise in reports." in text


def test_system_prompt_includes_scenario_list() -> None:
    """IG-524: Available scenarios moved to system prompt for caching."""
    classification = ScenarioClassification(
        scenario="general_summary",
        sections=["Summary"],
        contextual_focus=["Outcomes"],
        evidence_emphasis="Group by theme",
    )
    text = render_synthesis_system_prompt(classification, user_goal="g")
    assert "code_architecture_design" in text
    assert "research_synthesis" in text
    assert "general_summary" in text


def test_system_prompt_uses_synthesis_instructions_wrapper_and_anti_echo_rules() -> None:
    classification = ScenarioClassification(
        scenario="general_summary",
        sections=["Summary", "Key Points"],
        contextual_focus=["Outcomes"],
        evidence_emphasis="Group by theme",
    )
    text = render_synthesis_system_prompt(classification, user_goal="analyze gitignore")
    assert "<SYNTHESIS_INSTRUCTIONS>" in text
    assert "</SYNTHESIS_INSTRUCTIONS>" in text
    assert "SYNTHESIS_REPORT" not in text
    assert "Never output `<SYNTHESIS_INSTRUCTIONS>`" in text
    assert "start immediately with the first `##` heading" in text
    assert "Suggested outline" in text
    assert "Required sections" not in text
    assert "Multi-goal loops" in text
    assert "at most one short" in text


def test_system_prompt_empty_sections_asks_model_to_design_outline() -> None:
    """IG-652: heuristic path leaves sections empty; Phase 2 invents outline."""
    classification = ScenarioClassification(
        scenario="general_summary",
        sections=[],
        contextual_focus=["Outcomes"],
        evidence_emphasis="Bullets first",
    )
    text = render_synthesis_system_prompt(classification, user_goal="summarize work")
    assert "design 3–7" in text or "design 3-7" in text
    assert "Suggested outline" not in text


def test_system_prompt_includes_cli_formatting_rules() -> None:
    """IG-552 / IG-652: synthesis system prompt instructs tables, bullets, and mermaid."""
    classification = ScenarioClassification(
        scenario="general_summary",
        sections=["Summary"],
        contextual_focus=["Outcomes"],
        evidence_emphasis="Group by theme",
    )
    text = render_synthesis_system_prompt(classification, user_goal="summarize work")
    assert "Structure and Markdown" in text
    assert "GFM pipe tables" in text
    assert "markdown bullets" in text
    assert "```mermaid" in text
    assert "Prose budget" in text
    assert "content_draft" in text


def test_system_prompt_includes_scenario_format_hint() -> None:
    """IG-552: per-scenario layout hints are injected for the matched scenario."""
    classification = ScenarioClassification(
        scenario="decision_analysis",
        sections=["Context", "Options", "Trade-offs", "Recommendation"],
        contextual_focus=["Compare approaches"],
        evidence_emphasis="Tabulate options",
    )
    text = render_synthesis_system_prompt(classification, user_goal="pick a cache")
    assert 'Scenario-specific layout for "decision_analysis"' in text
    assert "Options comparison" in text
    assert "GFM table" in text
    assert "Bullets/tables first" in text
