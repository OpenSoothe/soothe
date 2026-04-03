"""RFC-204: Criticality Evaluator for MUST goal confirmation.

Determines whether a proposed goal requires user approval before creation.
Uses rule-based signals + optional LLM judgment.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)

CriticalityLevel = Literal["must", "should", "nice"]

# Thresholds
_PRIORITY_MUST_THRESHOLD = 90
_MAX_DESCRIPTION_LENGTH = 500
_MUST_REASONS_THRESHOLD = 2

# Rule-based signals that trigger MUST level
HIGH_RISK_KEYWORDS = frozenset({
    "deploy", "delete", "drop", "destroy", "wipe", "erase",
    "migrate", "provision", "format", "shutdown", "kill",
    "root", "admin", "credential", "secret", "key",
    "billing", "payment", "subscription", "invoice",
})


@dataclass
class CriticalityResult:
    """Result of criticality evaluation."""

    level: CriticalityLevel
    reasons: list[str]
    requires_confirmation: bool = False

    @property
    def is_must(self) -> bool:
        """Check if level is 'must' (requires confirmation)."""
        return self.level == "must"

    @property
    def is_should(self) -> bool:
        """Check if level is 'should' (recommended review)."""
        return self.level == "should"


def evaluate_criticality(
    description: str,
    priority: int = 50,
    *,
    use_llm: bool = False,
) -> CriticalityResult:
    """RFC-204: Evaluate if a proposed goal requires user confirmation.

    Combines rule-based signals with optional LLM judgment.

    Args:
        description: Goal description text.
        priority: Goal priority (0-100).
        use_llm: Whether to apply LLM-based evaluation.

    Returns:
        CriticalityResult with level, reasons, and confirmation flag.
    """
    reasons: list[str] = []
    desc_lower = description.lower()

    # Rule-based signals
    if _matches_risk_keywords(desc_lower, HIGH_RISK_KEYWORDS):
        reasons.append("Contains high-risk operation keywords")

    if priority >= _PRIORITY_MUST_THRESHOLD:
        reasons.append(f"Very high priority (>={_PRIORITY_MUST_THRESHOLD})")

    if len(description) > _MAX_DESCRIPTION_LENGTH:
        reasons.append(f"Large scope goal (>{_MAX_DESCRIPTION_LENGTH} chars)")

    # Determine level from rules
    if len(reasons) >= _MUST_REASONS_THRESHOLD:
        return CriticalityResult(
            level="must",
            reasons=reasons,
            requires_confirmation=True,
        )

    if reasons:
        return CriticalityResult(
            level="should",
            reasons=reasons,
            requires_confirmation=True,
        )

    # LLM-based evaluation if available and no rule triggers
    if use_llm:
        return CriticalityResult(
            level="should",
            reasons=["LLM evaluation recommended — review manually"],
            requires_confirmation=False,
        )

    return CriticalityResult(
        level="nice",
        reasons=[],
        requires_confirmation=False,
    )


def _matches_risk_keywords(text: str, keywords: frozenset[str]) -> bool:
    """Check if text contains any high-risk keywords.

    Args:
        text: Text to scan (should be lowercased).
        keywords: Set of keywords to match.

    Returns:
        True if any keyword is found.
    """
    return any(kw in text for kw in keywords)
