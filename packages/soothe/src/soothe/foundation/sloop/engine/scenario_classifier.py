"""Scenario classifier for synthesis generation (RFC-616, IG-300).

Determines appropriate synthesis scenario from goal + intent + execution pattern
using fast model with structured output.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, model_validator

from soothe.foundation.sloop.prompts.fragments import (
    SCENARIO_CLASSIFIER_SYSTEM_FRAGMENT,
    SCENARIO_CLASSIFIER_USER_FRAGMENT,
)

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel

    from soothe.foundation.sloop.state.schemas import LoopState

from soothe.config.models import ScenarioRulesConfig

logger = logging.getLogger(__name__)

_DEFAULT_SCENARIO_RULES = ScenarioRulesConfig()

# Built-in scenario templates with descriptions
BUILTIN_SCENARIOS: dict[str, list[str]] = {
    "code_architecture_design": [
        "Summary",
        "Component Analysis",
        "Key Findings",
        "Recommendations",
    ],
    "code_implementation_design": [
        "Approach",
        "Implementation Details",
        "Code Examples",
        "Usage Guide",
    ],
    "research_synthesis": [
        "Executive Summary",
        "Key Findings",
        "Source Analysis",
        "Conclusions",
    ],
    "travel_activity_plan": [
        "Overview",
        "Itinerary",
        "Logistics",
        "Recommendations",
    ],
    "tutorial_guide": [
        "Introduction",
        "Prerequisites",
        "Steps",
        "Tips",
    ],
    "analysis_report": [
        "Executive Summary",
        "Metrics/Findings",
        "Trends",
        "Recommendations",
    ],
    "investigation_summary": [
        "Problem Statement",
        "Investigation Process",
        "Findings",
        "Resolution",
    ],
    "decision_analysis": [
        "Context",
        "Options",
        "Trade-offs",
        "Recommendation",
    ],
    "content_draft": [
        "Introduction",
        "Body",
        "Conclusion",
    ],
    "general_summary": [
        "Summary",
        "Key Points",
    ],
}

# Per-scenario CLI layout hints for goal-completion synthesis (IG-552 Phase 1).
# Markdown tables and bullets render in Rich TUI today; Mermaid fences are
# preserved as source until a terminal diagram renderer lands (Phase 3).
SCENARIO_FORMAT_HINTS: dict[str, str] = {
    "code_architecture_design": (
        "Component inventory: GFM table (Name | Role | Location). "
        "Key findings and recommendations: bullet lists. "
        "Main request/data/control flow: ```mermaid flowchart when evidence supports it."
    ),
    "code_implementation_design": (
        "APIs, signatures, or config keys: GFM table. "
        "Patterns, usage, and caveats: bullet lists. "
        "Call or deployment sequence: ```mermaid sequenceDiagram when helpful."
    ),
    "research_synthesis": (
        "Source comparison: GFM table (Source | Finding | Confidence). "
        "Discoveries and conclusions: bullet lists."
    ),
    "travel_activity_plan": (
        "Itinerary: GFM table (Day/Time | Activity | Location | Notes). "
        "Tips and recommendations: bullet lists."
    ),
    "tutorial_guide": (
        "Prerequisites or checklist items: GFM table or bullets. "
        "Procedure: numbered or bullet steps. "
        "Optional overview flow: ```mermaid flowchart."
    ),
    "analysis_report": (
        "Metrics and measurements: GFM table (Metric | Value | Notes). "
        "Trends and recommendations: bullet lists."
    ),
    "investigation_summary": (
        "Symptom/cause matrix: GFM table (Symptom | Cause | Status). "
        "Investigation steps and resolution: bullet lists. "
        "Repro or request path: ```mermaid sequenceDiagram when evidence supports it."
    ),
    "decision_analysis": (
        "Options comparison: GFM table (Option | Pros | Cons | Fit). "
        "Recommendation rationale: bullet lists."
    ),
    "content_draft": (
        "Use short paragraphs for narrative sections; bullet lists for outlines or key beats."
    ),
    "general_summary": ("Brief summary paragraph; Key Points as a bullet list (3–5 items)."),
    "custom": (
        "Use GFM tables for comparisons or inventories; bullets for lists of 3+ items; "
        "```mermaid diagrams for workflows when a diagram clarifies structure."
    ),
}

_SCENARIO_DESCRIPTIONS: dict[str, str] = {
    "code_architecture_design": "System/module structure analysis",
    "code_implementation_design": "Concrete implementation patterns and examples",
    "research_synthesis": "Multi-source information gathering and findings",
    "travel_activity_plan": "Structured planning for trips, events, activities",
    "tutorial_guide": "Step-by-step instructional content",
    "analysis_report": "Data/metrics/trends analysis with recommendations",
    "investigation_summary": "Problem/troubleshooting investigation process",
    "decision_analysis": "Options comparison with trade-offs",
    "content_draft": "Blog, documentation, proposal, email drafts",
    "general_summary": "Simple summarization fallback",
}

_JSON_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)


def format_hint_for_scenario(scenario: str) -> str:
    """Return CLI layout hint for a synthesis scenario name (IG-552)."""
    return SCENARIO_FORMAT_HINTS.get(scenario, SCENARIO_FORMAT_HINTS["custom"])


class ScenarioClassification(BaseModel):
    """Scenario classification result for synthesis generation (IG-300).

    Produced by ScenarioClassifier from goal + intent + execution pattern.
    Guides Phase 2 synthesis with structure + focus + evidence usage.
    """

    scenario: str = Field(description="Built-in scenario name or 'custom' for novel cases")
    sections: list[str] = Field(description="Section names for synthesis structure")
    contextual_focus: list[str] = Field(
        description="2-3 specific focus areas for this goal (not generic)"
    )
    evidence_emphasis: str = Field(description="How to use execution evidence in synthesis")

    @model_validator(mode="after")
    def validate_sections(self) -> ScenarioClassification:
        """Ensure sections are provided."""
        if not self.sections:
            raise ValueError("sections must be provided")
        return self


def _extract_execution_summary(state: LoopState) -> dict:
    """Extract execution metadata from state step results (IG-300).

    Args:
        state: Loop state with step_results.

    Returns:
        Execution summary dict with total_steps, successful_steps,
        step_types, tools_used, evidence_volume.
    """
    total_steps = len(state.step_results)
    successful_steps = sum(1 for r in state.step_results if r.success)

    step_types = []
    tools_used = []
    for result in state.step_results:
        outcome_type = result.outcome.get("type", "unknown")
        step_types.append(outcome_type)

        # Extract tools from outcome metadata
        tool_name = result.outcome.get("tool_name")
        if tool_name:
            tools_used.append(tool_name)

    # Rough character scale for routing (truncate=True avoids duplicating ledger-scale blobs).
    evidence_volume = 0
    for result in state.step_results:
        if result.success:
            evidence_volume += len(result.to_evidence_string(truncate=True))

    return {
        "total_steps": total_steps,
        "successful_steps": successful_steps,
        "step_types": step_types,
        "tools_used": tools_used,
        "evidence_volume": evidence_volume,
    }


def _build_classifier_system_prompt() -> str:
    """Build system prompt with task instructions, scenario list, and output schema."""
    scenarios_list = "\n".join(
        f"{i + 1}. {name} - {_SCENARIO_DESCRIPTIONS.get(name, 'General synthesis')}"
        for i, name in enumerate(BUILTIN_SCENARIOS.keys())
    )
    return SCENARIO_CLASSIFIER_SYSTEM_FRAGMENT.format(scenarios_list=scenarios_list)


def _build_classifier_user_prompt(
    goal: str,
    intent_type: str,
    task_complexity: str,
    execution_summary: dict,
) -> str:
    """Build per-request user prompt with goal, intent, and execution summary."""
    return SCENARIO_CLASSIFIER_USER_FRAGMENT.format(
        goal=goal,
        intent_type=intent_type,
        task_complexity=task_complexity,
        total_steps=execution_summary["total_steps"],
        successful_steps=execution_summary["successful_steps"],
        step_types=execution_summary["step_types"],
        tools_used=execution_summary["tools_used"],
        evidence_volume=execution_summary["evidence_volume"],
    )


def _coerce_response_text(content: object) -> str:
    """Normalize model response content into a parseable text payload."""
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        chunks: list[str] = []
        for block in content:
            if isinstance(block, str):
                chunks.append(block)
            elif isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str):
                    chunks.append(text)
        if chunks:
            return "".join(chunks)

    return str(content)


def _iter_json_candidates(raw_text: str) -> list[str]:
    """Yield likely JSON payload candidates from model response text."""
    candidates: list[str] = []
    text = raw_text.strip()
    if text:
        candidates.append(text)

    # Most common failure mode: fenced markdown JSON block.
    for match in _JSON_FENCE_PATTERN.finditer(raw_text):
        fenced = match.group(1).strip()
        if fenced:
            candidates.append(fenced)

    # If prose surrounds JSON, take first/last object envelope.
    first_brace = raw_text.find("{")
    last_brace = raw_text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        candidates.append(raw_text[first_brace : last_brace + 1].strip())

    # Preserve order, remove duplicates.
    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate and candidate not in seen:
            seen.add(candidate)
            deduped.append(candidate)
    return deduped


def _parse_classification_response(content: object) -> ScenarioClassification:
    """Parse classification response from raw/fenced/wrapped JSON content."""
    response_text = _coerce_response_text(content)
    last_error: Exception | None = None

    for candidate in _iter_json_candidates(response_text):
        try:
            return ScenarioClassification.model_validate_json(candidate)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            continue

    if last_error is not None:
        raise last_error

    raise ValueError("Empty scenario classification response")


def _heuristic_classify(
    goal: str,
    intent_type: str,
    execution_summary: dict,
    *,
    scenario_rules: ScenarioRulesConfig | None = None,
) -> ScenarioClassification | None:
    """Config-driven fast-path classification that skips the LLM call."""
    rules = scenario_rules or _DEFAULT_SCENARIO_RULES
    total_steps = execution_summary["total_steps"]
    successful_steps = execution_summary["successful_steps"]
    step_types = execution_summary["step_types"]
    evidence_volume = execution_summary["evidence_volume"]

    if rules.skip_llm_when_single_step and total_steps <= 1:
        return ScenarioClassification(
            scenario="general_summary",
            sections=list(BUILTIN_SCENARIOS["general_summary"]),
            contextual_focus=[f"Summarize result for: {goal[:120]}"],
            evidence_emphasis="Present the single step outcome directly",
        )

    if rules.skip_llm_when_all_failed and successful_steps == 0 and total_steps > 0:
        return ScenarioClassification(
            scenario="investigation_summary",
            sections=list(BUILTIN_SCENARIOS["investigation_summary"]),
            contextual_focus=["Identify root cause of failures", "Summarize troubleshooting steps"],
            evidence_emphasis="Group error patterns; highlight root causes",
        )

    has_tool = any(t not in ("unknown", "llm_call") for t in step_types)
    if total_steps >= rules.high_step_count_threshold and has_tool:
        return ScenarioClassification(
            scenario="analysis_report",
            sections=list(BUILTIN_SCENARIOS["analysis_report"]),
            contextual_focus=[
                f"Aggregate findings across {total_steps} steps",
                "Highlight key metrics and outcomes",
            ],
            evidence_emphasis="Summarize tool outputs by concern, not chronologically",
        )

    if evidence_volume < rules.low_evidence_volume_threshold and intent_type == "agentic":
        return ScenarioClassification(
            scenario="general_summary",
            sections=list(BUILTIN_SCENARIOS["general_summary"]),
            contextual_focus=[f"Summarize key findings for: {goal[:120]}"],
            evidence_emphasis="Present key outcomes concisely",
        )

    # Could not confidently classify — fall through to LLM
    return None


async def classify_synthesis_scenario(
    goal: str,
    state: LoopState,
    llm_client: BaseChatModel,
    *,
    soothe_config: Any | None = None,
) -> ScenarioClassification:
    """Classify synthesis scenario from goal + intent + execution pattern (IG-300).

    Uses a heuristic fast-path for obvious cases, then falls back to the LLM
    for ambiguous ones.  The LLM call uses the supplied ``llm_client`` which
    should be a *fast* model (not a reasoning/think model).

    Args:
        goal: User's goal description.
        state: Loop state with intent classification and step results.
        llm_client: Fast model for classification (from config).
        soothe_config: Optional SootheConfig for Langfuse tracing.

    Returns:
        ScenarioClassification with scenario, sections, focus, emphasis.

    Raises:
        No exceptions - returns fallback classification on any failure.
    """
    # intent_type is always "agentic" after RFC-630 3-class intake
    intent_type = "agentic"
    task_complexity = "medium"
    if state.intent:
        task_complexity = getattr(state.intent, "task_complexity", "medium")

    # Extract execution summary
    execution_summary = _extract_execution_summary(state)

    scenario_rules = None
    if soothe_config is not None:
        scenario_rules = getattr(
            getattr(getattr(soothe_config, "agent", None), "loop", None),
            "rules",
            None,
        )
        if scenario_rules is not None:
            scenario_rules = scenario_rules.scenario

    heuristic = _heuristic_classify(
        goal,
        intent_type,
        execution_summary,
        scenario_rules=scenario_rules,
    )
    if heuristic is not None:
        logger.info(
            "Scenario classifier (heuristic): scenario=%s steps=%d",
            heuristic.scenario,
            execution_summary["total_steps"],
        )
        return heuristic

    # Build system + user prompts
    system_prompt = _build_classifier_system_prompt()
    user_prompt = _build_classifier_user_prompt(
        goal, intent_type, task_complexity, execution_summary
    )

    # Call LLM with structured output
    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        from soothe.utils.llm.invoke_policy import (
            await_with_llm_call_policy,
            llm_rate_limit_config_from,
        )
        from soothe.utils.observability.langfuse import SootheLangfuse

        invoke_config = SootheLangfuse(soothe_config).traced_llm(
            purpose="scenario_classify",
            component="synthesis.scenario_classifier",
            phase="post-loop",
            session_id=getattr(state, "thread_id", None),
            run_name="soothe:scenario-classify",
        )

        async def _invoke() -> Any:
            return await llm_client.ainvoke(
                [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)],
                config=invoke_config,
            )

        response = await await_with_llm_call_policy(
            _invoke,
            config=llm_rate_limit_config_from(soothe_config),
            thread_id=getattr(state, "thread_id", None),
        )

        # Parse JSON response into ScenarioClassification
        classification = _parse_classification_response(response.content)

        logger.info(
            "Scenario classifier (llm): scenario=%s sections=%d focus_items=%d",
            classification.scenario,
            len(classification.sections),
            len(classification.contextual_focus),
        )

        return classification

    except Exception:
        logger.warning("Scenario classification failed, using fallback", exc_info=True)
        return ScenarioClassification(
            scenario="general_summary",
            sections=list(BUILTIN_SCENARIOS["general_summary"]),
            contextual_focus=["Provide concise summary of goal completion"],
            evidence_emphasis="Use any available tool results or AI responses",
        )
