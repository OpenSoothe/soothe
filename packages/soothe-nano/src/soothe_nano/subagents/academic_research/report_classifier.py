"""Adaptive academic report scenario classification."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_SCENARIO_SECTIONS: dict[str, list[str]] = {
    "literature_review": [
        "Scope",
        "Executive Summary",
        "Key Papers",
        "Themes",
        "Gaps",
        "References",
    ],
    "paper_comparison": [
        "Scope",
        "Context",
        "Comparison Table",
        "Methods",
        "Findings",
        "Recommendation",
        "References",
    ],
    "method_survey": [
        "Scope",
        "Overview",
        "Methods Compared",
        "Strengths and Limits",
        "References",
    ],
    "citation_analysis": [
        "Scope",
        "Question",
        "Evidence",
        "Synthesis",
        "References",
    ],
    "general_academic": [
        "Scope",
        "Executive Summary",
        "Key Findings",
        "Open Questions",
        "References",
    ],
}

_CLASSIFY_PROMPT = """\
Classify this academic literature research topic and choose the best report scenario.

Topic: {topic}
Effort: {effort}
Loops completed: {loop_count}
Sources gathered: {source_count}

Scenarios: literature_review, paper_comparison, method_survey, citation_analysis, general_academic

Return ONLY raw JSON:
{{"scenario": "...",
  "sections": ["Section1", "Section2"],
  "contextual_focus": ["focus1", "focus2"],
  "evidence_emphasis": "one sentence"}}"""


class ReportScenarioClassification(BaseModel):
    scenario: str = "general_academic"
    sections: list[str] = Field(
        default_factory=lambda: list(_SCENARIO_SECTIONS["general_academic"])
    )
    contextual_focus: list[str] = Field(default_factory=list)
    evidence_emphasis: str = "Weight peer-reviewed and preprint sources with clear citations."


def _parse_json(content: str) -> dict[str, Any] | None:
    text = (content or "").strip()
    fence = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL | re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def fallback_classification(topic: str) -> ReportScenarioClassification:
    lower = topic.lower()
    if " vs " in lower or " versus " in lower or "compare" in lower:
        scenario = "paper_comparison"
    elif "literature review" in lower or "survey" in lower:
        scenario = "literature_review"
    elif "method" in lower or "approach" in lower:
        scenario = "method_survey"
    elif "cite" in lower or "citation" in lower:
        scenario = "citation_analysis"
    else:
        scenario = "general_academic"
    return ReportScenarioClassification(
        scenario=scenario,
        sections=list(_SCENARIO_SECTIONS[scenario]),
        contextual_focus=[topic[:120]],
    )


async def classify_report_scenario(
    model: Any,
    *,
    topic: str,
    effort: str,
    loop_count: int,
    source_count: int,
    soothe_config: Any | None = None,
    timeout_sec: float = 30.0,
) -> ReportScenarioClassification:
    from soothe_deepagents.middleware.llm_rate_limit import EnhancedTimeoutError

    from soothe_nano.utils.llm.invoke_policy import (
        await_with_llm_call_policy,
        llm_rate_limit_config_from,
    )

    prompt = _CLASSIFY_PROMPT.format(
        topic=topic[:500],
        effort=effort,
        loop_count=loop_count,
        source_count=source_count,
    )
    llm_config = llm_rate_limit_config_from(soothe_config).model_copy(
        update={
            "call_timeout_seconds": int(timeout_sec),
            "call_timeout_max_seconds": int(timeout_sec),
        }
    )

    async def _call() -> Any:
        return await model.ainvoke([{"role": "user", "content": prompt}])

    try:
        resp = await await_with_llm_call_policy(_call, config=llm_config)
        content = str(getattr(resp, "content", resp) or "")
        parsed = _parse_json(content)
        if not parsed:
            return fallback_classification(topic)
        scenario = str(parsed.get("scenario", "general_academic"))
        sections = parsed.get("sections") or _SCENARIO_SECTIONS.get(
            scenario, _SCENARIO_SECTIONS["general_academic"]
        )
        return ReportScenarioClassification(
            scenario=scenario,
            sections=[str(s) for s in sections],
            contextual_focus=[str(x) for x in parsed.get("contextual_focus", [])[:3]],
            evidence_emphasis=str(
                parsed.get(
                    "evidence_emphasis",
                    "Weight peer-reviewed and preprint sources with clear citations.",
                )
            ),
        )
    except (EnhancedTimeoutError, TimeoutError, Exception):
        logger.debug("Academic report classification failed, using fallback", exc_info=True)
        return fallback_classification(topic)
