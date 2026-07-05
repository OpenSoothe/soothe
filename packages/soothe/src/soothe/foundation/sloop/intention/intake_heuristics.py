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

_CASUAL_GREETING_MARKERS = re.compile(
    r"^(how\s+are\s+(you|u)|how'?s\s+it\s+going|how\s+is\s+it\s+going|"
    r"what'?s\s+up|whats\s+up|how\s+do\s+you\s+do|good\s+(morning|afternoon|evening)|"
    r"how\s+goes\s+it|how\s+r\s+u|sup)[!.?\s]*$",
    re.IGNORECASE,
)


def classify_intake_heuristic(query: str) -> IntentClassification | None:
    """Return an intake classification for obvious single-tool or chitchat lookups.

    Skips the intake LLM for short, unambiguous requests (weather, greetings)
    so routing stays on the fast path instead of simple/complex plan.
    """
    text = query.strip()
    if not text:
        return None

    if _GREETING_MARKERS.match(text):
        return _chitchat(text, _greeting_response(text))

    if _CASUAL_GREETING_MARKERS.match(text):
        return _chitchat(text, _casual_greeting_response(text))

    if len(text) > 100 or _COMPLEX_MARKERS.search(text):
        return None

    if _WEATHER_MARKERS.search(text):
        return _trivial(text, "I'll fetch the weather with a single tool call.")

    if _CLAWHUB_MARKERS.search(text):
        return _trivial(text, "I'll search ClawHub for matching skills.")

    return None


def _greeting_response(text: str) -> str:
    lowered = text.strip().lower().rstrip("!.? ")
    if lowered in {"thanks", "thank you", "谢谢"}:
        if "谢谢" in text:
            return "不客气！还有什么我可以帮你的吗？"
        return "You're welcome! Let me know if you need anything else."
    if any(token in text for token in ("你好", "嗨")):
        return "你好！有什么我可以帮你的吗？"
    return "Hello! How can I help you today?"


def _casual_greeting_response(text: str) -> str:
    lowered = text.strip().lower()
    if "morning" in lowered or "afternoon" in lowered or "evening" in lowered:
        return "Good day to you! How can I help?"
    if "what" in lowered and "up" in lowered:
        return "Not much — ready to help! What can I do for you?"
    return "I'm doing well, thanks for asking! How can I help you today?"


def _chitchat(query: str, response: str) -> IntentClassification:
    return IntentClassification(
        intake_label=IntakeLabel.CHITCHAT,
        goal_description=query,
        chitchat_response=response,
        task_complexity=derive_task_complexity_from_intake(IntakeLabel.CHITCHAT),
    )


def _trivial(query: str, reasoning: str) -> IntentClassification:
    return IntentClassification(
        intake_label=IntakeLabel.TRIVIAL,
        reasoning=reasoning,
        goal_description=query,
        task_complexity=derive_task_complexity_from_intake(IntakeLabel.TRIVIAL),
    )
