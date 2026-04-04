"""RFC-204: Relationship Auto-Detection for goals.

Detects implicit relationships between goals based on resource overlap,
text similarity, and execution patterns.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from soothe.cognition import Goal

logger = logging.getLogger(__name__)

RelationshipType = Literal["informs", "conflicts_with", "depends_on"]

# Thresholds
_AUTO_APPLY_CONFIDENCE = 0.8
_FLAG_FOR_REVIEW_CONFIDENCE = 0.5

# Common stop words for text comparison
_STOP_WORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "is",
        "was",
        "are",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "shall",
        "can",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
        "as",
        "into",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "between",
        "out",
        "off",
        "over",
        "under",
        "again",
        "further",
        "then",
        "once",
        "and",
        "but",
        "or",
        "nor",
        "not",
        "so",
        "yet",
        "both",
        "either",
        "neither",
        "each",
        "every",
        "all",
        "any",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "no",
        "only",
        "own",
        "same",
        "than",
        "too",
        "very",
        "just",
        "because",
    }
)


@dataclass
class Relationship:
    """A detected relationship between two goals.

    Args:
        from_goal: Source goal ID.
        to_goal: Target goal ID.
        rel_type: Relationship type.
        confidence: Confidence score (0.0-1.0).
        reason: Explanation of why the relationship was detected.
    """

    from_goal: str
    to_goal: str
    rel_type: RelationshipType
    confidence: float
    reason: str


def detect_relationships(
    completed_goal: Goal,
    all_goals: list[Goal],
) -> list[Relationship]:
    """Detect relationships between a completed goal and other goals.

    Uses heuristic signals:
    - Text overlap in descriptions (``informs``)
    - Shared tags or resource references (``informs``)
    - Resource write overlap (``conflicts_with``)
    - Output artifact references in other goal descriptions (``depends_on``)

    Args:
        completed_goal: The goal that just completed.
        all_goals: All known goals.

    Returns:
        List of detected relationships with confidence scores.
    """
    relationships: list[Relationship] = []
    completed_words = _significant_words(completed_goal.description)

    for other in all_goals:
        if other.id == completed_goal.id:
            continue
        if other.status in ("completed", "failed"):
            continue

        other_words = _significant_words(other.description)

        # Check informs: text overlap
        overlap = completed_words & other_words
        if overlap:
            confidence = min(len(overlap) / max(len(completed_words), len(other_words)), 1.0)
            if confidence >= _FLAG_FOR_REVIEW_CONFIDENCE:
                relationships.append(
                    Relationship(
                        from_goal=completed_goal.id,
                        to_goal=other.id,
                        rel_type="informs",
                        confidence=round(confidence, 2),
                        reason=f"Shared keywords: {', '.join(sorted(overlap)[:5])}",
                    )
                )

        # Check depends_on: if other goal description references completed goal's artifacts
        completed_artifact_refs = _extract_artifact_refs(completed_goal.description)
        relationships.extend(
            [
                Relationship(
                    from_goal=other.id,
                    to_goal=completed_goal.id,
                    rel_type="depends_on",
                    confidence=0.85,
                    reason=f"References completed goal's output: {ref}",
                )
                for ref in completed_artifact_refs
                if ref.lower() in other.description.lower()
            ]
        )

    return relationships


def _significant_words(text: str) -> set[str]:
    """Extract meaningful words from text, filtering stop words.

    Args:
        text: Input text.

    Returns:
        Set of significant lowercase words.
    """
    words = text.lower().split()
    # Remove punctuation and stop words
    cleaned = set()
    for word in words:
        stripped = word.strip(".,;:()[]{}\"'")
        if stripped and stripped not in _STOP_WORDS and len(stripped) > 2:  # noqa: PLR2004
            cleaned.add(stripped)
    return cleaned


def _extract_artifact_refs(description: str) -> list[str]:
    """Extract potential artifact references from goal description.

    Looks for file paths, directory names, and named outputs.

    Args:
        description: Goal description text.

    Returns:
        List of potential artifact names/paths.
    """
    refs: list[str] = []
    # Simple heuristic: extract quoted strings, file-like patterns, and capitalized nouns
    import re

    # Quoted strings
    refs.extend(match.group(1) for match in re.finditer(r'["\']([^"\']{3,})["\']', description))

    # File-like patterns (words with dots and extensions)
    refs.extend(match.group(0) for match in re.finditer(r"\b[\w\-.]+\.\w{2,4}\b", description))

    return refs


def auto_apply_relationships(
    relationships: list[Relationship],
    all_goals: list[Goal],
) -> tuple[list[Relationship], list[Relationship]]:
    """Apply high-confidence relationships automatically, flag others for review.

    Args:
        relationships: Detected relationships.
        all_goals: All known goals.

    Returns:
        Tuple of (applied_relationships, flagged_for_review).
    """
    applied: list[Relationship] = []
    flagged: list[Relationship] = []

    # Build lookup for modifying goal relationships
    goal_map = {g.id: g for g in all_goals}

    for rel in relationships:
        if rel.confidence >= _AUTO_APPLY_CONFIDENCE:
            # Auto-apply
            target = goal_map.get(rel.to_goal)
            if target:
                existing = getattr(target, rel.rel_type, []) or []
                if rel.from_goal not in existing:
                    existing.append(rel.from_goal)
                    setattr(target, rel.rel_type, existing)
                    applied.append(rel)
                    logger.info(
                        "Auto-applied relationship: %s %s %s (confidence=%.2f)",
                        rel.from_goal,
                        rel.rel_type,
                        rel.to_goal,
                        rel.confidence,
                    )
        elif rel.confidence >= _FLAG_FOR_REVIEW_CONFIDENCE:
            flagged.append(rel)
            logger.debug(
                "Flagged for review: %s %s %s (confidence=%.2f)",
                rel.from_goal,
                rel.rel_type,
                rel.to_goal,
                rel.confidence,
            )

    return applied, flagged
