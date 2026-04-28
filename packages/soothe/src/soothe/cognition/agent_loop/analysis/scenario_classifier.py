"""Scenario classifier for synthesis generation (RFC-616, IG-300).

Determines appropriate synthesis scenario from goal + intent + execution pattern
using fast model with structured output.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, model_validator

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel

    from soothe.cognition.agent_loop.state.schemas import LoopState

logger = logging.getLogger(__name__)

# Built-in scenario templates (minimal: scenario name + sections only)
BUILTIN_SCENARIOS = {
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

    # Calculate evidence volume (character count from successful steps)
    evidence_volume = 0
    for result in state.step_results:
        if result.success:
            evidence_str = result.to_evidence_string(truncate=False)
            evidence_volume += len(evidence_str)

    return {
        "total_steps": total_steps,
        "successful_steps": successful_steps,
        "step_types": step_types,
        "tools_used": tools_used,
        "evidence_volume": evidence_volume,
    }


def _build_classifier_prompt(
    goal: str,
    intent_type: str,
    task_complexity: str,
    execution_summary: dict,
) -> str:
    """Build classifier prompt for scenario classification (IG-300).

    Args:
        goal: User's goal description.
        intent_type: Intent classification (chitchat/quiz/thread_continuation/new_goal).
        task_complexity: Task complexity (chitchat/quiz/medium/complex).
        execution_summary: Execution metadata dict.

    Returns:
        Complete classifier prompt text.
    """
    # Format built-in scenarios list
    scenarios_list = "\n".join(
        f"{i + 1}. {name} - {desc}"
        for i, (name, sections) in enumerate(BUILTIN_SCENARIOS.items())
        for desc in [_get_scenario_description(name)]
    )

    return f"""Analyze the goal and execution pattern to determine the most appropriate synthesis scenario.

GOAL: {goal}
INTENT: {intent_type} (complexity: {task_complexity})

EXECUTION SUMMARY:
- Total steps: {execution_summary["total_steps"]}
- Successful: {execution_summary["successful_steps"]}
- Step types: {execution_summary["step_types"]}
- Tools used: {execution_summary["tools_used"]}
- Evidence volume: {execution_summary["evidence_volume"]} chars

AVAILABLE BUILT-IN SCENARIOS:
{scenarios_list}

TASK:
1. Match goal + execution pattern to a built-in scenario if appropriate
2. If novel situation not covered above → return "custom" scenario with designed sections
3. Generate 2-3 contextual_focus areas specific to THIS goal (not generic)
4. Generate evidence_emphasis instruction for how to use execution results effectively

OUTPUT FORMAT (JSON):
{{
    "scenario": "<scenario_name from above OR custom>",
    "sections": ["<section1>", "<section2>", "<section3>", ...],
    "contextual_focus": [
        "<specific focus area 1 for this goal>",
        "<specific focus area 2 for this goal>",
        "<specific focus area 3 for this goal>"
    ],
    "evidence_emphasis": "<instruction for using evidence>"
}}

EXAMPLE OUTPUT:
{
        "scenario": "code_architecture_design",
    "sections": ["Summary", "Component Analysis", "Key Findings", "Recommendations"],
    "contextual_focus": [
        "Compare monolithic vs modular approach",
        "Highlight dependency bottlenecks",
        "Quantify component complexity metrics"
    ],
    "evidence_emphasis": "Include module relationship diagrams and code snippets showing key dependencies"
}

ANOTHER EXAMPLE (custom):
{
        "scenario": "custom",
    "sections": ["Recipe Overview", "Ingredient Analysis", "Cooking Instructions", "Recommendations"],
    "contextual_focus": [
        "Group recipes by cuisine and difficulty",
        "Identify common ingredient substitutions",
        "Provide time-based recommendations"
    ],
    "evidence_emphasis": "Include full recipe content, ingredient lists, and cooking times from web search results"
}"""


def _get_scenario_description(scenario_name: str) -> str:
    """Get brief description for built-in scenario (IG-300).

    Args:
        scenario_name: Built-in scenario name.

    Returns:
        Brief description of scenario purpose.
    """
    descriptions = {
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
    return descriptions.get(scenario_name, "General synthesis")


async def classify_synthesis_scenario(
    goal: str,
    state: LoopState,
    llm_client: BaseChatModel,
) -> ScenarioClassification:
    """Classify synthesis scenario from goal + intent + execution pattern (IG-300).

    Uses fast model to analyze goal context and execution pattern, then suggests
    appropriate scenario structure with contextual focus and evidence emphasis.

    Args:
        goal: User's goal description.
        state: Loop state with intent classification and step results.
        llm_client: Fast model for classification (from config).

    Returns:
        ScenarioClassification with scenario, sections, focus, emphasis.

    Raises:
        No exceptions - returns fallback classification on any failure.
    """
    # Extract intent classification
    intent_type = "new_goal"
    task_complexity = "medium"
    if state.intent and hasattr(state.intent, "intent_type"):
        intent_type = state.intent.intent_type
        task_complexity = getattr(state.intent, "task_complexity", "medium")

    # Extract execution summary
    execution_summary = _extract_execution_summary(state)

    # Build classifier prompt
    prompt = _build_classifier_prompt(goal, intent_type, task_complexity, execution_summary)

    # Call LLM with structured output
    try:
        from langchain_core.messages import HumanMessage

        response = await llm_client.ainvoke([HumanMessage(content=prompt)])

        # Parse JSON response into ScenarioClassification
        classification = ScenarioClassification.parse_raw(response.content)

        logger.info(
            "Scenario classifier: scenario=%s sections=%d focus_items=%d",
            classification.scenario,
            len(classification.sections),
            len(classification.contextual_focus),
        )

        return classification

    except Exception:
        logger.warning("Scenario classification failed, using fallback", exc_info=True)
        return ScenarioClassification(
            scenario="general_summary",
            sections=BUILTIN_SCENARIOS["general_summary"],
            contextual_focus=["Provide concise summary of goal completion"],
            evidence_emphasis="Use any available tool results or AI responses",
        )
