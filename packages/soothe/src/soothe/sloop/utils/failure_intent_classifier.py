"""Failure intent classification for reflection (IG-433)."""

from __future__ import annotations

import logging
import re
from typing import Literal, NamedTuple

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

FailureCategory = Literal[
    "missing_prerequisite",
    "permission_denied",
    "resource_unavailable",
    "syntax_error",
    "logic_error",
    "timeout",
    "unknown",
]

SuggestedAction = Literal["create_prerequisite", "retry", "escalate", "skip"]


class FailureKeywordRule(NamedTuple):
    """Static keyword rule for offline failure intent fallback."""

    category: FailureCategory
    keywords: frozenset[str]
    confidence: float
    action: SuggestedAction


_KEYWORD_RULES: list[FailureKeywordRule] = [
    FailureKeywordRule(
        "missing_prerequisite",
        frozenset(
            {
                "missing",
                "not found",
                "not installed",
                "not available",
                "not configured",
                "no such",
                "does not exist",
                "cannot find",
                "dependency",
                "prerequisite",
            }
        ),
        0.85,
        "create_prerequisite",
    ),
    FailureKeywordRule(
        "permission_denied",
        frozenset(
            {"permission denied", "access denied", "forbidden", "unauthorized", "not allowed"}
        ),
        0.9,
        "escalate",
    ),
    FailureKeywordRule(
        "resource_unavailable",
        frozenset({"out of memory", "no space", "disk full", "connection refused", "unavailable"}),
        0.8,
        "retry",
    ),
    FailureKeywordRule(
        "syntax_error",
        frozenset({"syntaxerror", "syntax error", "parse error", "invalid syntax"}),
        0.85,
        "retry",
    ),
    FailureKeywordRule(
        "logic_error",
        frozenset({"assertionerror", "valueerror", "typeerror", "runtime error", "exception"}),
        0.75,
        "retry",
    ),
    FailureKeywordRule(
        "timeout",
        frozenset({"timeout", "timed out", "deadline exceeded"}),
        0.9,
        "retry",
    ),
]


class FailureIntent(BaseModel):
    """Classified failure intent from step output text."""

    category: FailureCategory
    confidence: float = Field(ge=0.0, le=1.0)
    suggested_action: SuggestedAction
    extracted_entities: list[str] = Field(default_factory=list)


def _extract_entities(text: str) -> list[str]:
    """Extract quoted strings and file-like tokens from failure text."""
    entities: list[str] = []
    entities.extend(match.group(1) for match in re.finditer(r'["\']([^"\']{2,80})["\']', text))
    entities.extend(match.group(0) for match in re.finditer(r"\b[\w\-./]+\.\w{2,5}\b", text))
    return list(dict.fromkeys(entities))[:10]


def classify_failure_intent_keyword(text: str) -> FailureIntent:
    """Offline keyword-based failure intent fallback when LLM is unavailable."""
    lowered = (text or "").lower()
    best_category: FailureCategory = "unknown"
    best_confidence = 0.4
    best_action: SuggestedAction = "retry"

    for rule in _KEYWORD_RULES:
        if any(kw in lowered for kw in rule.keywords):
            if rule.confidence > best_confidence:
                best_category = rule.category
                best_confidence = rule.confidence
                best_action = rule.action

    return FailureIntent(
        category=best_category,
        confidence=best_confidence,
        suggested_action=best_action,
        extracted_entities=_extract_entities(text),
    )
