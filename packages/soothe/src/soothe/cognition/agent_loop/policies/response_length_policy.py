"""Response length intelligence system for intelligent synthesis sizing.

Determines optimal response length based on intent classification, goal type,
task complexity, and evidence patterns to guide synthesis generation.
"""

from __future__ import annotations

from enum import Enum


class ResponseLengthCategory(Enum):
    """Response length categories with word count ranges.

    Categories guide synthesis prompt to produce appropriately sized outputs:
    - BRIEF: Chitchat, quiz, simple questions (50-150 words)
    - CONCISE: Thread continuation, simple follow-ups (150-300 words)
    - STANDARD: Medium tasks, research synthesis (300-500 words)
    - COMPREHENSIVE: Architecture, complex implementation (600-800 words)
    """

    BRIEF = "brief"
    CONCISE = "concise"
    STANDARD = "standard"
    COMPREHENSIVE = "comprehensive"

    @property
    def min_words(self) -> int:
        """Minimum word count for this category."""
        ranges = {
            ResponseLengthCategory.BRIEF: 50,
            ResponseLengthCategory.CONCISE: 150,
            ResponseLengthCategory.STANDARD: 300,
            ResponseLengthCategory.COMPREHENSIVE: 600,
        }
        return ranges[self]

    @property
    def max_words(self) -> int:
        """Maximum word count for this category."""
        ranges = {
            ResponseLengthCategory.BRIEF: 150,
            ResponseLengthCategory.CONCISE: 300,
            ResponseLengthCategory.STANDARD: 500,
            ResponseLengthCategory.COMPREHENSIVE: 800,
        }
        return ranges[self]


def determine_response_length(
    intent_type: str,
    goal_type: str,
    task_complexity: str,
    evidence_volume: int,
    evidence_diversity: int,
) -> ResponseLengthCategory:
    """Determine optimal response length category based on scenario.

    Uses intent classification, goal type, task complexity, and evidence metrics
    to select appropriate response length category for synthesis generation.

    Args:
        intent_type: Intent classification (chitchat/quiz/thread_continuation/new_goal).
        goal_type: Goal type classification (architecture_analysis/research_synthesis/
                   implementation_summary/general_synthesis).
        task_complexity: Task complexity (chitchat/quiz/medium/complex).
        evidence_volume: Total evidence character count from successful steps.
        evidence_diversity: Number of unique step types from successful steps.

    Returns:
        ResponseLengthCategory with word count range for synthesis.

    Rules:
        1. Chitchat intent → BRIEF (greetings, fillers need short replies)
        2. Quiz intent → BRIEF (factual questions need concise answers)
        3. Thread continuation → CONCISE (follow-ups build on prior context)
        4. New goal + medium + research → STANDARD (research needs methodology)
        5. New goal + complex + architecture → COMPREHENSIVE (full structured report)
        6. New goal + complex + implementation → COMPREHENSIVE (detailed code patterns)
        7. Large evidence (≥2000 chars) + high diversity (≥4 steps) → bump to COMPREHENSIVE
        8. Default: STANDARD for medium complexity, COMPREHENSIVE for complex
    """
    # Rule 1 & 2: Chitchat and quiz always brief
    if intent_type in ("chitchat", "quiz"):
        return ResponseLengthCategory.BRIEF

    # Rule 3: Thread continuation concise (builds on prior context)
    if intent_type == "thread_continuation":
        return ResponseLengthCategory.CONCISE

    # Rules 4-6: New goal scenarios
    if intent_type == "new_goal":
        # Architecture analysis → comprehensive (structured layers, components)
        if goal_type == "architecture_analysis":
            return ResponseLengthCategory.COMPREHENSIVE

        # Implementation summary → comprehensive (code patterns, usage examples)
        if goal_type == "implementation_summary":
            return ResponseLengthCategory.COMPREHENSIVE

        # Research synthesis + medium → standard (methodology + findings)
        if goal_type == "research_synthesis" and task_complexity == "medium":
            return ResponseLengthCategory.STANDARD

        # Complex task → comprehensive by default
        if task_complexity == "complex":
            return ResponseLengthCategory.COMPREHENSIVE

        # Medium task → standard by default
        if task_complexity == "medium":
            return ResponseLengthCategory.STANDARD

    # Rule 7: Evidence volume and diversity override
    # Large evidence + high diversity suggests complex multi-faceted task
    if evidence_volume >= 2000 and evidence_diversity >= 4:
        return ResponseLengthCategory.COMPREHENSIVE

    # Moderate evidence suggests standard synthesis
    if evidence_volume >= 1000 and evidence_diversity >= 3:
        return ResponseLengthCategory.STANDARD

    # Rule 8: Default fallback
    # Unknown intent or edge cases → standard
    return ResponseLengthCategory.STANDARD


def calculate_evidence_metrics(step_results: list) -> tuple[int, int]:
    """Calculate evidence volume and diversity from step results.

    Args:
        step_results: List of step result objects with success flag and step_id.

    Returns:
        Tuple of (evidence_volume, evidence_diversity):
        - evidence_volume: Total character count from successful step evidence strings
        - evidence_diversity: Count of unique step types from successful steps
    """
    successful_steps = [r for r in step_results if r.success]

    # Calculate evidence volume (total chars)
    evidence_volume = 0
    for result in successful_steps:
        evidence_str = result.to_evidence_string(truncate=False)
        evidence_volume += len(evidence_str)

    # Calculate evidence diversity (unique step types)
    unique_step_ids = {r.step_id for r in successful_steps}
    evidence_diversity = len(unique_step_ids)

    return evidence_volume, evidence_diversity
