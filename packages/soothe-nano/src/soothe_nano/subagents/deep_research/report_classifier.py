"""Adaptive report scenario classification for deep_research."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_SCENARIO_SECTIONS: dict[str, list[str]] = {
    "landscape_survey": [
        "Scope",
        "Executive Summary",
        "Landscape",
        "Key Players",
        "Trends",
        "References",
    ],
    "how_to_guide": [
        "Scope",
        "Overview",
        "Prerequisites",
        "Steps",
        "Pitfalls",
        "References",
    ],
    "comparison": [
        "Scope",
        "Context",
        "Comparison Table",
        "Trade-offs",
        "Recommendation",
        "References",
    ],
    "fact_check": [
        "Scope",
        "Claim",
        "Evidence For",
        "Evidence Against",
        "Verdict",
        "References",
    ],
    "general_research": [
        "Scope",
        "Executive Summary",
        "Key Findings",
        "Open Questions",
        "References",
    ],
}

_CLASSIFY_PROMPT = """\
Classify this public web research topic and choose the best report scenario.

Topic: {topic}
Effort: {effort}
Loops completed: {loop_count}
Sources gathered: {source_count}

Scenarios: landscape_survey, how_to_guide, comparison, fact_check, general_research

Return ONLY raw JSON:
{{"scenario": "...",
  "sections": ["Section1", "Section2"],
  "contextual_focus": ["focus1", "focus2"],
  "evidence_emphasis": "one sentence"}}"""


class ReportScenarioClassification(BaseModel):
    """Report structure for synthesis."""

    scenario: str = "general_research"
    sections: list[str] = Field(
        default_factory=lambda: list(_SCENARIO_SECTIONS["general_research"])
    )
    contextual_focus: list[str] = Field(default_factory=list)
    evidence_emphasis: str = "Weight credible primary web sources and recent publications."


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
    """Heuristic fallback without LLM."""
    lower = topic.lower()
    if " vs " in lower or " versus " in lower or "compare" in lower:
        scenario = "comparison"
    elif lower.startswith("how ") or "how to" in lower:
        scenario = "how_to_guide"
    elif "true" in lower and "?" in topic:
        scenario = "fact_check"
    elif "state of" in lower or "landscape" in lower or "trends" in lower:
        scenario = "landscape_survey"
    else:
        scenario = "general_research"
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
    """Classify report scenario using fast model with heuristic fallback."""
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
        scenario = str(parsed.get("scenario", "general_research"))
        sections = parsed.get("sections") or _SCENARIO_SECTIONS.get(
            scenario, _SCENARIO_SECTIONS["general_research"]
        )
        return ReportScenarioClassification(
            scenario=scenario,
            sections=[str(s) for s in sections],
            contextual_focus=[str(x) for x in parsed.get("contextual_focus", [])[:3]],
            evidence_emphasis=str(
                parsed.get("evidence_emphasis", "Weight credible primary web sources.")
            ),
        )
    except (EnhancedTimeoutError, TimeoutError, Exception):
        logger.debug("Report scenario classification failed, using fallback", exc_info=True)
        return fallback_classification(topic)
