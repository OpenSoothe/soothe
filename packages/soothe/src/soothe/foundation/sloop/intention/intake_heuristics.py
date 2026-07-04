"""Deterministic intake shortcuts before the LLM classifier (RFC-630)."""

from __future__ import annotations

import re

from soothe.foundation.sloop.intention.models import (
    IntakeLabel,
    IntentClassification,
    derive_task_complexity_from_intake,
)

_COMPLEX_MARKERS = re.compile(
    r"(迁移|重构|refactor|architect|architecture|implement a|build a|design a|"
    r"多步|多个|multi-step|codebase|代码库|分析.+(架构|结构))",
    re.IGNORECASE,
)

_WEATHER_MARKERS = re.compile(
    r"(天气|weather|forecast|forecasts|温度|气温|wttr|气象)",
    re.IGNORECASE,
)

_CLAWHUB_MARKERS = re.compile(
    r"(clawhub|claw\s+hub|skill\s+registry|community\s+skills?)",
    re.IGNORECASE,
)

_GREETING_MARKERS = re.compile(
    r"^(hi|hello|hey|thanks|thank you|你好|谢谢|嗨)[!.?\s]*$",
    re.IGNORECASE,
)


def classify_intake_heuristic(query: str) -> IntentClassification | None:
    """Return a trivial intake classification for obvious single-tool lookups.

    Skips the intake LLM for short, unambiguous requests (weather, greetings)
    so routing stays on the trivial fast path instead of simple/complex plan.
    """
    text = query.strip()
    if not text:
        return None

    if _GREETING_MARKERS.match(text):
        return _trivial(text, "I'll respond directly.")

    if len(text) > 100 or _COMPLEX_MARKERS.search(text):
        return None

    if _WEATHER_MARKERS.search(text):
        return _trivial(text, "I'll fetch the weather with a single tool call.")

    if _CLAWHUB_MARKERS.search(text):
        return _trivial(text, "I'll search ClawHub for matching skills.")

    return None


def _trivial(query: str, reasoning: str) -> IntentClassification:
    return IntentClassification(
        intent_type="agentic",
        intake_label=IntakeLabel.TRIVIAL,
        reasoning=reasoning,
        goal_description=query,
        task_complexity=derive_task_complexity_from_intake(IntakeLabel.TRIVIAL),
    )
