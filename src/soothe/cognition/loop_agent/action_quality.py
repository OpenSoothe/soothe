"""Action quality enhancement for progressive specificity.

This module implements post-processing for action descriptions to ensure
they become progressively specific across iterations (RFC-603).
"""

import logging
import re

from soothe.cognition.loop_agent.schemas import StepResult

logger = logging.getLogger(__name__)

_SPECIFICITY_PATTERNS = [
    r"\d+\s+(files?|components?|modules?|layers?|directories)",
    r"(examine|analyze|inspect|investigate|review)\s+\S+/",
    r"based on (the|my|these)\s+(findings|results|analysis|discoveries)",
    r"(identified|found|discovered|located)\s+\d+",
    r"(in|within|from)\s+\S+/\s+",
]

_MIN_ACTION_LENGTH_FOR_OVERLAP = 20


def _is_specific_action(action: str) -> bool:
    """Check if action description is specific (not generic).

    Specific actions contain:
    - Numbers (e.g., "5 files")
    - Paths (e.g., "examine src/")
    - References to prior work (e.g., "based on findings")
    - Discoveries (e.g., "found 3 patterns")

    Args:
        action: Action description text

    Returns:
        True if action is specific, False if generic
    """
    if not action or not action.strip():
        return False

    action_lower = action.lower().strip()

    # Check specificity patterns
    return any(re.search(pattern, action_lower, re.IGNORECASE) for pattern in _SPECIFICITY_PATTERNS)


def _normalize_action(action: str) -> str:
    """Normalize action for comparison.

    Args:
        action: Action description

    Returns:
        Normalized action (lowercase, single whitespace)
    """
    return re.sub(r"\s+", " ", action.lower().strip())


def _is_repeated_action(action: str, previous_actions: list[str], threshold: float = 0.85) -> bool:
    """Check if action repeats recent actions.

    Args:
        action: Current action description
        previous_actions: Last N actions from history
        threshold: Similarity threshold (0.85 = 85% similar)

    Returns:
        True if action repeats previous action
    """
    if not previous_actions:
        return False

    normalized_current = _normalize_action(action)

    # Check against last 3 actions
    for prev_action in previous_actions[-3:]:
        normalized_prev = _normalize_action(prev_action)

        # Simple similarity: check if normalized strings match
        if normalized_current == normalized_prev:
            return True

        # Check substring overlap for longer actions
        curr_long = len(normalized_current) > _MIN_ACTION_LENGTH_FOR_OVERLAP
        prev_long = len(normalized_prev) > _MIN_ACTION_LENGTH_FOR_OVERLAP
        if curr_long and prev_long:
            # Split into words and check overlap
            current_words = set(normalized_current.split())
            prev_words = set(normalized_prev.split())
            overlap = len(current_words & prev_words) / max(len(current_words), len(prev_words))
            if overlap >= threshold:
                return True

    return False


def _extract_paths_from_evidence(step_results: list[StepResult]) -> list[str]:
    """Extract file/directory paths from recent step results.

    Args:
        step_results: Recent step execution results

    Returns:
        List of extracted paths (last 3 unique)
    """
    paths = []

    for result in step_results[-5:]:  # Last 5 results
        if not result.output:
            continue

        # Extract paths like "src/", "docs/", etc.
        path_pattern = r"(?:examine|analyze|read|list|inspect)\s+(\S+/)"
        matches = re.findall(path_pattern, result.output, re.IGNORECASE)
        paths.extend(matches)

    # Return last 3 unique paths
    seen = set()
    unique_paths = []
    for path in paths:
        if path not in seen:
            seen.add(path)
            unique_paths.append(path)

    return unique_paths[-3:]


def enhance_action_specificity(
    action: str,
    _goal: str,
    iteration: int,
    previous_actions: list[str],
    step_results: list[StepResult],
) -> str:
    """Enhance action description to be more specific.

    Strategy:
    1. If already specific → keep as-is
    2. If repeated → derive new action from evidence
    3. If generic → add context from step results

    Args:
        action: Current action description
        _goal: Goal description (reserved for future use)
        iteration: Current iteration number
        previous_actions: Previous action descriptions
        step_results: Recent step execution results

    Returns:
        Enhanced action description (or original if already good)
    """
    if not action or not action.strip():
        return action

    logger.debug(
        "[Enhance] Iteration %d: Analyzing action: %s",
        iteration,
        action[:80],
    )

    # Step 1: Check if already specific
    if _is_specific_action(action):
        logger.debug("[Enhance] Action is already specific, keeping as-is")
        return action

    logger.debug("[Enhance] Action is generic, checking for repetition...")

    # Step 2: Check for repetition
    if _is_repeated_action(action, previous_actions):
        logger.warning(
            "[Enhance] REPETITION DETECTED! Action repeats previous. Previous count: %d",
            len(previous_actions),
        )

        # Derive new action from recent evidence
        paths = _extract_paths_from_evidence(step_results)
        logger.debug("[Enhance] Extracted paths from evidence: %s", paths)

        if paths:
            # Create specific action from discovered paths
            path_list = ", ".join(paths[:3])
            enhanced = f"Continue analysis in {path_list} based on previous findings"
            logger.info("[Enhance] Enhanced with paths: %s", enhanced[:80])
            return enhanced

        # Fallback: add iteration-specific context
        if iteration > 1:
            enhanced = f"Deepen investigation based on {iteration - 1} previous iterations"
            logger.info("[Enhance] Enhanced with iteration context: %s", enhanced)
            return enhanced

    # Step 3: Enhance generic action with context
    generic_prefixes = [
        "use file and shell tools",
        "gather facts",
        "collect information",
    ]

    action_lower = action.lower()
    is_generic = any(prefix in action_lower for prefix in generic_prefixes)

    if is_generic and step_results:
        logger.debug("[Enhance] Generic action detected, adding context...")
        # Add evidence-based context
        paths = _extract_paths_from_evidence(step_results)
        if paths:
            path_context = paths[0]  # Use first discovered path
            enhanced = f"Examine {path_context} to gather specific evidence"
            logger.info("[Enhance] Enhanced generic action: %s", enhanced[:80])
            return enhanced

    # Default: return original (no enhancement needed)
    logger.debug("[Enhance] No enhancement applied, returning original")
    return action
