"""Plan extraction utilities for parsing LLM responses.

Extracts structured Plan objects from markdown text with step formatting.
"""

from __future__ import annotations

import re

from soothe.protocols.planner import Plan, PlanStep

_MIN_STEP_DESCRIPTION_LENGTH = 5

_PLAN_STEP_RE = re.compile(
    r"\*\*Step\s+(\d+)[:\s]*(.+?)\*\*",
    re.IGNORECASE,
)


def parse_plan_from_text(goal: str, text: str) -> Plan:
    """Extract a Plan from markdown output (``**Step N: Title**`` format).

    Falls back to numbered/bulleted lines, then to a single-step plan.

    Args:
        goal: The original goal text.
        text: Raw markdown text from a planner.

    Returns:
        Parsed plan with extracted steps.
    """
    steps: list[PlanStep] = []
    matches = _PLAN_STEP_RE.findall(text)
    for i, (_num, title) in enumerate(matches, 1):
        steps.append(PlanStep(id=f"S_{i}", description=title.strip()))

    if not steps:
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        for i, line in enumerate(lines[:10], 1):
            cleaned = re.sub(r"^[\d\-\*\.]+\s*", "", line)
            if cleaned and len(cleaned) > _MIN_STEP_DESCRIPTION_LENGTH:
                steps.append(PlanStep(id=f"S_{i}", description=cleaned))

    if not steps:
        steps = [PlanStep(id="S_1", description=goal)]

    return Plan(goal=goal, steps=steps)
